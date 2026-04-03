# RouteHub Developer Guide

本文档面向维护这个项目的开发者，描述当前模块结构、配置路径策略、状态机和主要数据流。

## 项目目标

这是一个本地 OpenAI-compatible 路由代理系统，目标是：

- 通过统一本地入口代理多个上游
- 做路由、失败切换、健康检查和熔断
- 提供请求统计与 token 统计
- 提供本地控制台做配置、测试和可视化

## 启动入口

统一启动入口：

- `launch-service.ps1`
- `launch-service.sh`

它们最终启动：

- 路由运行时：`router_proxy.service`
- 管理控制台：`config_ui.server`

默认端口：

- 代理：`127.0.0.1:8330`
- UI：`127.0.0.1:8340`

## 配置路径策略

当前默认配置路径优先级：

1. 命令行 `--config`
2. 环境变量 `ROUTER_PROXY_CONFIG`
3. 用户目录默认配置

实现位置：

- `router_proxy/config.py`

相关常量 / 方法：

- `PROJECT_CONFIG_PATH`
- `PROJECT_CONFIG_EXAMPLE_PATH`
- `user_config_path()`
- `resolve_default_config_path()`
- `DEFAULT_CONFIG_PATH`
- `default_config_dict()`
- `ensure_config_file()`

建议：

- 仓库内保留 `router_config.example.json`
- 真实配置默认放用户目录
- 第一次启动时自动生成最小默认配置

## 模块结构

### 路由代理

- `router_proxy/models.py`
  - 配置 dataclass
- `router_proxy/config.py`
  - 配置解析与默认路径
- `router_proxy/upstream.py`
  - 请求解析
  - 上游筛选
  - 上游排序
  - 模型映射
  - test request / fallback request
- `router_proxy/health.py`
  - 上游状态机
  - health check
  - fallback probe
  - 熔断退避
- `router_proxy/server.py`
  - HTTP 入口
  - 代理主循环
  - runtime 编排
- `router_proxy/stats.py`
  - 持久化统计日志
  - usage/token 提取
- `router_proxy/capture.py`
  - 请求/响应抓包

### 管理控制台

- `config_ui/server.py`
  - 静态资源
  - `/api/config`
  - `/api/status`
  - `/api/stats`
  - reload / validate / healthcheck / test-request / reset
- `config_ui/static/index.html`
  - UI 结构
- `config_ui/static/app.js`
  - 页面状态
  - 配置渲染与收集
  - Route Map / Log / Config / Healthcheck
- `config_ui/static/styles.css`
  - 仪表盘样式

## 当前配置模型

### `RoutingConfig`

关键字段：

- `mode`
- `connect_timeout_seconds`
- `read_timeout_seconds`
- `failover_statuses`
- `circuit_breaker_threshold`
- `circuit_breaker_cooldown_seconds`
- `circuit_breaker_max_cooldown_multiplier`

### `HealthConfig`

关键字段：

- `enabled`
- `interval_seconds`
- `timeout_seconds`
- `healthy_statuses`
- `fallback_to_test_request`
- `fallback_test_model`
- `fallback_test_prompt`

## 当前状态机

核心在：

- `router_proxy/health.py`

### 主要状态

每个 upstream 当前可能处于：

- `disabled`
- `healthy`
- `unhealthy`
- `circuit_open`

### 当前状态字段

`UpstreamState` 维护：

- `healthy`
- `circuit_open_until`
- `consecutive_failures`
- `circuit_trip_count`
- `health_source`
- `last_failure_source`
- `last_health_status`
- `last_error`
- `last_checked_at`
- `last_latency_ms`
- `success_count`
- `failure_count`
- `runtime_score`

### 状态转换规则

#### 1. health check 成功

- 标记为 `healthy`
- `health_source = "healthcheck"`

#### 2. health check 失败

如果 `health.fallback_to_test_request = true`：

- 自动补发一发 fallback test
- 成功：
  - 仍标记 `healthy`
  - `health_source = "fallback_test"`
- 失败：
  - 标记 `unhealthy`
  - `last_failure_source = "fallback_test"`

如果未开启 fallback：

- 直接标记 `unhealthy`
- `last_failure_source = "healthcheck"`

#### 3. 真实代理请求成功

- `consecutive_failures = 0`
- `circuit_open_until = 0`
- `circuit_trip_count = 0`
- 标记 `healthy`

#### 4. 真实代理请求失败

- `consecutive_failures += 1`
- 达到阈值后打开熔断
- cooldown = `base_cooldown * 2^(trip_count-1)`
- 上限由 `circuit_breaker_max_cooldown_multiplier` 限制

#### 5. manual test 成功

- 标记 `healthy`
- `health_source = "manual_test"`
- 同样清除熔断退避计数

#### 6. manual test 失败

- 记一次 failure
- `last_failure_source = "test_request"`

#### 7. reset upstream

- 清空：
  - `consecutive_failures`
  - `circuit_open_until`
  - `runtime_score`
  - success/failure count
  - `last_error`
  - `circuit_trip_count`
