#!/usr/bin/env python3
"""Ask the unified index what Atlassian declared, anywhere, in a time window.

The question this answers is the one a partner has at 2am: "my customer says
X is broken - did Atlassian say anything, on any of its status pages?" There
is no single page that answers it, which is why this exists.

  python query.py --window 2026-09-01T12:00 2026-09-02T12:00
  python query.py --grep "confluence" --since 2026-06
  python query.py --stats

Nothing here is inferred. Every row is something Atlassian published itself.
"""
import json, os, sys, argparse, collections

HERE = os.path.dirname(os.path.abspath(__file__))


def load():
    path = os.path.join(HERE, "incidents.jsonl")
    if not os.path.exists(path):
        sys.exit("incidents.jsonl not found - run collect.py first")
    return [json.loads(l) for l in open(path, encoding="utf-8")]


def short(host):
    return host.replace(".status.atlassian.com", "")


def show(rows, limit):
    if not rows:
        print("no declared incidents matched")
        return
    for r in rows[:limit]:
        print(f"{r['created_at'][:16]}  {(r['impact'] or '?'):<9} {short(r['host']):<24} {r['name']}")
        if r.get("components"):
            print(f"{'':18}  components: {', '.join(r['components'][:6])}"
                  + (f" (+{len(r['components'])-6} more)" if len(r["components"]) > 6 else ""))
    if len(rows) > limit:
        print(f"... and {len(rows)-limit} more (raise --limit)")
    print(f"\n{len(rows)} incidents across {len(set(r['host'] for r in rows))} status pages")


def stats(rows):
    by_year = collections.Counter(r["created_at"][:4] for r in rows)
    pages = collections.defaultdict(set)
    for r in rows:
        pages[r["created_at"][:4]].add(r["host"])
    print(f"{'year':<6}{'incidents':>10}{'pages live':>12}{'per page':>10}")
    for y in sorted(by_year):
        n, p = by_year[y], len(pages[y])
        print(f"{y:<6}{n:>10}{p:>12}{n/p:>10.1f}")
    print("\nA falling count is not the same as fewer failures. This index only")
    print("sees what was declared; it cannot see what was not.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", nargs=2, metavar=("FROM", "TO"),
                    help="ISO timestamps, e.g. 2026-09-01T12:00 2026-09-02T12:00")
    ap.add_argument("--since", help="ISO prefix, e.g. 2026-06")
    ap.add_argument("--grep", help="case-insensitive match on name, component or update text")
    ap.add_argument("--impact", help="minor | major | critical | maintenance")
    ap.add_argument("--page", help="status page prefix, e.g. confluence")
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--stats", action="store_true")
    a = ap.parse_args()

    rows = load()
    if a.stats:
        return stats(rows)

    if a.window:
        lo, hi = a.window
        rows = [r for r in rows if lo <= r["created_at"] <= hi]
    if a.since:
        rows = [r for r in rows if r["created_at"] >= a.since]
    if a.impact:
        rows = [r for r in rows if (r["impact"] or "") == a.impact]
    if a.page:
        rows = [r for r in rows if r["host"].startswith(a.page)]
    if a.grep:
        q = a.grep.lower()
        rows = [r for r in rows if q in (r["name"] or "").lower()
                or any(q in c.lower() for c in r.get("components", []))
                or any(q in u["body"].lower() for u in r.get("updates", []))]

    rows.sort(key=lambda r: r["created_at"])
    show(rows, a.limit)


if __name__ == "__main__":
    main()
