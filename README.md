# RouteHub

![App Icon](config_ui/static/icons/icon.png)

RouteHub 是一个本地 OpenAI-compatible 路由代理项目，提供：

- 统一本地代理入口
- 多上游路由与失败切换
- 健康检查、熔断与自动恢复
- 请求与 token 统计
- 本地管理控制台

## 服务入口

- 路由代理：`http://127.0.0.1:8330`
- 管理控制台：`http://127.0.0.1:8340`

## 启动

Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\launch-service.ps1
```

Linux / macOS:

```bash
chmod +x ./launch-service.sh
./launch-service.sh
```

## 配置文件位置

当前默认配置路径优先级：

1. 命令行 `--config`
2. 环境变量 `ROUTER_PROXY_CONFIG`
3. 用户目录默认配置

默认用户目录配置位置：

- Windows: `%USERPROFILE%\.router-proxy\router_config.json`
- Linux / macOS: `~/.router-proxy/router_config.json`

首次启动时，如果配置文件不存在，系统会自动在用户目录生成一份最小默认配置：

- `upstreams` 为空
- 其他字段使用系统默认值

然后用户可以直接打开控制台填写配置，不需要手动复制模板。

## 示例配置

示例模板：

```text
router_config.example.json
```

它只作为参考模板，不要求用户手动复制。

## 当前能力

- 多上游转发
- 路由模式
  - `strict_priority`
  - `smart`
- 模型名映射
- 上游健康检查
- 熔断与自动恢复
- 手动 health check
- 手动 test request
- reset upstream
- Route Map 可视化
- 请求统计与 token 统计
- 前端配置管理

## 当前状态机制

每个 upstream 当前可能显示为：

- `Healthy`
- `Unhealthy`
- `Circuit Open`
- `Disabled`

### health check 与自动补测

当 health check 失败时，系统会自动补发一次轻量 test request：

- 补测成功：仍判定为 `Healthy`
- 补测失败：判定为 `Unhealthy`

### 熔断

熔断只根据真实请求失败触发：

- 达到 `routing.circuit_breaker_threshold` 次连续失败后进入 `Circuit Open`
- `routing.circuit_breaker_cooldown_seconds` 是基础冷却时间
- 冷却时间会随熔断次数递增
- 一次成功请求会重置熔断退避计数

## 控制台页面

- `Overview`
  - `Map / Stats`
- `Log`
  - recent requests
- `Config`
  - `Global / Upstreams / Raw JSON`
- `Healthcheck`
  - manual health check / test request / action result

## 日志与统计

统计日志默认写到用户目录：

```text
~/.router-proxy/logs/YYYY/MM/DD/request_stats.jsonl
```

记录包含：

- upstream 名称
- 事件类型
- 状态码
- 耗时
- model
- 成功/失败
- token usage

日志按日期分层存放：

- 每天一个 `request_stats.jsonl`
- 路径结构为 `年/月/日`

抓包默认写到用户目录：

```text
~/.router-proxy/captures/YYYY/MM/DD/
```

## 目录

- `router_proxy/`
  - 路由代理核心实现
- `config_ui/`
  - 管理控制台
- `logs/`
  - 统计和服务日志
- `captures/`
  - 请求/响应抓包

## 开发者文档

- `DEVELOPER.md`
