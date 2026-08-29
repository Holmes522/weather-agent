# Weather Export Specification

## Goal

用户可用自然语言把最近一次真实天气查询结果导出为 Word、Excel、PDF 或 Markdown，并通过一次性风格的临时链接下载。

## Inputs

- 导出动作词：`导出`、`保存`、`生成`、`输出`、`下载`、`存储`、`做成`、`整理成`。
- 格式别名：Word/Docx、Excel/Xlsx/Execl、PDF、Markdown/MD。
- 数据来源：同一 `session_id` 最近一次由天气客户端返回的结构化天气结果，最多 5 个城市。
- 同一句可同时包含天气查询和导出要求，例如“把深圳和广州明天天气导出为 Excel”。

## Outputs

- `POST /chat` 在成功导出时增加 `export`：`id`、`format`、`filename`、`download_url`。
- `GET /api/exports/<export_id>` 返回附件，类型分别为 DOCX、XLSX、PDF 和 UTF-8 Markdown。
- 文件至少包含城市、日期、温度、天气状况、湿度、风速、是否有雨、建议和天气服务来源。

## Behavior

- 只有导出动作但没有格式时，提示用户选择四种格式，不生成文件。
- 没有可用天气快照时，提示先查询天气，不使用模型编造数据。
- 导出请求不改变最近天气快照；导出链接过期后返回 404。
- 文件名由服务端生成并清洗，用户不能指定服务器路径。

## Safety and limits

- 文件只保存在有 TTL、数量上限和大小上限的进程内存储中。
- 导出 ID 使用不可预测随机值；响应设置 `Cache-Control: no-store`。
- 单次最多导出 5 条天气记录，不执行宏、公式、HTML 或用户提供的模板。

## Acceptance tests

- 四种格式都能生成并由对应解析库重新打开。
- `/chat` 支持先查天气后导出，也支持同句查询并导出。
- 缺少格式、缺少快照、未知/过期 ID 均返回稳定且可理解的结果。
