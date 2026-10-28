# kazu metrics

启动所有已启用来源的 Prometheus Exporter：

```bash
uv run kazu metrics
uv run kazu metrics --config ./config.toml --host 0.0.0.0 --port 9101
```

`--config` 指定 TOML 文件；`--host`、`--port` 覆盖 `[metrics]` 中的监听地址和端口。
抓取间隔、数据来源、空闲暂停阈值均在各来源的 TOML 配置节设置。

查询在后台执行，`GET /metrics` 不等待上游。暂停后的首次 Collect 异步恢复 Watch，
本次响应没有该来源的业务指标。启动、暂停、恢复和停止均有日志。

完整配置与指标说明见 `docs/metrics.md`。
