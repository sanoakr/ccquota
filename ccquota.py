#!/usr/bin/env python3
"""ccquota - Claude usage quota viewer CLI

Fetches usage data from claude.ai internal APIs and displays it in the terminal.
Requires a one-time browser login via `ccquota login`.
Subsequent data fetches are fully headless (cookie extraction + curl_cffi).
"""

import argparse
import json
import os
import re
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

from curl_cffi import requests as curl_requests
from playwright.sync_api import sync_playwright

CONFIG_DIR = Path.home() / ".config" / "ccquota"
SESSIONS_DIR = CONFIG_DIR / "sessions"
_LEGACY_BROWSER_DIR = CONFIG_DIR / "browser"
BASE_URL = "https://claude.ai"

WEEKDAY_ABBR = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


# ---------------------------------------------------------------------------
# ANSI styling
# ---------------------------------------------------------------------------

def _use_color() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if not hasattr(sys.stdout, "isatty"):
        return False
    return sys.stdout.isatty()


_COLOR = _use_color()


def _s(code: str, text: str) -> str:
    if not _COLOR:
        return text
    return f"\033[{code}m{text}\033[0m"


def _bold(t: str) -> str:
    return _s("1", t)


def _dim(t: str) -> str:
    return _s("2", t)


def _green(t: str) -> str:
    return _s("32", t)


def _yellow(t: str) -> str:
    return _s("33", t)


def _red(t: str) -> str:
    return _s("31", t)


def _cyan(t: str) -> str:
    return _s("36", t)


def _bar_color(ratio: float) -> callable:
    if ratio < 0.5:
        return _green
    if ratio < 0.8:
        return _yellow
    return _red


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------

def _sanitize_name(name: str) -> str:
    """ディスプレイ名をディレクトリ名に安全な文字列に変換する。"""
    s = re.sub(r"[^\w\-.]", "_", name).strip("_")
    return s or "default"


def _session_dir(name: str) -> Path:
    return SESSIONS_DIR / name


def _list_sessions() -> list[str]:
    """既存セッション名のソート済みリストを返す。"""
    if not SESSIONS_DIR.exists():
        return []
    return sorted(
        d.name for d in SESSIONS_DIR.iterdir()
        if d.is_dir() and not d.name.startswith("_")
    )


def _migrate_legacy():
    """旧形式（単一 browser/）から名前付きセッションへの一回限りの移行。"""
    if not _LEGACY_BROWSER_DIR.exists():
        return
    name = "default"
    try:
        cookies = _extract_cookies(_LEGACY_BROWSER_DIR)
        data = _api("/api/bootstrap", cookies)
        if data:
            account = data.get("account", {})
            raw = account.get("display_name") or account.get("full_name", "")
            if raw:
                name = _sanitize_name(raw)
    except (Exception, SystemExit):
        pass
    target = _session_dir(name)
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    if target.exists():
        shutil.rmtree(target)
    shutil.move(str(_LEGACY_BROWSER_DIR), str(target))
    print(f"Migrated legacy session → '{name}'")


def _resolve_session(user: str) -> Path:
    """指定されたユーザーのセッションディレクトリを返す。"""
    d = _session_dir(user)
    if not d.exists():
        sessions = _list_sessions()
        msg = f"Session '{user}' not found."
        if sessions:
            msg += f" Available: {', '.join(sessions)}"
        else:
            msg += " Run `ccquota login` first."
        print(msg, file=sys.stderr)
        sys.exit(1)
    return d


# ---------------------------------------------------------------------------
# Cookie / API helpers
# ---------------------------------------------------------------------------

def _extract_cookies(browser_dir: Path) -> dict[str, str]:
    """Extract cookies from the Playwright persistent context (no page navigation)."""
    if not browser_dir.exists():
        print("No session found. Run `ccquota login` first.", file=sys.stderr)
        sys.exit(1)

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(browser_dir), channel="chrome", headless=True,
        )
        raw = ctx.cookies(["https://claude.ai"])
        ctx.close()

    return {c["name"]: c["value"] for c in raw}


class AuthError(Exception):
    pass


def _api(path: str, cookies: dict) -> dict | list | None:
    """Call a claude.ai API endpoint via curl_cffi."""
    url = BASE_URL + path
    try:
        resp = curl_requests.get(
            url, cookies=cookies, impersonate="chrome",
            headers={"Accept": "application/json"},
            timeout=15,
        )
    except Exception as e:
        print(f"API error: {e}", file=sys.stderr)
        return None

    if resp.status_code in (401, 403):
        raise AuthError("Run `ccquota login` to re-authenticate.")
    if resp.status_code != 200:
        return None

    return resp.json()


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------

