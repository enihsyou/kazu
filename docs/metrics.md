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
定时轮询。指标使用 `prometheus-client` 构造，独立 registry 和流量 collector 在服务实例启动时
创建一次并持续复用。每次更新时替换流量快照及其标签，采集、更新和响应生成均在
同一把锁内完成，避免上一次响应的 label 或数据残留。项目没有 Prometheus 连接配置或远程推送逻辑。

响应使用显式创建的 `CollectorRegistry`，不使用默认全局 `REGISTRY`，因此不输出
默认 Process、GC、Platform collectors 的 `process_*`、`python_gc_*` 或 `python_info` 指标。

启动前需配置有效的 SSP Authorization，并由常驻进程通过 HTTP 提供 scrape。

流量指标使用三个 Counter，表示当前业务日截至本次查询时刻的累计总量（today total）：

```text
kazu_subscription_traffic_upload_bytes_total{provider="ssp",user_id="8780",server_rate="1.00"}
kazu_subscription_traffic_download_bytes_total{provider="ssp",user_id="8780",server_rate="1.00"}
kazu_subscription_traffic_deducted_bytes_total{provider="ssp",user_id="8780",server_rate="1.00"}
```

它们分别表示实际上行、实际下行和扣除流量，单位都是 bytes。数值在同一业务日内随
使用量递增，并在进入下一业务日后重置为新一天的累计值；它们是上游提供的当日总量，
不是把每次采集值再次累加。label 只有固定的
`provider="ssp"`、上游 `user_id` 与 API 返回的 `server_rate`；不添加 `date`、
`record_at` 或查询时间 label。Prometheus 的正常采集时间负责形成当天的时间序列；不
进行历史日期回填。

Counter 直接暴露上游当日累计值，不在进程内累加，跨日随上游重置。其语义假设是
同一标签序列在业务日内只增不减；如果上游向下修正，Prometheus 会把下降视为重置，
可能高估消耗量，可通过 `resets` 观察。使用 `rate` 或 `increase` 时先对各序列计算，
再聚合标签，例如：

```promql
sum(rate(kazu_subscription_traffic_deducted_bytes_total{provider=~"$provider"}[$__rate_interval]))
sum(increase(kazu_subscription_traffic_deducted_bytes_total{provider=~"$provider"}[1h]))
sum(resets(kazu_subscription_traffic_deducted_bytes_total{provider=~"$provider"}[$__range]))
```

`rate` 的单位为 bytes/s，`increase` 使用窗口边界外推，因此结果可能是小数。
扣除流量仍直接使用 deducted 指标，不用上传与下载相加替代。

查询当前累计量时，应取所需标签序列在查询窗口内的最后一个有效样本，不能对时间轴上
的样本求和。查询每日累计量时，应取该业务日最后一个有效样本；查询小时消耗量时，应
计算该小时末与小时初累计量之差，并处理跨日重置，避免把重置后的负差值当作流量。
当看板需要忽略 `user_id` 与 `server_rate` 标签时，应先用 `sum` 合并标签，再用
`last_over_time` 取得聚合后序列的最后一个有效样本。由于范围函数需要范围向量，
PromQL 使用子查询语法，例如：

```promql
last_over_time((sum(kazu_subscription_traffic_deducted_bytes_total{provider=~"$provider"}))[2m:10s])
```

这里的 `sum` 只合并每个时刻的标签序列，不沿时间轴累加采集样本。看板中的“合计”、
“总消耗”和“实际扣除流量”必须直接使用 `kazu_subscription_traffic_deducted_bytes_total`；
不能用上传与下载相加代替，因为扣除流量已经应用了 `server_rate`。

此外，`kazu_subscription_traffic_scrape_duration_seconds` 是无 label 的 Gauge，记录本次从 SSP
抓取并规范化流量所用的秒数，不包含 InfluxDB 上报耗时。服务装配时直接使用该 Gauge
的 `.time()` 装饰采集函数，与流量指标通过同一 registry 输出到 Prometheus，不写入 InfluxDB。

请求失败或响应中没有当前业务日时，`/metrics` 返回 HTTP 503，Alloy 将这次 scrape
视为失败；不会返回旧值或人为补零。并发采集重叠时额外请求也返回 503，以避免重复请求
上游。下一次请求会重新采集。其他路径返回 404。

