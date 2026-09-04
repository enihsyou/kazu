# 指标与流量历史

## SSP 代理订阅流量

`kazu ssp metrics` 按 `record_at` 在本机时区解释业务日。上游的
`record_at` 是日期锚点，不是流量事件发生时间；“今天”、跨日、跨月和跨年判断都使用
该时区。

### Prometheus HTTP 服务

```bash
uv run kazu ssp metrics --host 127.0.0.1 --port 9101
```

命令常驻运行，通过 `GET http://127.0.0.1:9101/metrics` 提供指标。`--host` 默认
`127.0.0.1`，`--port` 默认 `9101`；Ctrl+C 停止服务。每次请求实时读取 SSP，不在后台
定时轮询。指标使用 `prometheus-client` 构造，独立 registry 和 Gauge 在服务实例启动时
创建一次并持续复用。每次更新时清理流量 Gauge 的旧标签，采集、更新和响应生成均在
同一把锁内完成，避免上一次响应的 label 或数据残留。项目没有 Prometheus 连接配置或远程推送逻辑。

响应使用显式创建的 `CollectorRegistry`，不使用默认全局 `REGISTRY`，因此不输出
默认 Process、GC、Platform collectors 的 `process_*`、`python_gc_*` 或 `python_info` 指标。

旧版 stdout/`--output PATH`/`.prom` 文件方式已移除；原有定时命令和 textfile collector
需要改为常驻进程加 HTTP scrape。启动前需配置有效的 SSP Authorization。

只输出当前业务日截至本次查询时刻的累计值，三个指标均为 Gauge：

```text
kazu_proxy_upload_bytes{provider="ssp",user_id="8780",server_rate="1.00"}
kazu_proxy_download_bytes{provider="ssp",user_id="8780",server_rate="1.00"}
kazu_proxy_deducted_bytes{provider="ssp",user_id="8780",server_rate="1.00"}
```

它们分别表示实际上行、实际下行和扣除流量，单位都是 bytes。label 只有固定的
`provider="ssp"`、上游 `user_id` 与 API 返回的 `server_rate`；不添加 `date`、
`record_at` 或查询时间 label。Prometheus 的正常采集时间负责形成当天的时间序列；不
进行历史日期回填，也不构造 Counter。

此外，`kazu_proxy_scrape_duration_seconds` 是无 label 的 Gauge，记录本次从 SSP
抓取并规范化流量所用的秒数，不包含 InfluxDB 上报耗时。服务装配时直接使用该 Gauge
的 `.time()` 装饰采集函数，与流量指标通过同一 registry 输出到 Prometheus，不写入 InfluxDB。

请求失败或响应中没有当前业务日时，`/metrics` 返回 HTTP 503，Alloy 将这次 scrape
视为失败；不会返回旧值或人为补零。并发采集重叠时额外请求也返回 503，以避免重复请求
上游和同时写库。下一次请求会重新采集。其他路径返回 404。

### 推荐使用 Grafana Alloy 采集

保持 Kazu 服务运行，在 Alloy 中添加以下组件。`prometheus.remote_write.default` 指向
你已配置好的接收端；若名称不同，请替换 `forward_to` 的引用。

```alloy
prometheus.scrape "kazu_ssp" {
  targets = [
    { "__address__" = "127.0.0.1:9101" },
  ]
  metrics_path    = "/metrics"
  scrape_interval = "5m"
  scrape_timeout  = "60s"
  forward_to     = [prometheus.remote_write.default.receiver]
}
```

示例以 5 分钟作为采集间隔，避免过于频繁请求 SSP；按业务需要调整。
`scrape_timeout` 要覆盖 SSP 请求以及启用时的 InfluxDB 查询/写入耗时，不得大于
`scrape_interval`。SSP 的 `--timeout` 和 `[influxdb3].timeout` 是单次 HTTP 请求超时，
不是整个 scrape 的总时限；历史日逐条查重会累加耗时。
配置项参见 [Alloy prometheus.scrape 文档](https://grafana.com/docs/alloy/latest/reference/components/prometheus/prometheus.scrape/)。

同机采集可使用默认监听地址。跨主机或跨容器采集时，Kazu 使用 `--host 0.0.0.0`，
将 `__address__` 改为 Alloy 实际可访问的主机/容器服务名。不要把 `0.0.0.0` 当作采集
目标，也不要把 Alloy 容器内的 `127.0.0.1` 当作 Kazu 容器。服务没有内置认证/TLS，
只应开放给可信采集端；需要公网访问时使用网络限制或带认证/TLS 的反向代理。

### InfluxDB 3 记录

只有显式指定 `kazu ssp metrics --push-influxdb`，且启动检查通过后才写 InfluxDB 3。
未启用时记录 INFO 并且不连接数据库。启用时要求完整的 host/database/token 配置，
通过带数据库和 token 的 `SELECT 1 AS ready` 检查后记录 INFO，开始上报；检查失败
记录 WARNING，当前进程禁用上报但继续提供 `/metrics`。SQL 检查不写探测点，能确认
数据库查询权限，不能提前证明写入权限；token 应同时具有查询和写入权限。
具体配置参见 [SSP 命令文档](cli/ssp.md#authorization)。

上报随 scrape 发生，不独立定时运行。每次写入都会包含
当前业务日和上游返回的历史业务日：当前日使用实际采集时间作为 InfluxDB 时间戳，持续
追加快照；历史日使用其本机时区最后一秒作为时间戳（InfluxDB 时间戳按 UTC 存储）。

表（measurement）为 `subscription_traffic_daily`。业务日期由 `usage_date` 字段表达。
查询历史业务日时，优先取该日固定 `23:59:59` 时间点的记录；如果尚未补写历史记录，
则取该日最后一次采集快照。它们均为可获得的累计值，不等同于绝对结算结果。

标签（tags）：

- `provider`：固定为 `ssp`。
- `user_id`：少数派侧用户 ID。

字段（fields）：

- `upload_bytes`：原始上行 bytes。
- `download_bytes`：原始下行 bytes。
- `deducted_bytes`：按 `server_rate` 计算出的扣除 bytes。
- `server_rate`：API 返回的原始倍率文本。
- `usage_date`：本机时区下的业务日期。

扣除流量的定义为：

```text
deducted_bytes = (upload_bytes + download_bytes) × server_rate
```

原始流量值保留为整数 bytes，不做展示层单位换算。当前日的多次采集按采集时刻追加；
历史日只对其固定最终时间点查重，相同数据跳过，不同数据报冲突，避免静默改写历史
事实。前一天留下的当日采集快照不会被误判成多条历史最终记录。

写入失败记录 ERROR，不终止指标服务，也不把已经采集成功的当前日指标判为失败；
后续 scrape 会再次尝试。若上游只返回历史日、没有今天的数据，可以上报这些有效历史
记录，但本次 `/metrics` 仍返回 503。建议每个账户只运行一个开启上报的 Kazu 实例，
避免跨进程的历史查重/写入竞争。修改配置或修复启动检查问题后需要重启命令。

### 月末边界

月末当天仍是当前业务日。例如本机时间 9 月 30 日 23:00 的数据只是截至 23:00 的累计
值，仍输出到 Prometheus；指定 `--push-influxdb` 时也会按采集时刻写入 InfluxDB。因为
上游只返回当前月份数据，跨月后不能补采 9 月 30 日，因此该日最后一条记录只代表采集
任务最后一次取得的累计值，不声称是绝对最终结算值。2 月 28/29 日、大小月及跨年均
遵循同一规则；月度结算若未来需要，应另建语义。
