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
are disabled by default. This minimal configuration uses the current CLI login:

```toml
[sources.tinyfish]
enabled = true

[sources.firecrawl]
enabled = true

[sources.parallel]
enabled = true
```

TinyFish and Firecrawl support their official CLIs and API keys. Tavily uses its
usage API. Exa is unsupported because usage queries require a special Team Service
API key and separately enabled Team Management access. Parallel's balance API
does not accept standard API keys; only its CLI with an existing OAuth login is supported.
`source="auto"` prefers CLI and falls back to a supported API; use `source="api"`
to query the API directly.
SSP remains available through `kazu ssp get` and the unified metrics endpoint.

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
