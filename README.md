# remains

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
uv run remains ssp
```

Optional arguments:

```bash
uv run remains ssp --url https://s1.thefew01.top/#/traffic --session ssp
```
