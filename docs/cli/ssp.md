# `kazu ssp`

读取少数派的流量使用情况。

## 用法

```bash
uv run kazu ssp --help
uv run kazu ssp --docs
uv run kazu ssp get
uv run kazu ssp get --detail
uv run kazu ssp get --authorization "Bearer <credential>"
uv run kazu ssp metrics
uv run kazu ssp metrics --host 0.0.0.0 --port 9101
uv run kazu ssp metrics --push-influxdb
```

`--docs` 从安装包内的 Markdown 资源读取文档；源码/可编辑安装未包含资源时使用仓库文档。
Docker 中可直接运行 `docker run --rm kazu:latest ssp --docs`，无需挂载源码。

容器运行指标服务时，需要配置 SSP Authorization，并显式提供子命令和监听地址：

```bash
docker run --rm -p 127.0.0.1:9101:9101 \
  -v kazu-config:/root/.config/kazu \
  kazu:latest ssp metrics --host 0.0.0.0 --port 9101
```

## `get` 子命令

`kazu ssp get` 与 `metrics` 共用 `SSPSource.collect()` 获取并规范化流量数据，
终端表格展示同一份快照中的业务日期、流量和倍率。

请求选项：

- `--authorization`：完整的 `Bearer <credential>` 文本，覆盖配置文件。
- `--timeout`：请求超时秒数。
- `--verbose`：显示已脱敏的 HTTP 请求与响应。
- `--detail`：按完整字节数显示流量，例如 `123,456,789 B`；默认使用较短的可读单位。

## `metrics` 子命令

`kazu ssp metrics` 启动常驻 HTTP 服务，默认地址为
`http://127.0.0.1:9101/metrics`，按 Ctrl+C 停止。每次 `GET /metrics` 才请求 SSP，
由 `prometheus-client` 的 `Gauge` 构造指标并生成 Prometheus exposition 响应。

推荐让 Grafana Alloy 的 `prometheus.scrape` 直接拉取 `/metrics`，不使用 textfile
collector、Pushgateway 或定时重复启动命令。详见[采集配置示例](../metrics.md#推荐使用-grafana-alloy-采集)。

默认不连接 InfluxDB。增加 `--push-influxdb` 后，启动时检查配置和数据库查询权限；
通过后，每次成功采集的数据都会尝试写入 InfluxDB 3：当日按采集时刻追加，历史业务日
固定写到该日最后一秒。没有 scrape 就不会产生采集或上报。

选项：

- `--host`：监听地址，默认 `127.0.0.1`。容器内或远程 Alloy 采集时可使用 `0.0.0.0`。
- `--port`：监听端口，默认 `9101`，范围为 `1`–`65535`。
- `--push-influxdb`：通过启动检查后启用 InfluxDB 3 上报；未指定时不连接 InfluxDB。
- `--authorization`：完整的 `Bearer <credential>` 文本，覆盖配置文件。
- `--timeout`：请求超时秒数。
- `--verbose`：显示已脱敏的 HTTP 请求与响应。

当前三个流量 Gauge 名称为：

```text
kazu_subscription_traffic_upload_bytes
kazu_subscription_traffic_download_bytes
kazu_subscription_traffic_deducted_bytes
```

三个值都是当前业务日截至本次查询时刻的累计总量（today total），在日内随使用量递增，
进入下一业务日后重置。它们不是每个采集间隔内的增量，也不是 Counter。查询当前累计量
应取窗口内最后一个有效样本，不能把时间轴上的样本相加；每日累计量取该业务日最后一个
有效样本，每小时消耗量则由该小时首尾累计值之差计算，并处理跨日重置。忽略
`user_id` 与 `server_rate` 时，先用 `sum` 合并每个时刻的标签序列，再对聚合后的序列
使用 `last_over_time` 取最后一个有效样本；`sum` 不用于累加时间轴上的采集样本。
PromQL 应使用 `last_over_time((sum(metric{...}))[窗口:10s])` 形式的子查询。展示合计、
总消耗或实际扣除流量时直接查询 `kazu_subscription_traffic_deducted_bytes`，不要用上传与
下载相加代替，因为扣除流量已经应用了 `server_rate`。

另外输出无 label 的抓取耗时 Gauge：

```text
kazu_subscription_traffic_scrape_duration_seconds
```

其值为本次从 SSP 抓取并规范化流量所用的秒数，不包含 InfluxDB 上报耗时，
与流量指标在同一次 Prometheus 响应中输出，不写入 InfluxDB。

三个流量指标都有 `provider="ssp"`、`user_id` 和 `server_rate` 三个 label；抓取耗时指标不带 label。`date`、
`record_at` 和查询时间都不是 label。上游请求失败、当前日数据缺失或采集请求重叠时，
`/metrics` 返回 HTTP 503，不返回旧数据或人为补零；下一次 scrape 会重新尝试。
其他路径返回 HTTP 404。启动和上报状态通过 stderr 中的 INFO/WARNING/ERROR 日志显示。

监听地址没有内置认证或 TLS；不要直接暴露到公网。

## Authorization

Authorization 必须是完整的 `Bearer <credential>` 文本。

令牌来源是登录后的 Local Storage `VUE_NAIVE_ACCESS_TOKEN` 键。

登录少数派后，在该站点页面的浏览器开发者工具 Console 中运行下面的 JavaScript；它会将正确格式的值复制到剪贴板：

```js
const token = localStorage.getItem("VUE_NAIVE_ACCESS_TOKEN");
if (!token) throw new Error("VUE_NAIVE_ACCESS_TOKEN is not available");
copy(`Bearer ${token}`);
```

可以临时传入命令行，或保存到用户配置文件：

```toml
[sources.ssp]
authorization = "Bearer <credential>"
```

InfluxDB 3 的连接信息位于顶层 `[influxdb3]`：

```toml
[influxdb3]
host = "https://influxdb.example.com"
database = "kazu"
token = "<query-and-write-token>"****
timeout = 15.0
```

`host`、`database`、`token` 必填；目标数据库须已存在，token 需要该库的查询与写入权限。令牌应保存在本机用户配置中，不要提交到仓库。

启动行为：

- 未传 `--push-influxdb`：INFO 提示未启用上报，不访问 InfluxDB。
- 已传参数：使用配置中的 database/token 调用 `/api/v3/query_sql` 执行
  `SELECT 1 AS ready`。成功时 INFO 提示将上报。
- 配置不完整或检查失败：WARNING 提示不会上报，但 `/metrics` 服务继续运行；修复配置
  后需要重启命令。启动检查不创建数据库，也不写入探测点。
- 后续写入失败：记录 ERROR，本次指标响应不因该错误变为失败，下次采集继续尝试上报。

`/ping` 只能检查服务状态，不能证明指定数据库和写入权限有效。这里的 SQL 检查验证
数据库查询是否可用，写入权限仍由实际写入确认。

## 内置加密配置来源

`BOOTSTRAP_MASTER_KEY` 取自首页加载的 `sec.js`。脚本中的 32 位小写字母数字字符串可用
`:'\\b[a-z0-9]{32}\\b',` 的等价模式定位。

`SECURE_SETTING` 取自 `https://s1.thefew01.top/` 响应中的
`<meta name="secure-setting" content="...">`，无需登录。首页同时提供 `sec.js` 的链接。
`tests/test_ssp_bootstrap.py` 会在网络可用时请求这两个公开资源，并验证它们仍与内置常量一致。
