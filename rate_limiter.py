"""适用于单进程免费部署的线程安全滑动窗口限流器。"""

from collections import deque
from math import ceil
from threading import Lock
from time import monotonic
from typing import Callable, Deque, Dict, Tuple


class InMemoryRateLimiter:
    """按客户端键限制固定时间窗内的请求数，并限制内存中的客户端数量。"""

    def __init__(
        self,
        max_requests: int,
        window_seconds: int = 60,
        max_clients: int = 10_000,
        clock: Callable[[], float] = monotonic,
    ):
        if max_requests < 1 or window_seconds < 1 or max_clients < 1:
            raise ValueError("rate limiter limits must be positive")
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._max_clients = max_clients
        self._clock = clock
        self._requests: Dict[str, Deque[float]] = {}
        self._lock = Lock()

    def check(self, client_key: str) -> Tuple[bool, int]:
        """返回是否放行，以及被拒绝时建议等待的秒数。"""

        now = self._clock()
        cutoff = now - self._window_seconds
        with self._lock:
            requests = self._requests.get(client_key)
            if requests is None:
                self._make_room(now)
                requests = deque()
                self._requests[client_key] = requests

            while requests and requests[0] <= cutoff:
                requests.popleft()

            if len(requests) >= self._max_requests:
                retry_after = max(1, ceil(self._window_seconds - (now - requests[0])))
                return False, retry_after

            requests.append(now)
            return True, 0

    def _make_room(self, now: float) -> None:
        if len(self._requests) < self._max_clients:
            return

        cutoff = now - self._window_seconds
        expired_keys = [
            key
            for key, requests in self._requests.items()
            if not requests or requests[-1] <= cutoff
        ]
        for key in expired_keys:
            del self._requests[key]

        if len(self._requests) >= self._max_clients:
            self._requests.pop(next(iter(self._requests)))
