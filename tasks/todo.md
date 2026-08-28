# Weather Query Agent MVP Tasks

- [x] Task 1: 配置、解析器和会话状态；验证：`pytest tests/test_parser.py`
- [x] Task 2: OpenWeatherMap 客户端；验证：`pytest tests/test_weather_client.py`
- [x] Task 3: Flask `/chat` 路由；验证：`pytest tests/test_app.py`
- [x] Task 4: 端到端 mock API 流程；验证：`pytest`
- [x] Task 5: 文档与环境模板；验证：按 README curl 示例检查
- [x] Task 6: 安全检查与最终审查；验证：无 `.env`、无真实 Key、全套件通过
- [x] Task 7: 增加和风天气 Provider；验证：`pytest tests/test_qweather_client.py`
- [x] Task 8: 支持请求级 Provider 选择；验证：`pytest tests/test_app.py`
- [x] Task 9: 多城市提取、动态城市解析和纠错；验证：`pytest tests/test_parser.py tests/test_geocoding.py`
- [x] Task 10: 意图化回复和多轮上下文；验证：`pytest tests/test_conversation.py tests/test_app.py`
- [x] Task 11: 多城市 API/UI 展示；验证：完整测试与浏览器运行时检查
- [ ] Task 12: OpenAI 兼容模型客户端；验证：`pytest tests/test_llm_client.py`
- [ ] Task 13: 受限天气工具 Agent 编排；验证：`pytest tests/test_agent.py`
- [ ] Task 14: `/chat` Agent 集成和有限会话历史；验证：`pytest tests/test_ai_chat.py`
- [ ] Task 15: 本机模型配置接口和页面；验证：`pytest tests/test_llm_config.py`
- [ ] Task 16: 文档、完整测试、安全审查和浏览器验证；验证：`pytest -q`
