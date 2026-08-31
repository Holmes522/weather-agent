"""只读天气知识库：校验 Markdown、生成本地向量并执行有界检索。"""

from dataclasses import dataclass
import hashlib
import math
from pathlib import Path
import re
from typing import Dict, Iterable, List, Sequence, Tuple
import unicodedata
from urllib.parse import urlparse

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.vectorstores import InMemoryVectorStore


class KnowledgeBaseError(Exception):
    """知识文档或索引不满足安全契约。"""


class KnowledgeQueryError(Exception):
    """知识检索查询无效。"""


@dataclass(frozen=True)
class KnowledgeChunk:
    content: str
    title: str
    section: str
    source_name: str
    source_url: str
    score: float


MAX_DOCUMENT_FILES = 32
MAX_DOCUMENT_BYTES = 64 * 1024
MAX_INDEXED_CHUNKS = 128
MAX_CHUNK_CHARACTERS = 1_600
MAX_QUERY_CHARACTERS = 200
MAX_RESULTS = 3
DEFAULT_MIN_SCORE = 0.16
REQUIRED_METADATA = {"title", "source_name", "source_url", "topics"}

DOMAIN_ALIASES = {
    "雷电": ("雷电", "雷雨", "打雷", "闪电"),
    "暴雨": ("暴雨", "大雨", "强降雨", "洪涝", "积水", "内涝"),
    "高温": ("高温", "炎热", "太热", "中暑", "热射病"),
    "寒冷": ("寒潮", "低温", "寒冷", "降温", "冰冻", "太冷"),
    "大风": ("大风", "风大", "风很大", "刮风", "强风", "台风"),
    "户外": ("户外", "爬山", "登山", "露营", "跑步", "骑行", "运动"),
    "穿衣": ("穿衣", "衣服", "怎么穿", "穿什么", "保暖"),
    "驾车": ("驾车", "开车", "行车", "自驾", "车辆"),
}
PRIMARY_WEATHER_DOMAINS = frozenset({"雷电", "暴雨", "高温", "寒冷", "大风"})


class LocalHashEmbeddings(Embeddings):
    """无需网络的词法 Hash Embeddings，适合小型固定中文知识库。"""

    def __init__(self, dimensions: int = 768):
        if dimensions < 128:
            raise ValueError("embedding dimensions are too small")
        self._dimensions = dimensions

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> List[float]:
        return self._embed(text)

    def _embed(self, text: str) -> List[float]:
        vector = [0.0] * self._dimensions
        for feature, weight in _text_features(text):
            digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
            value = int.from_bytes(digest, "big")
            index = value % self._dimensions
            sign = 1.0 if value & 1 else -1.0
            vector[index] += sign * weight
        norm = math.sqrt(sum(value * value for value in vector))
        if norm:
            return [value / norm for value in vector]
        return vector


