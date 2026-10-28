# SSP 命令

SSP 通过加密网关读取订阅流量，保留终端查询及实时刷新能力：

```bash
uv run kazu ssp get
uv run kazu ssp get --detail
uv run kazu ssp get --watch 5
uv run kazu ssp --config ./config.toml get
```

`get` 可用参数：

- `--detail`：完整显示字节数。
- `--watch INTERVAL`：按秒刷新终端表格，与 Exporter 的后台抓取配置独立。
- `--authorization`：覆盖 `SSP_AUTHORIZATION`。
- `--timeout`：覆盖配置中的请求超时。
- `--verbose`：显示脱敏后的 HTTP 请求与响应。

将完整认证值放进配置文件同目录的 `.env`，或进程环境变量：

```dotenv
SSP_AUTHORIZATION="Bearer <credential>"
```

可省略的公共配置：

```toml
[sources.ssp]
enabled = true
source = "auto"
interval = 120
idle_poll_limit = 5
timeout = 30
api_base_url = "https://s1.thefew01.top/api/v1"
gateway_base_url = "https://x1.thecores.top"
```

`enabled` 控制统一 Metrics 与 Status 是否查询 SSP；显式执行 `ssp get` 总会查询。
通过 `uv run kazu metrics` 将 SSP 与其他来源一起暴露给 Prometheus。
SSP 的 `auto` 和 `api` 都使用内置 API；`cli` 不适用。
流量按本机时区解释业务日，上传、下载和按倍率折算的扣费流量共用同一份规范化快照。
