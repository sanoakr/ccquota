# ccquota

A CLI tool that displays your [Claude](https://claude.ai) usage quota — session limits, weekly limits, organization spending, and per-user breakdown.

[日本語版 README はこちら](README.ja.md)

## How It Works

`ccquota` calls Claude's internal APIs directly. No browser is launched during normal use.

1. **Login (one-time):** Opens Chrome for you to sign in to claude.ai. The session is saved locally in `~/.config/ccquota/browser/`.
2. **Show (default):** Extracts cookies from the saved session (headless, no window), then fetches usage data via [curl_cffi](https://github.com/lexiforest/curl_cffi) which impersonates a real browser's TLS fingerprint to pass Cloudflare.

## Example Output

```
  Your Usage
  ──────────────────────────────────────────────
  Session           ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ 0%
  Weekly Limit      █████████████████████░░░░░░░░░ 72%
                    ↻ resets 4/29 (Wed) 17:00
  Claude Design     ████████████████░░░░░░░░░░░░░░ 54%
                    ↻ resets 4/29 (Wed) 17:00

  Organization (MyTeam)
  ──────────────────────────────────────────────
  Monthly Spend     ██████████████████░░░░░░░░░░░░ 60%  ($120.09 / $200.00)
  Balance           $79.90

  Spend by User
  ──────────────────────────────────────────────
  Alice                     $95.47
  Bob                       $24.67
```

## Requirements

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- Google Chrome installed on your system

## Installation

```bash
git clone https://github.com/sanoakr/ccquota.git
cd ccquota
uv sync
```

## Usage

### First-time setup

```bash
uv run ccquota login
```

A Chrome window opens. Sign in to claude.ai, and the tool auto-detects completion (up to 5 min timeout). The session is saved to `~/.config/ccquota/browser/`.

### View usage

```bash
uv run ccquota           # default: show usage
uv run ccquota show      # explicit subcommand
uv run ccquota --debug   # print raw JSON from APIs
```

### Install as a command

```bash
uv pip install -e .
ccquota
```

## API Endpoints Used

| Endpoint | Data |
|---|---|
| `/api/bootstrap` | Organization ID, user info |
| `/api/organizations/{id}/usage` | Session (5h), weekly, Design, Opus utilization |
| `/api/organizations/{id}/overage_spend_limit` | Monthly spend vs. limit |
| `/api/organizations/{id}/overage_spend_limits` | Per-user spend breakdown |
| `/api/organizations/{id}/prepaid/credits` | Prepaid credit balance |

## Data Storage

All data is stored locally under `~/.config/ccquota/browser/`. This is a Chromium user-data directory containing your claude.ai session cookies. No credentials are stored elsewhere.

To log out, delete the directory:

```bash
rm -rf ~/.config/ccquota/browser
```

## License

MIT