def _get_account_info(cookies: dict) -> tuple[str, str, str]:
    """Return (org_id, org_name, user_name) from the bootstrap API."""
    data = _api("/api/bootstrap", cookies)
    if not data:
        print("Failed to fetch bootstrap info.", file=sys.stderr)
        sys.exit(1)

    account = data.get("account", {})
    user_name = account.get("display_name") or account.get("full_name", "")

    memberships = account.get("memberships", [])
    if not memberships:
        print("No organization found.", file=sys.stderr)
        sys.exit(1)

    org = memberships[0]["organization"]
    return org["uuid"], org.get("name", ""), user_name


def _fetch_all(cookies: dict, org_id: str, *, org: bool = False) -> dict:
    """Fetch usage data. Organization spending is included only when org=True."""
    result = {}

    usage = _api(f"/api/organizations/{org_id}/usage", cookies)
    if usage:
        result["usage"] = usage

    if org:
        spend = _api(f"/api/organizations/{org_id}/overage_spend_limit", cookies)
        if spend:
            result["spend"] = spend

        members = _api(f"/api/organizations/{org_id}/overage_spend_limits?page=1&per_page=100", cookies)
        if members:
            result["members"] = members

        credits = _api(f"/api/organizations/{org_id}/prepaid/credits", cookies)
        if credits:
            result["credits"] = credits

    return result


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def _bar(ratio: float, width: int = 25) -> str:
    ratio = max(0.0, min(1.0, ratio))
    filled = int(ratio * width)
    empty = width - filled
    color = _bar_color(ratio)
    pct_str = f"{ratio * 100:.0f}%"
    return color("█" * filled) + _dim("░" * empty) + " " + color(pct_str)


def _dw(s: str) -> int:
    """Display width accounting for fullwidth characters."""
    return sum(2 if ord(ch) > 0x7F else 1 for ch in s)


def _pad(label: str, col: int = 18) -> str:
    return " " * max(col - _dw(label), 1)


def _fmt_reset(iso_str: str | None) -> str:
    """Format an ISO timestamp as a local reset time."""
    if not iso_str:
        return ""
    try:
        dt = datetime.fromisoformat(iso_str).astimezone()
        wd = WEEKDAY_ABBR[dt.weekday()]
        return f"{dt.month}/{dt.day} ({wd}) {dt.hour}:{dt.minute:02d}"
    except Exception:
        return iso_str


def _cents_to_dollars(cents: int | float) -> str:
    return f"${cents / 100:.2f}"


def _section(title: str):
    print()
    print(f"  {_bold(title)}")
    print(f"  {_dim('─' * 46)}")


def _usage_row(label: str, ratio: float, reset_at: str | None = None):
    print(f"  {label}{_pad(label)}{_bar(ratio)}")
    r = _fmt_reset(reset_at)
    if r:
        print(f"  {'':18s}{_dim('↻ resets ' + r)}")


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

