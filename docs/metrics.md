# Metrics 与配置

```bash
uv run kazu metrics
uv run kazu metrics --config ./config.toml
uv run kazu metrics --host 0.0.0.0 --port 9101
```

服务只提供 `GET /metrics`，默认监听 `127.0.0.1:9101`。各数据源在后台独立查询；
Prometheus Collect 读取不可变快照，不等待 CLI 或上游 HTTP 请求。

## 配置

所有字段均可省略，未填写的字段使用默认值。数据源默认禁用，需要显式启用。

```toml
[metrics]
host = "127.0.0.1"
port = 9101

[sources.tinyfish]
enabled = true
source = "auto"
interval = 120
idle_poll_limit = 5
```

`ssp`、`exa`、`tinyfish`、`tavily`、`firecrawl`、`parallel` 各有独立的配置节。
共同配置项：

| 字段 | 默认值 | 含义 |
| --- | --- | --- |
| `enabled` | `false` | 是否启用该数据源 |
| `source` | `"auto"` | `auto` 优先 CLI，然后 API；也可指定 `cli` 或 `api` |
| `interval` | `120` | 一次查询结束后，到下一次查询的间隔，单位秒 |
| `timeout` | `30` | 单个 CLI 命令或 HTTP 请求的超时秒数 |
| `idle_poll_limit` | `5` | 未被 Collect 消费的连续查询次数上限，必须为正整数 |
| `command` | `""` | CLI 可执行文件名或路径；留空使用该服务的标准命令名 |

Metrics 服务没有抓取间隔命令行参数。CLI 路径应当只包含可执行文件路径，不含参数。
CLI 必须提前安装并登录；Exporter 不安装 CLI，也不发起交互登录。

## 当前数据源

| 来源 | 接入方式 | 导出内容 |
| --- | --- | --- |
| TinyFish | CLI 或 API | 钱包余额、全部历史搜索调用数 |
| Firecrawl | CLI 或 API `/v2/team/credit-usage` | 账户剩余 credits、当前套餐 credits 限额 |
| Parallel | `parallel-cli balance --json get` | USD 预付余额、待扣金额、后付费状态 |
| SSP | 内置 API | 当前业务日上传、下载、扣费流量 |
| Exa | Team Management API | 指定 Key 最近 30 天的美元消耗 |
| Tavily | API `/usage` | Key、套餐、按量付费各自的 credits 用量和限额 |

`auto` 会先查询 CLI；CLI 不存在、未认证或查询失败时，才尝试已实现的 API 适配器。
Exa、Tavily 的 `auto` 直接使用 API；Parallel 保留 CLI OAuth，不支持普通 API Key 查询余额。
SSP 的 `auto` 使用内置 API，不支持 CLI 来源。

TinyFish 钱包和搜索用量分别查询。旧账户没有钱包时仍可输出成功取得的搜索用量，
状态为 `partial`。Firecrawl 的账户余额可能包含额外充值，不能与套餐额度直接相减
得到真实消耗。Parallel 的待扣金额不是累计消费；后付费账户只输出后付费状态，
不将 API 固定返回的零余额解释为额度耗尽。无法获得的指标不会补成零。

## 凭据

配置文件只能包含非敏感字段。API Key、Token、Authorization 字段不能写进 TOML。
在实际配置文件所在目录创建 `.env`；不会读取工作目录下其他 `.env`。
进程环境变量优先于 `.env`，`.env` 内容不会自动注入 CLI 子进程。

```dotenv
SSP_AUTHORIZATION="Bearer <credential>"
```

搜索 CLI 复用自身现有登录凭据；API 使用 `TINYFISH_API_KEY`、`TAVILY_API_KEY`、
`FIRECRAWL_API_KEY`。Exa 使用独立的 `EXA_SERVICE_KEY`，普通 Search Key 不可替代，
并需先向 Exa 开通 Team Management 权限。`.env` 已加入 Git 和 Docker 构建忽略列表。
配置在命令启动时读取，修改后需要重启命令。

例如，直接使用 Tavily 和 Exa API：

```toml
[sources.tavily]
enabled = true
source = "api"

[sources.exa]
enabled = true
api_key_id = "550e8400-e29b-41d4-a716-446655440000"
```

同目录 `.env`：

```dotenv
TAVILY_API_KEY=<credential>
EXA_SERVICE_KEY=<service-credential>
```

Tavily 的 Key 限额为 `null` 时表示无限额，只输出用量；零限额仍为有效值。
各范围的剩余量取同范围限额减用量并最低为零，不将 credits 当作调用次数。
其 `/usage` 限流为每 10 分钟 10 次，默认 120 秒间隔可用，频繁运行 Status 也会占用限流。
Exa 不从消耗反推账户余额，最近 30 天也不等同于自然月或账期。
HTTP 错误仅显示状态码，不输出响应正文，不自动重试。