- 恢复 `healthy = true`
- `health_source = "manual_reset"`

## 路由准入规则

在 `router_proxy/upstream.py` 中：

- `enabled = true`
- 模型匹配
- `health_manager.is_routable(name) = true`

`is_routable()` 的含义：

- `healthy == true`
- 不在 `circuit_open_until` 冷却中

也就是说：

- `unhealthy` upstream 不参与自动路由
- `circuit_open` upstream 不参与自动路由

## 当前路由流程

入口：

- `router_proxy/server.py`

主流程：

1. 读取客户端请求
2. `parse_request()`
3. `filter_available_upstreams()`
4. `sort_upstreams()`
5. 逐个尝试代理
6. 成功则流式回传
7. 失败则按：
   - 网络异常
   - retryable exception
   - `failover_statuses`
   切到下一个上游

## 当前统计

统计日志：

- 默认在用户目录的 `logs/YYYY/MM/DD/request_stats.jsonl`

关键事件：

- `proxy_request`
- `test_request`
- `health_fallback_test`

实现：

- `router_proxy/stats.py`

当前 `StatsLogger` 支持两种模式：

- 传入 `.jsonl` 文件路径
  - 兼容单文件模式
- 传入目录路径
  - 自动按 `YYYY/MM/DD/request_stats.jsonl` 分层写入

当前默认使用目录模式。

## 当前前端信息架构

一级导航：

- `Overview`
- `Log`
- `Config`
- `Healthcheck`

### Overview

- `Map / Stats` 二级切换
- `Map`
  - Route Map
- `Stats`
  - summary by upstream 表格

### Log

- recent requests 表格

### Config

二级子页签：

- `Global`
- `Upstreams`
- `Raw JSON`

### Healthcheck

- manual health check
- test request
- action result

## 当前前端实现细节

### Route Map

Route Map 当前显示：

- `Healthy`
- `Unhealthy`
- `Circuit Open`
- `Disabled`

hover 详情会显示：

- `Verified By`
- `Failure Source`
- `Circuit Trips`
- `Cooldown`
- `Models`
- `Model Map`

### Config > Upstreams

- 已有 upstream 默认折叠
- 新增 upstream 默认展开
- 当前折叠状态使用前端运行期 `_ui_id` 管理
- `_ui_id` 已不再写回配置文件

## 当前已知问题 / 技术债

### 1. 配置文件示例与真实配置的职责要继续分离

当前路径策略已经改成用户目录优先并自动生成默认配置。

仍建议：

- 仓库中长期只保留 `router_config.example.json`
- 不要把真实密钥配置提交到仓库

### 2. 工具栏映射仍需继续收口

页面工具栏已经按一级页面分配，但仍建议继续核查：

- `Overview`
- `Log`
- `Config`
- `Healthcheck`

确保按钮只出现在对应页面。

### 3. capture 目录也已改为日期分层

当前抓包输出默认在用户目录下：

- `captures/YYYY/MM/DD/`

实现位于：

- `router_proxy/capture.py`

### 4. `mappingTemplate` 编码残留

当前 `mapping-arrow` 仍有编码残留问题，建议继续清理成标准箭头字符。

## 建议的后续维护方向

### 优先级高

- 清理前端工具栏与隐藏逻辑的一致性
- 继续补状态机相关测试
- 明确仓库发布时的配置文件策略

### 优先级中

- 补更明确的前端状态说明
- 继续优化 `Config > Upstreams` 交互
- 支持“一次只展开一个 upstream”

### 优先级低

- 给 stats / log 增加更强筛选
- 提供更清晰的健康历史时间线

## EXE 打包

当前项目已经补了适合 PyInstaller 的基础设施：

- `service_entry.py`
  - 作为 exe 入口
- `config_ui/server.py`
  - 已兼容 frozen 环境下的静态资源路径
- `build-exe.ps1`
  - Windows 打包脚本
- `config_ui/static/icons/app-icon.svg`
  - 前端 favicon / README 图标

### 构建命令

```powershell
powershell -ExecutionPolicy Bypass -File .\build-exe.ps1
```

可选：

```powershell
powershell -ExecutionPolicy Bypass -File .\build-exe.ps1 -OneDir
```

如果存在：

- `config_ui/static/icons/app-icon.ico`

打包脚本会自动把它作为 Windows exe 图标传给 PyInstaller。

### 当前已知构建阻塞

当前环境如果直接跑 PyInstaller，存在一个外部环境问题：

- Anaconda 环境里安装了第三方 `pathlib` 回溯包
- 这个包和 PyInstaller 不兼容

解决方式通常是：

- 用干净的 Python 虚拟环境构建
- 或从当前环境移除第三方 `pathlib`

## 维护建议

修改时优先遵守：

- 保持目录分层，不回退成单文件脚本
- PowerShell 不使用容易和内置变量冲突的名字
- 配置文件读取继续兼容 `utf-8-sig`
- 前端继续按“控制台”而不是“纯配置页”思路维护
