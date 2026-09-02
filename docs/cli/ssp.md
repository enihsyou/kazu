# `kazu ssp`

读取少数派的流量使用情况。

## 用法

```bash
uv run kazu ssp --help
uv run kazu ssp --docs
uv run kazu ssp get
uv run kazu ssp get --authorization "Bearer <credential>"
uv run kazu ssp metrics
uv run kazu ssp metrics --output C:\\var\\lib\\node_exporter\\textfile\\ssp.prom
uv run kazu ssp metrics --push-influxdb
```

## `get` 子命令

`kazu ssp get` 获取流量数据并以终端表格展示。

请求选项：

- `--authorization`：完整的 `Bearer <credential>` 文本，覆盖配置文件。
- `--timeout`：请求超时秒数。
- `--verbose`：显示已脱敏的 HTTP 请求与响应。

## `metrics` 子命令

`kazu ssp metrics` 获取当前接口返回的近期每日数据，并输出 Prometheus
exposition 格式。默认输出到标准输出，适合由 Grafana Alloy 的 textfile collector
读取；`--output PATH` 会将内容原子化写入指定文件，并更新文件的修改时间。命令本身不
向 Prometheus 发起推送，也不需要 Prometheus 连接配置。

默认只生成指标输出。增加 `--push-influxdb` 后，会把全部业务日数据写入 InfluxDB 3：
当日数据按采集时刻追加，历史业务日固定写到该日最后一秒。

选项：

- `--output PATH`：将 exposition 文本原子化写入文件，而不是输出到 stdout。
- `--push-influxdb`：启用历史业务日的 InfluxDB 3 写入；未指定时不连接 InfluxDB。
- `--authorization`：完整的 `Bearer <credential>` 文本，覆盖配置文件。
- `--timeout`：请求超时秒数。
- `--verbose`：显示已脱敏的 HTTP 请求与响应。

当前日的三个 Gauge 名称为：

```text
proxy_traffic_upload_bytes
proxy_traffic_download_bytes
proxy_traffic_deducted_bytes
```

每个指标都有 `provider="ssp"`、`user_id` 和 `server_rate` 三个 label。`date`、
`record_at` 和查询时间都不是 label。请求失败或当前日数据缺失时，不会把已有指标人为
重置为零。

## Authorization

Authorization 必须是完整的 `Bearer <credential>` 文本。

登录少数派后，在该站点页面的浏览器开发者工具 Console 中运行下面的 JavaScript；它会将正确格式的值复制到剪贴板：

```js
const token = localStorage.getItem("VUE_NAIVE_ACCESS_TOKEN");
if (!token) throw new Error("VUE_NAIVE_ACCESS_TOKEN is not available");
copy(`Bearer ${token}`);
```

令牌来源是登录后的 Local Storage `VUE_NAIVE_ACCESS_TOKEN` 键。

可以临时传入命令行，或保存到用户配置文件：

```toml
[sources.ssp]
authorization = "Bearer <credential>"
```

InfluxDB 3 的连接信息位于顶层 `[influxdb3]`：

```toml
[influxdb3]
host = "https://influx.example.com"
database = "kazu"
token = "<write-token>"
org = "<optional-org>"
timeout = 15.0
```

这些字段只在使用 `metrics --push-influxdb` 时生效。令牌应保存在本机用户配置中，
不要提交到仓库。

## 内置加密配置来源

`BOOTSTRAP_MASTER_KEY` 取自首页加载的 `sec.js`。脚本中的 32 位小写字母数字字符串可用
`:'\\b[a-z0-9]{32}\\b',` 的等价模式定位。

`SECURE_SETTING` 取自 `https://s1.thefew01.top/` 响应中的
`<meta name="secure-setting" content="...">`，无需登录。首页同时提供 `sec.js` 的链接。
`tests/test_ssp_bootstrap.py` 会在网络可用时请求这两个公开资源，并验证它们仍与内置常量一致。