class WeatherKnowledgeBase:
    """在内存向量库中检索经过校验的天气安全知识。"""

    def __init__(
        self,
        vector_store: InMemoryVectorStore,
        chunk_count: int,
        min_score: float = DEFAULT_MIN_SCORE,
    ):
        self._vector_store = vector_store
        self._chunk_count = chunk_count
        self._min_score = min_score

    @classmethod
    def from_directory(cls, directory: Path) -> "WeatherKnowledgeBase":
        resolved = directory.resolve()
        if not resolved.is_dir():
            raise KnowledgeBaseError("knowledge directory is missing")
        paths = sorted(resolved.glob("*.md"))
        if not paths or len(paths) > MAX_DOCUMENT_FILES:
            raise KnowledgeBaseError("knowledge document count is invalid")

        documents: List[Document] = []
        for path in paths:
            if path.is_symlink() or path.stat().st_size > MAX_DOCUMENT_BYTES:
                raise KnowledgeBaseError("knowledge document is unsafe or too large")
            documents.extend(_load_markdown_document(path))
            if len(documents) > MAX_INDEXED_CHUNKS:
                raise KnowledgeBaseError("knowledge chunk count is too large")
        if not documents:
            raise KnowledgeBaseError("knowledge base has no content")

        # 官方示例使用 InMemoryVectorStore.from_documents 构建小型 RAG 索引。
        # Source: https://docs.langchain.com/oss/python/langgraph/agentic-rag
        vector_store = InMemoryVectorStore.from_documents(
            documents=documents,
            embedding=LocalHashEmbeddings(),
        )
        return cls(vector_store, len(documents))

    def search(self, query: str, limit: int = MAX_RESULTS) -> Tuple[KnowledgeChunk, ...]:
        normalized_query = query.strip() if isinstance(query, str) else ""
        if (
            not normalized_query
            or len(normalized_query) > MAX_QUERY_CHARACTERS
            or any(ord(character) < 32 for character in normalized_query)
        ):
            raise KnowledgeQueryError("knowledge query is invalid")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_RESULTS:
            raise KnowledgeQueryError("knowledge result limit is invalid")

        primary_domains = _matching_domains(normalized_query) & PRIMARY_WEATHER_DOMAINS
        document_filter = (
            lambda document: bool(
                primary_domains.intersection(document.metadata.get("domains", ()))
            )
            if primary_domains
            else None
        )
        candidates = self._vector_store.similarity_search_with_score(
            normalized_query,
            k=min(self._chunk_count, limit * 3),
            filter=document_filter,
        )
        results: List[KnowledgeChunk] = []
        seen = set()
        for document, raw_score in candidates:
            score = float(raw_score)
            key = (document.metadata["title"], document.metadata["section"])
            if score < self._min_score or key in seen:
                continue
            seen.add(key)
            results.append(
                KnowledgeChunk(
                    content=document.metadata["content"],
                    title=document.metadata["title"],
                    section=document.metadata["section"],
                    source_name=document.metadata["source_name"],
                    source_url=document.metadata["source_url"],
                    score=round(min(1.0, max(0.0, score)), 4),
                )
            )
            if len(results) == limit:
                break
        return tuple(results)


def build_default_knowledge_base() -> WeatherKnowledgeBase:
    """从应用随附的只读知识目录构建进程内索引。"""

    return WeatherKnowledgeBase.from_directory(Path(__file__).with_name("knowledge"))


def _load_markdown_document(path: Path) -> List[Document]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise KnowledgeBaseError("knowledge document cannot be read") from error
    if "\x00" in text:
        raise KnowledgeBaseError("knowledge document contains invalid characters")
    metadata, body = _parse_frontmatter(text)
    _validate_metadata(metadata)

    documents: List[Document] = []
    for section, content in _markdown_sections(body):
        for chunk in _bounded_chunks(content):
            search_text = (
                f"标题：{metadata['title']}\n"
                f"主题：{metadata['topics']}\n"
                f"章节：{section}\n"
                f"内容：{chunk}"
            )
            documents.append(
                Document(
                    page_content=search_text,
                    metadata={
                        "title": metadata["title"],
                        "section": section,
                        "source_name": metadata["source_name"],
                        "source_url": metadata["source_url"],
                        "content": chunk,
                        "domains": sorted(
                            _matching_domains(
                                f"{metadata['title']} {metadata['topics']} {section}"
                            )
                        ),
                    },
                )
            )
    return documents