### 推荐使用 Grafana Alloy 采集

保持 Kazu 服务运行，在 Alloy 中添加以下组件。`prometheus.remote_write.default` 指向
你已配置好的接收端；若名称不同，请替换 `forward_to` 的引用。

```alloy
prometheus.scrape "kazu_ssp" {
  targets = [
    { "__address__" = "127.0.0.1:9101" },
  ]
  metrics_path    = "/metrics"
  scrape_interval = "10s"
  scrape_timeout  = "10s"
  forward_to     = [prometheus.remote_write.default.receiver]
}
```

当前部署以 10 秒作为采集间隔；按业务需要调整时，应同时评估 SSP 请求频率与响应时间。
`scrape_timeout` 只需覆盖 SSP 请求和指标生成，不得大于 `scrape_interval`。InfluxDB
写入由后台线程处理，不计入 scrape；`[influxdb3].timeout` 只限制后台单次 HTTP 请求。
配置项参见 [Alloy prometheus.scrape 文档](https://grafana.com/docs/alloy/latest/reference/components/prometheus/prometheus.scrape/)。

同机采集可使用默认监听地址。跨主机或跨容器采集时，Kazu 使用 `--host 0.0.0.0`，
将 `__address__` 改为 Alloy 实际可访问的主机/容器服务名。不要把 `0.0.0.0` 当作采集
目标，也不要把 Alloy 容器内的 `127.0.0.1` 当作 Kazu 容器。服务没有内置认证/TLS，
只应开放给可信采集端；需要公网访问时使用网络限制或带认证/TLS 的反向代理。

### InfluxDB 3 记录

只有显式指定 `kazu ssp metrics --push-influxdb`，且启动检查通过后才写 InfluxDB 3。
未启用时记录 INFO 并且不连接数据库。启用时要求完整的 host/database/token 配置，
启动时通过 `information_schema.tables` 查询检查目标 measurement 是否存在，成功后记录
INFO 并启动后台上报；检查失败记录 WARNING，当前进程禁用上报但继续提供 `/metrics`。
该检查不写探测点，能确认数据库查询权限，不能提前证明写入权限；token 应同时具有查询
和写入权限。表是否存在只在启动时查询一次，不在每次上报前重复查询。
具体配置参见 [SSP 命令文档](cli/ssp.md#authorization)。

上报随 scrape 入队，不独立定时采集。`/metrics` 只做非阻塞入队，不等待 InfluxDB
查询、写入或超时。后台队列保留一个待处理快照；数据库较慢且新快照到达时，用新快照
替换尚未开始处理的旧快照。每次实际写入包含当前业务日和上游返回的历史业务日：当前日
使用实际采集时间作为 InfluxDB 时间戳，持续追加快照；历史日使用其本机时区最后一秒作为
时间戳（InfluxDB 时间戳按 UTC 存储）。

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
历史日最终值保存在当前进程内存中：成功写入后，相同值跳过，不同值报冲突，避免当前
进程静默改写历史事实。写入失败不会更新内存记录，后续快照仍可重试；进程重启后内存
记录会清空，因此数据库不会用于跨进程查重。

写入失败记录 ERROR，不终止指标服务，也不把已经采集成功的当前日指标判为失败；失败的
历史最终值不会被记为已写入，后续包含该值的快照可再次尝试。若上游只返回历史日、没有
今天的数据，可以将这些有效历史记录入队，但本次 `/metrics` 仍返回 503。建议每个账户
只运行一个开启上报的 Kazu 实例，避免跨进程重复写入。修改配置或修复启动检查问题后
需要重启命令。

### 月末边界

月末当天仍是当前业务日。例如本机时间 9 月 30 日 23:00 的数据只是截至 23:00 的累计
值，仍输出到 Prometheus；指定 `--push-influxdb` 时也会按采集时刻写入 InfluxDB。因为
上游只返回当前月份数据，跨月后不能补采 9 月 30 日，因此该日最后一条记录只代表采集
任务最后一次取得的累计值，不声称是绝对最终结算值。2 月 28/29 日、大小月及跨年均
遵循同一规则；月度结算若未来需要，应另建语义。