## Watch 与 Collect

启动时各来源立即进行一次后台查询，然后按自己的 `interval` 继续。
每次 Collect 将未消费查询次数归零。查询尝试成功或失败都会计数；达到
`idle_poll_limit` 后，如果到下一次查询时仍没有 Collect，就暂停 Watch、清除业务
快照，并记录暂停日志。保留最后一次结果一个间隔，让阈值为 1 时仍有消费机会。

暂停后的下一次 Collect 只发送唤醒信号并记录恢复日志，该次响应不包含该来源的
业务指标。后台查询完成后，后续 Collect 才会包含新数据；并发 Collect 不会创建
重复 worker。首次后台查询尚未完成时，同样不输出该来源的业务指标。

单个来源失败不会影响其他来源，失败来源不继续输出其上次业务快照。响应保留
诊断 Gauge，供 Prometheus 区分没有数据、失败和暂停：

- `kazu_source_up{provider}`：最近一次查询完整成功为 1；失败、部分成功、初始或暂停为 0。
- `kazu_source_watching{provider}`：Collect 取快照时是否正在 Watch。
- `kazu_source_last_success_timestamp_seconds{provider}`：最近一次获得有效数据的 Unix 时间，尚无数据时为 0。
- `kazu_source_query_duration_seconds{provider}`：最近一次查询耗时。

搜索账户数据分为金额、credits、次数三类 Gauge。剩余、已用、限额等语义放在指标名中，
服务名使用 `provider` 标签，统计范围使用 `scope` 标签：

| 指标 | 单位 | 含义 |
| --- | --- | --- |
| `kazu_search_money_remaining` | 金额 | 可用余额，币种由 `currency` 标签指定 |
| `kazu_search_money_used` | 金额 | 范围内消耗，币种由 `currency` 标签指定 |
| `kazu_search_money_pending_debit` | 金额 | 待扣金额，币种由 `currency` 标签指定 |
| `kazu_search_credits_remaining` | credits | 指定范围的剩余量 |
| `kazu_search_credits_cap` | credits | 指定范围的限额 |
| `kazu_search_credits_used` | credits | 指定范围的已用量 |
| `kazu_search_calls_used` | 调用次数 | 已调用次数 |

`scope` 表示数据范围：`account` 为账户、`plan` 为套餐账期、`all_time` 为全部历史。
Tavily 还使用 `key` 和 `paygo`；Exa 的 `key_30d` 为指定 Key 最近 30 天。
待扣金额不等于累计消费；账户剩余 credits 和套餐 cap 的范围不同，不能直接相减。
例如：

```prometheus
kazu_search_money_remaining{provider="tinyfish",currency="USD",scope="account"} 21.44
kazu_search_credits_remaining{provider="firecrawl",scope="account"} 1000
kazu_search_credits_cap{provider="firecrawl",scope="plan"} 500000
kazu_search_calls_used{provider="tinyfish",scope="all_time"} 42
```

后付费标志属于诊断信息，单独使用 `kazu_source_postpaid{provider}`，不混入金额指标。

SSP 保留每日流量 Counter：`kazu_subscription_traffic_upload_bytes_total`、
`kazu_subscription_traffic_download_bytes_total`、`kazu_subscription_traffic_deducted_bytes_total`，
标签为 `provider`、`user_id`、`server_rate`。业务日期与本机时区一致。

Prometheus 配置示例：

```yaml
scrape_configs:
  - job_name: kazu
    scrape_interval: 30s
    static_configs:
      - targets: ["127.0.0.1:9101"]
```

## Docker

```bash
docker run --rm -p 9101:9101 \
  -v /path/to/kazu-config:/root/.config/kazu:ro \
  kazu:latest
```

目录内放 `config.toml` 及可选的 `.env`。基础镜像提供 Python Exporter 与 SSP 支持；
使用搜索 CLI 的自定义镜像还需要安装对应官方 CLI，并为容器内运行用户提供其登录状态。
宿主机已有 CLI 和凭据不会自动出现在容器里。

## 官方参考

- [TinyFish CLI](https://docs.tinyfish.ai/cli/commands)
- [Firecrawl credit-usage 实现](https://github.com/firecrawl/cli/blob/main/src/commands/credit-usage.ts)
- [Parallel CLI 实现](https://github.com/parallel-web/parallel-web-tools/blob/main/parallel_web_tools/cli/commands.py)
- [Tavily usage](https://docs.tavily.com/documentation/api-reference/endpoint/usage)
- [Tavily rate limits](https://docs.tavily.com/documentation/rate-limits)
- [Exa Key usage](https://exa.ai/docs/reference/team-management/get-api-key-usage)
- [Firecrawl credit usage](https://docs.firecrawl.dev/api-reference/endpoint/credit-usage)
