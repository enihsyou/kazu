# LLM 配额

首轮支持 MiniMax China Token Plan，直接查询官方 CLI 使用的
`GET https://api.minimax.cn/v1/token_plan/remains`。不需要安装或登录 `mmx`。
Codex 订阅、DeepSeek 余额暂未接入。

## 配置

在实际 `config.toml` 中启用：

```toml
[sources.minimax]
enabled = true
source = "api"
region = "china"
```

同目录 `.env`：

```dotenv
MINIMAX_API_KEY=<中国区 Token Plan 密钥>
```

`source="auto"` 同样直接使用 API；不支持 `cli`、`cli-auth`。
`region` 默认且目前仅支持 `china`；global 尚未接入。
进程环境变量优先于 `.env`。不要将密钥写入 TOML。
Token Plan 密钥通常以 `sk-cp-` 开头，`sk-api-` 按量付费密钥不适用于此配额接口。
本轮不查询 MiniMax 按量付费余额。请求错误只显示状态码或固定说明，不输出响应正文。

```bash
uv run kazu status
uv run kazu status --json
uv run kazu metrics
```

## 已导出的指标

以下均为 Gauge，标签统一为 `provider="minimax"`、`model` 和 `interval`。
`interval` 使用可整除的最大单位，例如 `4h`、`5h`、`1d`、`1w`；
不能整除周、天、小时则保留秒，例如 `18001s`。
短周期可能为 4 小时、5 小时或 24 小时，以接口起止时间为准。

| 指标 | 单位 | 含义 |
| --- | --- | --- |
| `kazu_llm_quota_remaining_ratio` | 比例 | 1 表示 100% 剩余；周 boost 后可能超过 1 |
| `kazu_llm_quota_reset_timestamp_seconds` | Unix 秒 | 接口窗口结束时间 |

Status 将剩余比例显示为百分比，重置时间显示为本地时区时间；JSON 保持原始测量值。
不同模型可能共享配额，不能把它们的剩余比例相加。

有 `current_*_remaining_percent` 时直接使用该权威百分比。
旧响应没有百分比时，沿用官方 CLI 的解释：`usage_count` 为剩余 count，
除以同窗口 `total_count` 得出比例。原始 count 未证明具有统一 token 或请求单位，
因此不导出绝对 token、请求数或 credits。
周比例按接口 `weekly_boost_permille / 1000` 调整，不将展示上限用作数据上限。

没有报告的周配额、零分母、无限或未包含在套餐内的模型窗口不补零；
`status=3` 的窗口不输出有限配额指标。有限配额必须有起止时间，才能确定窗口标签。
没有任何可用配额时状态为 `partial`，不会误报为配额耗尽。

## 后续来源的计量边界

- 周期额度：5 小时、周、日或月属于同一类；用窗口区分。剩余比例、
  同单位的 cap/used/remaining、重置时间都是 Gauge。只在接口明确提供计量单位后
  才增加 token 或请求次数指标，不能把 Codex 额度换算成固定 token 数。
- 金额余额：另用 LLM money measurement，保留 `currency` 和账户范围。
  DeepSeek 的余额不是 token 配额，也不应放进 `kazu_search_*` 指标。
- 速率上限：QPS/RPM 是请求速率，TPM 是 token 速率，按单位分别建 measurement；
  每分钟速率换算为每秒速率后才能与 QPS 比较。配置上限不代表实时剩余容量。
- 并发上限：同时执行的请求数，与时间窗口消费额度分开。
- 上下文长度：模型单请求能力，属于模型容量，不能当作账户剩余额度。

本轮只实现接口真实返回的周期配额，不为未来来源提前添加空指标。

## 调研依据

- [MiniMax CLI quota count 语义](https://github.com/MiniMax-AI/cli/blob/38aba5f26173dd1065b115b221d79c9ddd87c6bb/src/utils/quota.ts)
- [MiniMax CLI quota 展示及 boost](https://github.com/MiniMax-AI/cli/blob/38aba5f26173dd1065b115b221d79c9ddd87c6bb/src/output/quota-table.ts)
- [MiniMax CLI 官方响应 fixture](https://github.com/MiniMax-AI/cli/blob/38aba5f26173dd1065b115b221d79c9ddd87c6bb/test/fixtures/quota-response.json)
- [Codex 订阅额度](https://help.openai.com/en/articles/11369540-using-codex-with-your-chatgpt-plan)
- [DeepSeek 余额 API](https://api-docs.deepseek.com/zh-cn/api/get-user-balance/)
- [DeepSeek 限流说明](https://api-docs.deepseek.com/quick_start/rate_limit/)
