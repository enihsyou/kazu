# Kazu (数)

A Python CLI managed by uv that collects structured usage statistics from read-only APIs.

## Requirements

- Python 3.11+
- uv

## Setup

```bash
uv sync
```

## Usage

```bash
uv run kazu --help
```

Serve SSP traffic metrics for Grafana Alloy:

```bash
uv run kazu ssp metrics --host 127.0.0.1 --port 9101
```

Configure SSP authorization first. This is a long-running service exposing
`GET /metrics`, not stdout or a `.prom` textfile exporter. Add `--push-influxdb`
to opt into InfluxDB 3 reporting after its startup database/token query check.
See [SSP commands](docs/cli/ssp.md), [metrics and Alloy scrape configuration](docs/metrics.md),
and [code organization](docs/architecture.md).

## Configuration

The app uses built-in defaults when no config file exists.

If you want a persistent config file, create one under the platform config directory.

- Linux: `~/.config/kazu/config.toml`
- macOS: `~/Library/Application Support/kazu/config.toml`
- Windows: `%APPDATA%\\KokomiNetwork\\kazu\\config.toml`
