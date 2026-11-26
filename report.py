#!/usr/bin/env python3
"""Put what partners saw next to what Atlassian declared.

A partner report is one outage someone observed: which product, which
endpoint, from when to when. This file stores reports and checks each one
against every incident Atlassian published on the relevant status pages.

  python report.py add --product confluence --start 2026-09-01T18:55 \\
      --end 2026-09-02T06:32 --endpoint /wiki/rest/api/contentbody/convert/async/view \\
      --status 503 --reporter "partner name"
  python report.py check

A report is "declared" if an incident naming the product was open on a
matching page during its window. Overlapping incidents about something else are
listed as "different subject". Neither proves it was the same failure.
"""
import argparse, json, os, re, sys
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPORTS = os.path.join(HERE, "reports.jsonl")

# Which status pages could declare an outage of each product. The developer
# page carries the partner-facing API components for every product.
PAGES = {
    "confluence": ["confluence", "developer"],
    "jira": ["jira-software", "jira-work-management", "developer"],
    "jsm": ["jira-service-management", "developer"],
    "jpd": ["jira-product-discovery", "developer"],
    "bitbucket": ["bitbucket", "developer"],
    "forge": ["developer"],
    "marketplace": ["developer"],
    "admin": ["admin", "access"],
}
# Words that make an overlapping incident plausibly about the same product.
KEYWORDS = {
    "confluence": ["confluence"], "jira": ["jira"], "jsm": ["service management", "jsm"],
    "jpd": ["product discovery"], "bitbucket": ["bitbucket"], "forge": ["forge"],
    "marketplace": ["marketplace"], "admin": ["admin", "login", "authentication"],
}
# An incident opened this long after the start of a window still counts: status
# pages are human-gated and routinely lag the failure.
LAG = timedelta(hours=2)


def parse_ts(s):
    if not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d(:\d\d)?(Z|[+-]\d\d:\d\d)?", s or ""):
        raise argparse.ArgumentTypeError(f"not an ISO timestamp: {s!r} (use 2026-09-01T18:55, UTC)")
    t = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return (t if t.tzinfo else t.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def load_jsonl(path):
    if not os.path.exists(path):
        return []
    return [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]


def inc_ts(s):
    """Incident timestamps carry milliseconds ("2026-11-16T11:07:13.970Z")."""
    t = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return (t if t.tzinfo else t.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def span(inc):
    """When an incident was open, as far as the record says.

    Start is the earlier of started_at and created_at (Atlassian sometimes
    backdates started_at). End is resolved_at; history.json rows have none, so
    for them the end is unknown and only the opening time can be used.
    """
    opened = inc_ts(inc["created_at"])
    if inc.get("started_at"):
        opened = min(opened, inc_ts(inc["started_at"]))
    closed = inc_ts(inc["resolved_at"]) if inc.get("resolved_at") else None
    return opened, closed


def matches(report, incidents):
    """Incidents on a matching page that were open at any point in the window.

    An incident opened before the window and still open during it counts:
    half the v2 incidents run longer than two hours, so checking only the
    opening time would call a long, declared outage "not declared".
    """
    pages = PAGES[report["product"]]
    lo, hi = parse_ts(report["start"]) - LAG, parse_ts(report["end"]) + LAG
    out = []
    for inc in incidents:
        if not any(inc["host"].startswith(p + ".") for p in pages):
            continue
        opened, closed = span(inc)
        if opened <= hi and (closed or opened) >= lo:
            out.append(inc)
    return out


def cmd_add(a):
    start, end = a.start, a.end
    if end <= start:
        sys.exit("--end must be after --start")
    if end - start > timedelta(days=14):
        sys.exit("window longer than 14 days - split it into separate reports")
    row = {"product": a.product, "start": iso(start), "end": iso(end),
           "endpoint": (a.endpoint or "").strip()[:300], "status": a.status,
           "reporter": (a.reporter or "anonymous").strip()[:80],
           "ticket": (a.ticket or "").strip()[:40],
           "added_at": iso(datetime.now(timezone.utc))}
    with open(a.file, "a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")
    print(f"added: {row['product']} {row['start']} -> {row['end']}")


def cmd_check(a):
    reports = load_jsonl(a.file)
    if not reports:
        return print("no partner reports yet")
    incidents = load_jsonl(os.path.join(HERE, "incidents.jsonl"))
    silent = 0
    for r in reports:
        hours = (parse_ts(r["end"]) - parse_ts(r["start"])).total_seconds() / 3600
        found = matches(r, incidents)
        words = KEYWORDS[r["product"]]
        about = [i for i in found if any(w in (i["name"] or "").lower() for w in words)]
        silent += not about
        print(f"{r['start'][:16]}  {hours:5.1f}h  {r['product']:<11} {r.get('status') or '':<4} "
              f"{r['endpoint'] or '-'}  [{r['reporter']}]")
        for inc in found:
            tag = "declared" if inc in about else "different subject"
            earlier = " (open since before the window)" if span(inc)[0] < parse_ts(r["start"]) - LAG else ""
            print(f"{'':20}{tag}: {inc['host'].split('.')[0]} {inc['created_at'][:16]} {inc['name']}{earlier}")
        if not about:
            print(f"{'':20}NOT DECLARED: nothing about {r['product']} on {', '.join(PAGES[r['product']])}")
    print(f"\n{len(reports)} reports, {silent} with nothing declared about that product in the window.")
    print("'declared' means an incident naming the product was open at the same time.")
    print("It does not prove the incident was about the same failure.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=REPORTS)
    sub = ap.add_subparsers(dest="cmd", required=True)
    add = sub.add_parser("add")
    add.add_argument("--product", required=True, choices=sorted(PAGES))
    add.add_argument("--start", required=True, type=parse_ts, help="UTC, e.g. 2026-09-01T18:55")
    add.add_argument("--end", required=True, type=parse_ts, help="UTC")
    add.add_argument("--endpoint")
    add.add_argument("--status", type=int, choices=range(100, 600), metavar="HTTP_STATUS")
    add.add_argument("--reporter")
    add.add_argument("--ticket")
    sub.add_parser("check")
    a = ap.parse_args()
    cmd_add(a) if a.cmd == "add" else cmd_check(a)


if __name__ == "__main__":
    main()
