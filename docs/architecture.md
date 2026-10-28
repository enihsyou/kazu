# 代码组织

- `cli.py`：命令入口；`clicmds/*_cli.py` 注册 Metrics、Status、SSP 命令。
- `config.py`：合并内置默认值与 TOML，读取同目录 `.env`，环境变量优先。
- `lib/usage.py`：不可变 `Measurement`、`UsageSnapshot` 和 `UsageSource` 协议。
- `sources/search.py`：官方 CLI 调用和 JSON 映射；CLI 优先、API 次之的选择逻辑。
- `sources/registry.py`：来源装配与 SSP 快照适配。
- `sources/ssp.py`、`lib/sspgateway/`：SSP 网关访问与流量规范化。
- `lib/metrics/watch.py`：每个来源一个后台线程，负责定时查询、缓存和空闲暂停。
- `lib/metrics/exporter.py`：Prometheus Collector，只读取缓存并发送唤醒信号。
- `lib/metrics/server.py`：提供 `GET /metrics` 的 HTTP 服务。
- `lib/metrics/traffic.py`：SSP 流量快照转换为原有每日 Counter。

## 数据与并发边界

来源通过 `collect()` 返回统一快照，不依赖终端渲染或 Prometheus 注册表。
搜索用量是 Gauge，SSP 日累计流量保留 Counter 语义。
来源之间并行，同一来源只由自己的 worker 串行查询。外部命令使用参数列表执行、
关闭 stdin、设置超时，不启动交互认证，不把原始 stdout/stderr 写入日志。

Watch 的缓存、空闲计数、暂停和停止标志由同一 Condition 保护；上游 I/O 在锁外执行。
Collect 在锁内复制视图并清零计数，暂停时清除快照。唤醒前先取得无业务数据的视图，
因此即使 worker 立即完成，唤醒它的那次响应也不会意外包含该来源的新指标。

Collector 每次按快照生成指标族，没有长期存活的 Gauge 标签缓存，避免旧标签残留。
注册 Collector 时 `describe()` 不会触发真实 Collect。HTTP 端口绑定成功后才启动 worker。
停止时发出通知；执行中的 CLI/HTTP 操作由自己的超时约束，资源在 worker 退出时关闭。

Status 使用独立线程池执行一次性查询，复用同一来源装配与快照，不读写 Exporter 状态。

## 扩展 API 来源

在 `sources/search.py` 的 `API_COLLECTORS` 中加入 provider 对应的查询函数，签名为
`SourceConfig -> UsageSnapshot`。配置已从 `.env` 注入 `api_key`，禁止从 TOML 读取凭据。
`auto` 首先尝试 CLI；CLI 不可用时调用已注册的 API 适配器。显式 `cli` 或 `api` 则只用
指定来源。来源特有的非敏感配置随适配器一起增加，不提前引入空的服务层或认证框架。

## 文档打包

`docs/` 是唯一文档源。wheel 将其打包到 `kazu/_docs`；命令的 `--docs` 由
`CLIDocumentation` 展示包内文档，源码安装读取 `docs/cli/`。
