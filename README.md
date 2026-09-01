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

## Configuration

The app uses built-in defaults when no config file exists.

If you want a persistent config file, create one under the platform config directory.

- Linux: `~/.config/kazu/config.toml`
- macOS: `~/Library/Application Support/kazu/config.toml`
- Windows: `%APPDATA%\\KokomiNetwork\\kazu\\config.toml`
