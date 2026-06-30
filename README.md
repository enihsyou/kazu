# Kazu (数)

A Python CLI managed by uv that fetches usage statistics from web pages via agent-browser.

## Requirements

- Python 3.11+
- uv
- agent-browser installed and available in PATH
- Browser authentication already completed by the user

## Setup

```bash
uv sync
```

## Usage

```bash
uv run kazu ssp
```

## Configuration

The app uses built-in defaults when no config file exists.

If you want a persistent config file, create one under the platform config directory.

- Linux: `~/.config/kazu/config.toml`
- macOS: `~/Library/Application Support/kazu/config.toml`
- Windows: `%APPDATA%\\KokomiNetwork\\kazu\\config.toml`
