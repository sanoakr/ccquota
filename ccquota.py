#!/usr/bin/env python3
"""ccquota - Claude usage quota viewer CLI

Fetches usage data from claude.ai internal APIs and displays it in the terminal.
Requires a one-time browser login via `ccquota login`.
Subsequent data fetches are fully headless (cookie extraction + curl_cffi).
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from curl_cffi import requests as curl_requests
from playwright.sync_api import sync_playwright

CONFIG_DIR = Path.home() / ".config" / "ccquota"
BROWSER_DIR = CONFIG_DIR / "browser"
BASE_URL = "https://claude.ai"

WEEKDAY_ABBR = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


# ---------------------------------------------------------------------------
# Cookie / API helpers
# ---------------------------------------------------------------------------

def _extract_cookies() -> dict[str, str]:
    """Extract cookies from the Playwright persistent context (no page navigation)."""
    if not BROWSER_DIR.exists():
        print("No session found. Run `ccquota login` first.", file=sys.stderr)
        sys.exit(1)

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(BROWSER_DIR), channel="chrome", headless=True,
        )
        raw = ctx.cookies(["https://claude.ai"])
        ctx.close()

    return {c["name"]: c["value"] for c in raw}


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
        print("Auth error. Run `ccquota login` to re-authenticate.", file=sys.stderr)
        sys.exit(1)
    if resp.status_code != 200:
        return None

    return resp.json()


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------

def _get_org_info(cookies: dict) -> tuple[str, str]:
    """Return (org_id, org_name) from the bootstrap API."""
    data = _api("/api/bootstrap", cookies)
    if not data:
        print("Failed to fetch bootstrap info.", file=sys.stderr)
        sys.exit(1)

    memberships = data.get("account", {}).get("memberships", [])
    if not memberships:
        print("No organization found.", file=sys.stderr)
        sys.exit(1)

    org = memberships[0]["organization"]
    return org["uuid"], org.get("name", "")


def _fetch_all(cookies: dict, org_id: str) -> dict:
    """Fetch all usage data from multiple API endpoints."""
    result = {}

    usage = _api(f"/api/organizations/{org_id}/usage", cookies)
    if usage:
        result["usage"] = usage

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

def _bar(ratio: float, width: int = 30) -> str:
    filled = int(max(0, min(1, ratio)) * width)
    return f"{'█' * filled}{'░' * (width - filled)} {ratio * 100:.0f}%"


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


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

def _display(data: dict, org_name: str, *, debug: bool = False, timestamp: str = ""):
    if debug:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return

    usage = data.get("usage", {})
    spend = data.get("spend", {})
    members = data.get("members", {})
    credits_data = data.get("credits", {})

    print()
    print("  Your Usage")
    print("  " + "─" * 46)

    five = usage.get("five_hour", {})
    if five:
        u = five.get("utilization", 0) or 0
        label = "Session"
        print(f"  {label}{_pad(label)}{_bar(u / 100)}")
        r = _fmt_reset(five.get("resets_at"))
        if r:
            print(f"  {'':18s}↻ resets {r}")

    seven = usage.get("seven_day", {})
    if seven:
        u = seven.get("utilization", 0) or 0
        label = "Weekly Limit"
        print(f"  {label}{_pad(label)}{_bar(u / 100)}")
        r = _fmt_reset(seven.get("resets_at"))
        if r:
            print(f"  {'':18s}↻ resets {r}")

    omelette = usage.get("seven_day_omelette", {})
    if omelette:
        u = omelette.get("utilization", 0) or 0
        label = "Claude Design"
        print(f"  {label}{_pad(label)}{_bar(u / 100)}")
        r = _fmt_reset(omelette.get("resets_at"))
        if r:
            print(f"  {'':18s}↻ resets {r}")

    opus = usage.get("seven_day_opus", {})
    if opus:
        u = opus.get("utilization", 0) or 0
        label = "Opus"
        print(f"  {label}{_pad(label)}{_bar(u / 100)}")
        r = _fmt_reset(opus.get("resets_at"))
        if r:
            print(f"  {'':18s}↻ resets {r}")

    if spend:
        used = spend.get("used_credits", 0)
        limit = spend.get("monthly_credit_limit", 0)
        if limit:
            ratio = used / limit
            print()
            header = f"  Organization ({org_name})" if org_name else "  Organization"
            print(header)
            print("  " + "─" * 46)

            label = "Monthly Spend"
            suffix = f"  ({_cents_to_dollars(used)} / {_cents_to_dollars(limit)})"
            print(f"  {label}{_pad(label)}{_bar(ratio)}{suffix}")

            balance = credits_data.get("amount")
            if balance is not None:
                label2 = "Balance"
                print(f"  {label2}{_pad(label2)}{_cents_to_dollars(balance)}")

    items = members.get("items", [])
    if items:
        print()
        print("  Spend by User")
        print("  " + "─" * 46)
        for m in sorted(items, key=lambda x: -(x.get("used_credits", 0) or 0)):
            name = m.get("account_name", "Unknown")
            used = m.get("used_credits", 0) or 0
            print(f"  {name}{_pad(name, 24)}{_cents_to_dollars(used):>8s}")

    if timestamp:
        print()
        print(f"  Last updated: {timestamp}")

    print()


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_login():
    """Open a browser for the user to log in and save the session."""
    BROWSER_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(BROWSER_DIR), channel="chrome", headless=False,
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
            sys.exit(1)

        ctx.close()

    cookies = _extract_cookies()
    data = _api("/api/bootstrap", cookies)
    if not data:
        print("Login failed. Please try again.", file=sys.stderr)
        sys.exit(1)

    name = data.get("account", {}).get("full_name", "")
    print(f"Login successful: {name}")
    print("Run `ccquota` to view your usage.")


def _fetch_and_display(cookies: dict, org_id: str, org_name: str, *, debug: bool = False, timestamp: str = ""):
    """Fetch data and display. Returns True on success."""
    data = _fetch_all(cookies, org_id)
    if not data:
        return False
    _display(data, org_name, debug=debug, timestamp=timestamp)
    return True


def cmd_show(*, debug: bool = False, watch: bool = False, interval: int = 60):
    """Fetch and display usage data."""
    cookies = _extract_cookies()
    org_id, org_name = _get_org_info(cookies)

    if not watch:
        if not _fetch_and_display(cookies, org_id, org_name, debug=debug):
            print("Failed to fetch usage data.", file=sys.stderr)
            sys.exit(1)
        return

    try:
        while True:
            os.system("clear" if os.name != "nt" else "cls")
            now = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
            _fetch_and_display(cookies, org_id, org_name, debug=debug, timestamp=now)
            print(f"  Refreshing every {interval}s — press Ctrl+C to quit")
            time.sleep(interval)
    except KeyboardInterrupt:
        print()


def main():
    parser = argparse.ArgumentParser(
        description="Claude usage quota viewer",
        epilog="Run `ccquota login` first to authenticate.",
    )
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("login", help="Log in via browser")
    show_p = sub.add_parser("show", help="Show usage (default)")
    show_p.add_argument("--debug", action="store_true", help="Print raw JSON data")
    show_p.add_argument("--watch", "-w", action="store_true", help="Refresh every 60s")
    show_p.add_argument("--interval", "-n", type=int, default=60, metavar="SEC", help="Watch interval in seconds (default: 60)")
    parser.add_argument("--debug", action="store_true", help="Print raw JSON data")
    parser.add_argument("--watch", "-w", action="store_true", help="Refresh every 60s")
    parser.add_argument("--interval", "-n", type=int, default=60, metavar="SEC", help="Watch interval in seconds (default: 60)")

    args = parser.parse_args()
    if args.command == "login":
        cmd_login()
    else:
        cmd_show(debug=args.debug, watch=args.watch, interval=args.interval)


if __name__ == "__main__":
    main()
