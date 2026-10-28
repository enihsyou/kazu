# kazu status

一次性并行查询所有已启用来源的当前用量，输出终端表格或 JSON：

```bash
uv run kazu status
uv run kazu status --config ./config.toml
uv run kazu status --json
```

输出每个来源的启用状态、实际采用的数据来源、配置的查询间隔、抓取耗时、查询状态和当前指标。
状态包括 `disabled`、`ok`、`partial`、`error`。尚未成功选中来源时，Source 显示配置值。

命令独立执行，不要求 Metrics 服务已经运行，也不读取或唤醒该服务的 Watch。
不显示其他进程的 Watch 状态。禁用来源不执行查询。
部分来源失败时仍显示其他来源的数据，`partial` 或 `error` 使退出码为 1，其余为 0。
凭据从配置目录的 `.env` 和进程环境变量读取，输出不包含凭据或原始 CLI 响应。

抓取耗时覆盖该来源本次完整查询，失败时也显示耗时；禁用来源显示 `—`，JSON 中为
`duration_seconds: null`。成功为绿色、部分成功为黄色、失败为红色、禁用为灰色。
金额、credits、次数分别使用颜色和名称区分，重定向输出时 Rich 自动关闭终端颜色。
