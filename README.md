# Kazu (数)

A Prometheus exporter for account balances, usage and quotas, managed with uv.
Python 3.11+ is required.

```bash
uv sync
uv run kazu metrics
uv run kazu status
uv run kazu status --json
```

Enable the sources you want in `config.toml`. All fields have defaults; sources
are disabled by default. This configuration uses CLI login for TinyFish and
Firecrawl, and device OAuth for Parallel:

```toml
[sources.tinyfish]
enabled = true

[sources.firecrawl]
enabled = true

[sources.parallel]
enabled = true
source = "oauth"
```

TinyFish and Firecrawl support their official CLIs and API keys. Tavily uses its
usage API. Exa is unsupported because usage queries require a special Team Service
API key and separately enabled Team Management access. Parallel's balance API
does not accept standard API keys; it supports its CLI or device OAuth.
`source="auto"` selects a configured API first, then an available CLI; Parallel
uses OAuth when the CLI is unavailable. Set `source="oauth"` to use OAuth directly.
On first use, Kazu logs an authorization URL and waits up to five minutes, polling
every five seconds (longer if the server requires it, with five seconds added for
each `slow_down`). Client registration and tokens are saved in `parallel-oauth.json`
beside the selected configuration file. Refreshed tokens are saved automatically
and reused after restart. No Parallel CLI installation or credential file is needed.
SSP remains available through `kazu ssp get` and the unified metrics endpoint.

MiniMax China Token Plan quotas are available through the built-in API. Enable
`[sources.minimax]` with `enabled = true` and put `MINIMAX_API_KEY=<Token Plan key>`
in the `.env` beside your configuration. No `mmx` installation is needed.
Both status and metrics report remaining quota by model and window; see
[LLM quotas](docs/llm-quotas.md) for units and limitations.

Configuration locations:

- Linux: `~/.config/kazu/config.toml`
- macOS: `~/Library/Application Support/kazu/config.toml`
- Windows: `%LOCALAPPDATA%/KokomiNetwork/kazu/config.toml`

Use `kazu metrics --config /path/to/config.toml` or `kazu status --config ...` to
select another file. Put credentials in the `.env` beside that file, never in
TOML. Process environment variables take precedence. See [.env.example](.env.example)
and [the default configuration](kazu/default_config.toml).

`GET /metrics` reads cached data without waiting for upstream queries. Each
source polls independently, pauses after its configured number of unconsumed
polls, and resumes asynchronously on the next Collect. The waking response
omits that source's business metrics until a later scrape can read fresh data.

See [metrics and configuration](docs/metrics.md), [status](docs/cli/status.md),
[SSP commands](docs/cli/ssp.md), and [architecture](docs/architecture.md).
