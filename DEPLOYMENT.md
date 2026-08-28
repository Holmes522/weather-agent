# Render 免费部署指南

项目已经包含 `render.yaml`，可以通过 Render Blueprint 创建免费 Web Service。

## 1. 创建服务

1. 登录 <https://dashboard.render.com/>。
2. 选择 **New → Blueprint**。
3. 连接 GitHub 仓库 `Holmes522/weather-agent`。
4. Render 读取仓库根目录的 `render.yaml` 后，确认创建服务。

Blueprint 会自动设置：

- 免费 Web Service；
- `WEATHER_PROVIDER=openmeteo`，无需 API Key；
- `APP_ENV=production`，关闭公网配置页；
- 每个客户端每分钟最多 30 次聊天请求；
- Gunicorn 单 Worker、四线程；
- `/health` 健康检查。
- Nominatim 动态城市搜索（带缓存、每秒一次串行限速和 OpenStreetMap 署名）。

构建和启动命令已经写入 `render.yaml`，无需手工填写。

## 2. 验证部署

部署状态变成 **Live** 后，打开 Render 提供的 `https://...onrender.com` 地址。

依次检查：

1. 首页可以打开；
2. 输入“北京今天天气怎么样？”可以返回天气；
3. `https://你的域名/health` 返回 `{"status":"ok"}`；
4. `https://你的域名/settings` 返回 404，这是生产环境的预期保护。

免费实例可能被平台重启，当前多轮会话保存在内存中，因此重启后会清空。

## 3. 可选：改用其他天气服务

在 Render 服务的 **Environment** 页面添加环境变量，不要把真实 Key 写入代码或 `render.yaml`。

### 和风天气

```text
WEATHER_PROVIDER=qweather
QWEATHER_API_KEY=重新生成的API密钥
QWEATHER_API_HOST=你的专属主机名.qweatherapi.com
```

### OpenWeather

```text
WEATHER_PROVIDER=openweather
OPENWEATHER_API_KEY=重新生成的API密钥
```

保存环境变量后 Render 会重新部署。其他已经配置 Key 的 Provider 也会出现在聊天页下拉框中。

## 4. 回滚

如果新版本出现问题，在 Render 的 **Deploys** 页面选择上一个成功部署并执行回滚；也可以在 Git 中 revert 对应提交后重新推送。

## 免费版限制

- 仅适合演示、学习和低流量非商业使用；
- Open-Meteo 免费接口没有可用性保证，并要求显示数据来源；
- 公共 Nominatim 适合中低流量的用户触发式搜索；流量增加后需将 `GEOCODING_API_URL` 切换到自托管或商业兼容服务；
- 限流与多轮会话都在单个进程内存中；
- 不包含 Redis、数据库、用户登录或管理员后台；
- 生产环境不能通过网页添加 API Key，只能由站点管理员设置环境变量。