def _display(data: dict, org_name: str, user_name: str = "", *, debug: bool = False, timestamp: str = ""):
    if debug:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return

    usage = data.get("usage", {})
    spend = data.get("spend", {})
    members = data.get("members", {})
    credits_data = data.get("credits", {})

    title = f"Your Usage ({user_name})" if user_name else "Your Usage"
    _section(title)

    five = usage.get("five_hour", {})
    if five:
        u = (five.get("utilization", 0) or 0) / 100
        _usage_row("Session", u, five.get("resets_at"))

    seven = usage.get("seven_day", {})
    if seven:
        u = (seven.get("utilization", 0) or 0) / 100
        _usage_row("Weekly Limit", u, seven.get("resets_at"))

    omelette = usage.get("seven_day_omelette", {})
    if omelette:
        u = (omelette.get("utilization", 0) or 0) / 100
        _usage_row("Claude Design", u, omelette.get("resets_at"))

    opus = usage.get("seven_day_opus", {})
    if opus:
        u = (opus.get("utilization", 0) or 0) / 100
        _usage_row("Opus", u, opus.get("resets_at"))

    if spend:
        used = spend.get("used_credits", 0)
        limit = spend.get("monthly_credit_limit", 0)
        if limit:
            ratio = used / limit
            title = f"Organization ({org_name})" if org_name else "Organization"
            _section(title)

            label = "Monthly Spend"
            spent_str = _cents_to_dollars(used)
            limit_str = _cents_to_dollars(limit)
            suffix = _dim(f"  ({spent_str} / {limit_str})")
            print(f"  {label}{_pad(label)}{_bar(ratio)}{suffix}")

            balance = credits_data.get("amount")
            if balance is not None:
                label2 = "Balance"
                print(f"  {label2}{_pad(label2)}{_cyan(_cents_to_dollars(balance))}")

    items = members.get("items", [])
    if items:
        _section("Spend by User")
        for m in sorted(items, key=lambda x: -(x.get("used_credits", 0) or 0)):
            name = m.get("account_name", "Unknown")
            used = m.get("used_credits", 0) or 0
            dollars = _cents_to_dollars(used)
            color = _dim if used == 0 else (lambda t: t)
            print(f"  {color(name)}{_pad(name, 24)}{color(f'{dollars:>8s}')}")

    if timestamp:
        print()
        print(f"  {_dim('Updated: ' + timestamp)}")

    print()


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_login():
    """Open a browser for the user to log in and save the session."""
    _migrate_legacy()

    existing = _list_sessions()
    if existing:
        print(f"Existing sessions: {', '.join(existing)}")
        print("A new browser window will open. Log in with a different account to add it.")
        print()

    temp_dir = SESSIONS_DIR / "_login_temp"
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(temp_dir), channel="chrome", headless=False,
            viewport={"width": 1280, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://claude.ai", timeout=60_000)

        print("Please log in to claude.ai in the browser window.")
        print("Waiting for login (up to 5 minutes)...")

        for _ in range(150):
            page.wait_for_timeout(2000)
            if "claude.ai" in page.url and "login" not in page.url:
                break
        else:
            print("Timed out.", file=sys.stderr)
            ctx.close()
            shutil.rmtree(temp_dir)
            sys.exit(1)

        ctx.close()

    cookies = _extract_cookies(temp_dir)
    try:
        data = _api("/api/bootstrap", cookies)
    except AuthError:
        data = None
    if not data:
        print("Login failed. Please try again.", file=sys.stderr)
        shutil.rmtree(temp_dir)
        sys.exit(1)

    account = data.get("account", {})
    raw_name = account.get("display_name") or account.get("full_name", "")
    name = _sanitize_name(raw_name) if raw_name else "default"

    target = _session_dir(name)
    is_update = target.exists()
    if is_update:
        shutil.rmtree(target)
    shutil.move(str(temp_dir), str(target))

    if is_update:
        print(f"Session updated: {raw_name or name}")
    else:
        print(f"Session added: {raw_name or name}")

    all_sessions = _list_sessions()
    if len(all_sessions) > 1:
        print(f"All sessions: {', '.join(all_sessions)}")
        print("Run `ccquota` to view all sessions.")


def cmd_logout(user: str | None = None, *, remove_all: bool = False):
    """Remove saved session data."""
    _migrate_legacy()

    if remove_all:
        sessions = _list_sessions()
        if not sessions:
            print("No sessions found.")
            return
        for s in sessions:
            shutil.rmtree(_session_dir(s))
            print(f"Removed session: {s}")
        return

    if user:
        d = _session_dir(user)
        if not d.exists():
            sessions = _list_sessions()
            msg = f"Session '{user}' not found."
            if sessions:
                msg += f" Available: {', '.join(sessions)}"
            print(msg, file=sys.stderr)
            sys.exit(1)
        shutil.rmtree(d)
        print(f"Logged out: {user}")
        return

    sessions = _list_sessions()
    if not sessions:
        print("No sessions found.")
        return
    if len(sessions) == 1:
        shutil.rmtree(_session_dir(sessions[0]))
        print(f"Logged out: {sessions[0]}")
        return

    print("Multiple sessions. Specify with `ccquota logout <name>` or --all:", file=sys.stderr)
    for s in sessions:
        print(f"  - {s}", file=sys.stderr)
    sys.exit(1)


def _fetch_and_display(cookies: dict, org_id: str, org_name: str, user_name: str = "", *, org: bool = False, debug: bool = False, timestamp: str = ""):
    """Fetch data and display. Returns True on success."""
    data = _fetch_all(cookies, org_id, org=org)
    if not data:
        return False
    _display(data, org_name, user_name, debug=debug, timestamp=timestamp)
    return True


def _show_single(browser_dir: Path, *, org: bool, debug: bool, watch: bool, interval: int):
    """単一セッションのデータを表示する。"""
    try:
        cookies = _extract_cookies(browser_dir)
        org_id, org_name, user_name = _get_account_info(cookies)
    except AuthError as e:
        print(f"Auth error: {e}", file=sys.stderr)
        sys.exit(1)

    if not watch:
        if not _fetch_and_display(cookies, org_id, org_name, user_name, org=org, debug=debug):
            print("Failed to fetch usage data.", file=sys.stderr)
            sys.exit(1)
        return

    try:
        while True:
            os.system("clear" if os.name != "nt" else "cls")
            now = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
            _fetch_and_display(cookies, org_id, org_name, user_name, org=org, debug=debug, timestamp=now)
            print(f"  {_dim(f'Refreshing every {interval}s — Ctrl+C to quit')}")
            time.sleep(interval)
    except KeyboardInterrupt:
        print()


def _show_all(sessions: list[str], *, org: bool, debug: bool, watch: bool, interval: int):
    """全セッションのデータを表示する。"""
    def _show_one(name: str, *, timestamp: str = ""):
        try:
            cookies = _extract_cookies(_session_dir(name))
            oid, oname, uname = _get_account_info(cookies)
            if not _fetch_and_display(cookies, oid, oname, uname, org=org, debug=debug, timestamp=timestamp):
                print(f"  Failed to fetch data for '{name}'.", file=sys.stderr)
        except AuthError as e:
            print(f"  {name}: {e}", file=sys.stderr)

    if not watch:
        for s in sessions:
            _show_one(s)
        return

    try:
        while True:
            os.system("clear" if os.name != "nt" else "cls")
            now = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
            for s in sessions:
                _show_one(s, timestamp=now)
            print(f"  {_dim(f'Refreshing every {interval}s — Ctrl+C to quit')}")
            time.sleep(interval)
    except KeyboardInterrupt:
        print()


def cmd_show(*, user: str | None = None, org: bool = False, debug: bool = False, watch: bool = False, interval: int = 60):
    """Fetch and display usage data."""
    _migrate_legacy()

    if user:
        browser_dir = _resolve_session(user)
        _show_single(browser_dir, org=org, debug=debug, watch=watch, interval=interval)
    else:
        sessions = _list_sessions()
        if not sessions:
            print("No sessions found. Run `ccquota login` first.", file=sys.stderr)
            sys.exit(1)
        _show_all(sessions, org=org, debug=debug, watch=watch, interval=interval)


def main():
    parser = argparse.ArgumentParser(
        description="Claude usage quota viewer",
        epilog="Run `ccquota login` first to authenticate.",
    )
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("login", help="Log in via browser (run again to add another account)")

    logout_p = sub.add_parser("logout", help="Remove saved session")
    logout_p.add_argument("user", nargs="?", help="Session name to remove")
    logout_p.add_argument("--all", action="store_true", help="Remove all sessions")

    show_p = sub.add_parser("show", help="Show usage (default)")
    show_p.add_argument("--user", "-u", help="Show only this session")
    show_p.add_argument("--org", "-o", action="store_true", help="Include organization spending and per-user breakdown")
    show_p.add_argument("--debug", action="store_true", help="Print raw JSON data")
    show_p.add_argument("--watch", "-w", action="store_true", help="Refresh every 60s")
    show_p.add_argument("--interval", "-n", type=int, default=60, metavar="SEC", help="Watch interval in seconds (default: 60)")

    parser.add_argument("--user", "-u", help="Show only this session")
    parser.add_argument("--org", "-o", action="store_true", help="Include organization spending and per-user breakdown")
    parser.add_argument("--debug", action="store_true", help="Print raw JSON data")
    parser.add_argument("--watch", "-w", action="store_true", help="Refresh every 60s")
    parser.add_argument("--interval", "-n", type=int, default=60, metavar="SEC", help="Watch interval in seconds (default: 60)")

    args = parser.parse_args()
    if args.command == "login":
        cmd_login()
    elif args.command == "logout":
        cmd_logout(args.user, remove_all=args.all)
    else:
        cmd_show(user=args.user, org=args.org, debug=args.debug, watch=args.watch, interval=args.interval)


if __name__ == "__main__":
    main()