def _parse_frontmatter(text: str) -> Tuple[Dict[str, str], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise KnowledgeBaseError("knowledge metadata is missing")
    try:
        closing_index = next(
            index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---"
        )
    except StopIteration as error:
        raise KnowledgeBaseError("knowledge metadata is incomplete") from error

    metadata: Dict[str, str] = {}
    for line in lines[1:closing_index]:
        key, separator, value = line.partition(":")
        normalized_key = key.strip()
        normalized_value = value.strip()
        if not separator or normalized_key in metadata:
            raise KnowledgeBaseError("knowledge metadata is invalid")
        metadata[normalized_key] = normalized_value
    return metadata, "\n".join(lines[closing_index + 1 :]).strip()


def _validate_metadata(metadata: Dict[str, str]) -> None:
    if set(metadata) != REQUIRED_METADATA:
        raise KnowledgeBaseError("knowledge metadata fields are invalid")
    if any(
        not value
        or len(value) > 500
        or any(ord(character) < 32 for character in value)
        for value in metadata.values()
    ):
        raise KnowledgeBaseError("knowledge metadata value is invalid")
    if len(metadata["title"]) > 100 or len(metadata["source_name"]) > 100:
        raise KnowledgeBaseError("knowledge metadata value is too long")

    parsed = urlparse(metadata["source_url"])
    hostname = parsed.hostname.lower() if parsed.hostname else ""
    if (
        parsed.scheme != "https"
        or not hostname
        or (hostname != "gov.cn" and not hostname.endswith(".gov.cn"))
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise KnowledgeBaseError("knowledge source URL is not an official HTTPS URL")


def _markdown_sections(body: str) -> List[Tuple[str, str]]:
    if not body:
        raise KnowledgeBaseError("knowledge document body is empty")
    sections: List[Tuple[str, str]] = []
    current_section = "概览"
    current_lines: List[str] = []
    for line in body.splitlines():
        if line.startswith("## "):
            _append_section(sections, current_section, current_lines)
            current_section = line[3:].strip()
            current_lines = []
        elif not line.startswith("# "):
            current_lines.append(line)
    _append_section(sections, current_section, current_lines)
    if not sections:
        raise KnowledgeBaseError("knowledge document has no sections")
    return sections


def _append_section(
    sections: List[Tuple[str, str]], section: str, lines: Sequence[str]
) -> None:
    content = "\n".join(lines).strip()
    if not section or len(section) > 100:
        raise KnowledgeBaseError("knowledge section title is invalid")
    if content:
        sections.append((section, content))


def _bounded_chunks(content: str) -> Iterable[str]:
    paragraphs = [value.strip() for value in re.split(r"\n\s*\n", content) if value.strip()]
    current = ""
    for paragraph in paragraphs:
        remaining = paragraph
        while len(remaining) > MAX_CHUNK_CHARACTERS:
            if current:
                yield current
                current = ""
            yield remaining[:MAX_CHUNK_CHARACTERS]
            remaining = remaining[MAX_CHUNK_CHARACTERS:]
        candidate = f"{current}\n\n{remaining}".strip() if current else remaining
        if len(candidate) > MAX_CHUNK_CHARACTERS:
            yield current
            current = remaining
        else:
            current = candidate
    if current:
        yield current


def _text_features(text: str) -> Iterable[Tuple[str, float]]:
    normalized = unicodedata.normalize("NFKC", text).lower()
    for word in re.findall(r"[a-z0-9]+", normalized):
        if len(word) > 1:
            yield f"word:{word}", 1.0

    chinese = re.findall(r"[\u3400-\u9fff]", normalized)
    stop_characters = set("的了是在和与及或有为对中时可要应将把这那呢吗呀啊什么怎么")
    for character in chinese:
        if character not in stop_characters:
            yield f"char:{character}", 0.35
    for size, weight in ((2, 1.0), (3, 1.2)):
        for index in range(len(chinese) - size + 1):
            token = "".join(chinese[index : index + size])
            yield f"cjk{size}:{token}", weight

    for canonical, aliases in DOMAIN_ALIASES.items():
        if any(alias in normalized for alias in aliases):
            yield f"domain:{canonical}", 2.5


def _matching_domains(text: str) -> set[str]:
    normalized = unicodedata.normalize("NFKC", text).lower()
    return {
        canonical
        for canonical, aliases in DOMAIN_ALIASES.items()
        if any(alias in normalized for alias in aliases)
    }
