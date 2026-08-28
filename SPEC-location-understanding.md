# Spec: location-understanding

## Objective

让一次查询包含最多 5 个城市，并允许查询白名单之外的全球城市。未知城市必须显式报错，不能静默复用上一次城市。对已确认的常见错别字返回纠正后的标准城市名。

## Contract

- `parse_query()` 返回按文本顺序去重的 `location_terms`。
- `CityResolver.resolve()` 将地点文本转换成统一的 `City(name, latitude, longitude, country_code)`。
- 动态查询使用可配置的 Nominatim Search API，携带应用 User-Agent，串行限速为每秒至多一次，并缓存结果。
- `大利` 作为已确认别名纠正为 `大理`，响应暴露 `corrected_from`。

## Testing

- 单元测试覆盖“深圳和广州”、白名单外城市、空结果、异常响应和纠错。
- 测试使用请求桩，不访问真实网络。

## Boundaries

- Always：第三方响应类型校验；最多 5 个地点；只在成功后写会话。
- Ask first：接入收费地理编码、数据库或 LLM。
- Never：城市解析失败时回退到旧城市；无缓存地批量调用公共地理编码。

## Success Criteria

1. “深圳和广州明天天气什么样”产生两个有序结果。
2. “纽约明天天气”可以通过地理编码获得坐标。
3. “大利天气如何”查询并显示“大理”，同时说明已纠正。
4. 一个明确但查不到的城市返回 `CITY_NOT_FOUND`。
