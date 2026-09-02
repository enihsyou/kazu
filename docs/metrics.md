# 指标与流量历史

## SSP 代理订阅流量

`kazu ssp metrics` 按 `record_at` 在本机时区解释业务日。上游的
`record_at` 是日期锚点，不是流量事件发生时间；“今天”、跨日、跨月和跨年判断都使用
该时区。

### Prometheus 输出

命令默认向 stdout 输出 Prometheus exposition 文本，也可以用 `--output PATH` 原子化
写入 `.prom` 文件，供 Grafana Alloy textfile collector 采集。项目不存在 Prometheus
连接配置，也没有远程推送逻辑。

只输出当前业务日截至本次查询时刻的累计值，三个指标均为 Gauge：

```text
proxy_traffic_upload_bytes{provider="ssp",user_id="8780",server_rate="1.00"}
proxy_traffic_download_bytes{provider="ssp",user_id="8780",server_rate="1.00"}
proxy_traffic_deducted_bytes{provider="ssp",user_id="8780",server_rate="1.00"}
```

它们分别表示实际上行、实际下行和扣除流量，单位都是 bytes。label 只有固定的
`provider="ssp"`、上游 `user_id` 与 API 返回的 `server_rate`；不添加 `date`、
`record_at` 或查询时间 label。Prometheus 的正常采集时间负责形成当天的时间序列；不
进行历史日期回填，也不构造 Counter。

如果请求失败或响应中没有当前业务日，命令不会用零覆盖已有的指标文件或指标状态。

### InfluxDB 3 记录

只有显式指定 `kazu ssp metrics --push-influxdb` 时才写 InfluxDB 3。每次写入都会包含
当前业务日和上游返回的历史业务日：当前日使用实际采集时间作为 InfluxDB 时间戳，持续
追加快照；历史日使用其本机时区最后一秒作为时间戳（InfluxDB 时间戳按 UTC 存储）。

表（measurement）为 `subscription_traffic_daily`。业务日期由 `usage_date` 字段表达。
查询一个业务日时，取该日最大的时间戳，即为当日最后一次可获得的累计值。

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
历史日相同数据会跳过，不同数据会报冲突，避免静默改写历史事实。

### 月末边界

月末当天仍是当前业务日。例如本机时间 9 月 30 日 23:00 的数据只是截至 23:00 的累计
值，仍输出到 Prometheus；指定 `--push-influxdb` 时也会按采集时刻写入 InfluxDB。因为
上游只返回当前月份数据，跨月后不能补采 9 月 30 日，因此该日最后一条记录只代表采集
任务最后一次取得的累计值，不声称是绝对最终结算值。2 月 28/29 日、大小月及跨年均
遵循同一规则；月度结算若未来需要，应另建语义。
