# ccquota

A CLI tool that displays your [Claude](https://claude.ai) usage quota — session limits, weekly limits, and optionally organization spending with per-user breakdown.

[日本語版 README はこちら](README.ja.md)

## How It Works

`ccquota` calls Claude's internal APIs directly. No browser is launched during normal use.

1. **Login (one-time):** Opens Chrome for you to sign in to claude.ai. The session is saved locally in `~/.config/ccquota/browser/`.
2. **Show (default):** Extracts cookies from the saved session (headless, no window), then fetches usage data via [curl_cffi](https://github.com/lexiforest/curl_cffi) which impersonates a real browser's TLS fingerprint to pass Cloudflare.

## Example Output

```
  Your Usage (Alice)
  ──────────────────────────────────────────────
  Session           ░░░░░░░░░░░░░░░░░░░░░░░░░ 0%
  Weekly Limit      ██████████████████░░░░░░░ 72%
                    ↻ resets 4/29 (Wed) 17:00
  Claude Design     █████████████░░░░░░░░░░░░ 54%
                    ↻ resets 4/29 (Wed) 17:00
```

With `--org`:

```
  Organization (MyTeam)
  ──────────────────────────────────────────────
  Monthly Spend     ███████████████░░░░░░░░░░ 60%  ($120.09 / $200.00)
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
ccquota                  # personal usage only (default)
ccquota --org            # include organization spending & per-user breakdown
ccquota --watch          # refresh every 60s
ccquota -w -n 30         # refresh every 30s
ccquota -o -w            # organization + watch mode
ccquota --debug          # print raw JSON from APIs
```

> When installed via `uv pip install -e .`, you can run `ccquota` directly. Otherwise prefix with `uv run`.

### Options

| Flag | Short | Description |
|---|---|---|
| `--org` | `-o` | Include organization spending and per-user breakdown |
| `--watch` | `-w` | Refresh periodically (default: every 60s) |
| `--interval SEC` | `-n SEC` | Watch interval in seconds (default: 60) |
| `--debug` | | Print raw JSON data from APIs |

## API Endpoints Used

| Endpoint | Data | When |
|---|---|---|
| `/api/bootstrap` | Organization ID, user info | Always |
| `/api/organizations/{id}/usage` | Session (5h), weekly, Design, Opus utilization | Always |
| `/api/organizations/{id}/overage_spend_limit` | Monthly spend vs. limit | `--org` |
| `/api/organizations/{id}/overage_spend_limits` | Per-user spend breakdown | `--org` |
| `/api/organizations/{id}/prepaid/credits` | Prepaid credit balance | `--org` |

## Data Storage

All data is stored locally under `~/.config/ccquota/browser/`. This is a Chromium user-data directory containing your claude.ai session cookies. No credentials are stored elsewhere.

To log out, delete the directory:

```bash
rm -rf ~/.config/ccquota/browser
```

## License

MIT
