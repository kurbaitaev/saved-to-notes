#!/usr/bin/env python3
"""Where the Apify money went this billing cycle.

    python3 apify_usage.py              # spend by actor, plus runs per day
    python3 apify_usage.py --days 7     # only the last 7 days
    python3 apify_usage.py --actor instagram-profile-scraper --sample 5

Written after a month's budget went on 11,869 runs of a single actor that no
part of this project calls. The Apify dashboard shows the total and the plan
limit; it does not make it obvious that one actor is 94% of the bill, or that
the runs arrived at 139 a day from an API token rather than from you.

Read-only. It never starts an actor.
"""

import argparse
import collections
import datetime
import json
import os
import pathlib
import sys
import urllib.error
import urllib.request

PROJ = pathlib.Path(__file__).resolve().parent
PAGE = 1000
MAX_RUNS = 20000  # a hard stop, so a pathological account can't spin forever


def load_env() -> None:
    f = PROJ / ".env"
    if not f.exists():
        return
    for line in f.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def api(path: str, token: str):
    sep = "&" if "?" in path else "?"
    url = f"https://api.apify.com/v2/{path}{sep}token={token}"
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.load(r)["data"]


def cycle_start(token: str) -> datetime.datetime:
    """The billing cycle, not the calendar month — they rarely line up."""
    try:
        d = api("users/me/usage/monthly", token)
        s = (d.get("usageCycle") or {}).get("startAt")
        if s:
            return datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:  # noqa: BLE001
        pass
    return datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=30)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=0, help="override the billing cycle")
    ap.add_argument("--actor", help="substring: show sample runs for this actor")
    ap.add_argument("--sample", type=int, default=3)
    args = ap.parse_args()
    load_env()

    token = os.environ.get("APIFY_TOKEN", "").strip()
    if not token:
        print("No APIFY_TOKEN in .env or the environment.")
        return 1

    try:
        limits = api("users/me/limits", token)
    except urllib.error.HTTPError as e:
        print(f"Apify rejected the token ({e}).")
        return 1
    used = float(limits.get("current", {}).get("monthlyUsageUsd") or 0)
    cap = float(limits.get("limits", {}).get("maxMonthlyUsageUsd") or 0)

    since = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=args.days)
             if args.days else cycle_start(token))

    cost: collections.Counter = collections.Counter()
    runs: collections.Counter = collections.Counter()
    byday: collections.Counter = collections.Counter()
    origin: collections.Counter = collections.Counter()
    events: collections.Counter = collections.Counter()
    samples: dict[str, list] = collections.defaultdict(list)

    offset, total, done = 0, 0, False
    while not done and offset < MAX_RUNS:
        items = api(f"actor-runs?limit={PAGE}&offset={offset}&desc=1", token)["items"]
        if not items:
            break
        for r in items:
            started = r.get("startedAt")
            if started and datetime.datetime.fromisoformat(
                    started.replace("Z", "+00:00")) < since:
                done = True
                break
            act = r.get("actId") or "?"
            runs[act] += 1
            cost[act] += float(r.get("usageTotalUsd") or 0)
            byday[(started or "")[:10]] += 1
            origin[(r.get("meta") or {}).get("origin") or "?"] += 1
            for k, v in (r.get("chargedEventCounts") or {}).items():
                events[(act, k)] += v
            if len(samples[act]) < args.sample:
                samples[act].append(r)
            total += 1
        offset += PAGE

    names = {}
    for act in runs:
        try:
            names[act] = api(f"acts/{act}", token)["name"]
        except Exception:  # noqa: BLE001
            names[act] = act

    bar = f"  ${used:.2f} of ${cap:.0f}" if cap else f"  ${used:.2f} used"
    print(f"\nBilling cycle since {since:%Y-%m-%d}{bar}")
    print(f"{total} run(s) examined"
          + ("  (hit the scan limit — older runs not counted)" if total >= MAX_RUNS else ""))

    print("\nSpend by actor")
    for act, usd in cost.most_common():
        share = f"{usd / sum(cost.values()):.0%}" if sum(cost.values()) else "-"
        print(f"  ${usd:8.2f}  {share:>4}  {runs[act]:>6} run(s)  {names[act]}")

    if events:
        print("\nWhat was charged for")
        for (act, k), v in events.most_common(8):
            print(f"  {v:>8} x {k:<28} {names.get(act, act)}")

    print("\nRuns per day")
    for day, n in sorted(byday.items())[-14:]:
        print(f"  {day}  {n:>5}  {'#' * min(n // 10, 60)}")

    print(f"\nCalled from: {dict(origin)}")
    print("  API = a token (script, agent, or MCP client configured with your key)")

    if args.actor:
        match = [a for a in runs if args.actor in names.get(a, a)]
        for act in match:
            print(f"\nSample runs — {names[act]}")
            for r in samples[act]:
                print(f"  {r.get('startedAt', '')[:19]}  {r.get('status')}  "
                      f"${r.get('usageTotalUsd')}  events={r.get('chargedEventCounts')}")
                print(f"    https://console.apify.com/actors/runs/{r.get('id')}")
    elif cost:
        top = cost.most_common(1)[0][0]
        print(f"\nBiggest consumer is {names[top]}. To see individual runs:")
        print(f"  python3 apify_usage.py --actor {names[top]}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
