#!/usr/bin/env python3
"""Collect every incident Atlassian has published, across all of its status pages.

Two modes.

Full (default) rebuilds from scratch: the v2 API for recent incidents plus the
deeper history.json archive, back as far as it goes.

Incremental (--incremental) keeps what is already in incidents.jsonl and re-reads
only the v2 feeds. It is what the hourly job runs. Its real purpose is not speed:
it is that a status page can be edited after the fact, and an incident can be
withdrawn. Each run compares what a page says now against what it said before and
appends any difference to changes.jsonl. Git keeps the rest - the record of what
was published cannot be quietly revised once it is in the commit history.

Why this exists: Atlassian does not have one status page. It has 20 live ones
split by product, plus status.atlassian.com, which still resolves but has no
components and no incident since March 2025. A partner whose customer reports a
broken API has no single place to look. This builds that place.

Everything here is public: Statuspage v2 endpoints, no credentials, no probing
of anyone's site.

Usage:  python collect.py [--hosts-only] [--max-pages N]
Output: incidents.jsonl  (one incident per line)
        hosts.json       (the status pages found, with component counts)
"""
import json, re, sys, os, time, urllib.request, urllib.error
import concurrent.futures as cf

UA = {"User-Agent": "atlassian-status-index/0.1 (public Statuspage API reader)"}
OUT = os.path.dirname(os.path.abspath(__file__))

# Subdomains probed for a Statuspage. Unknown ones simply 404 and are dropped,
# so adding a guess here is cheap and wrong guesses are self-correcting.
CANDIDATES = """status jira jira-software jira-service-management jira-work-management
jira-product-discovery jira-align confluence bitbucket trello opsgenie statuspage compass
atlas loom rovo guard developer marketplace admin analytics bamboo crowd fisheye sourcetree
halp forge access identity jsm jpd jwm team-central mercury focus talent""".split()


MONTHS = {m: n for n, m in enumerate(
    "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(), start=1)}


def parse_history_ts(raw, year):
    """history.json dates are HTML fragments and carry no year.

    They look like: "Sep <var data-var='date'>11</var>, <var ...>07:46</var> UTC"
    and sometimes a range, "Apr 10, 00:30 - 01:30 UTC". The year lives on the
    enclosing month object, so it has to be passed in. Returns an ISO-8601
    string, or None if the shape is unfamiliar - never a half-parsed guess.
    """
    if not raw or not year:
        return None
    text = re.sub(r"<[^>]+>", "", raw)
    m = re.match(r"\s*([A-Z][a-z]{2})\s+(\d{1,2}),\s*(\d{2}):(\d{2})", text)
    if not m or m.group(1) not in MONTHS:
        return None
    mon, day, hh, mm = MONTHS[m.group(1)], int(m.group(2)), int(m.group(3)), int(m.group(4))
    try:
        return f"{int(year):04d}-{mon:02d}-{day:02d}T{hh:02d}:{mm:02d}:00Z"
    except (TypeError, ValueError):
        return None


def fetch(url, tries=3):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(1 + i)
        except Exception:
            time.sleep(1 + i)
    return None


def discover():
    def probe(sub):
        host = f"{sub}.status.atlassian.com"
        d = fetch(f"https://{host}/api/v2/summary.json")
        if not d:
            return None
        return {"host": host,
                "name": d["page"]["name"],
                "components": len(d.get("components", [])),
                "page_id": d["page"]["id"]}
    found = []
    with cf.ThreadPoolExecutor(16) as ex:
        for r in ex.map(probe, CANDIDATES):
            if r:
                found.append(r)
    # Distinct pages only: access./guard. are the same page under two names.
    seen, uniq = set(), []
    for h in sorted(found, key=lambda x: x["host"]):
        if h["page_id"] in seen:
            h["alias_of"] = next(u["host"] for u in uniq if u["page_id"] == h["page_id"])
        else:
            seen.add(h["page_id"])
        uniq.append(h)
    return uniq


def incidents_for(host, max_pages):
    """Recent incidents from the v2 API, then the deeper /history.json archive.

    The two overlap; de-duplication is by incident id, and the v2 record wins
    because it carries the update timeline that history.json omits.
    """
    by_id = {}
    d = fetch(f"https://{host}/api/v2/incidents.json")
    for i in (d or {}).get("incidents", []):
        by_id[i["id"]] = {
            "host": host, "id": i["id"], "name": i["name"],
            "impact": i.get("impact"), "status": i.get("status"),
            "created_at": i.get("created_at"), "started_at": i.get("started_at"),
            "resolved_at": i.get("resolved_at"), "shortlink": i.get("shortlink"),
            "components": [c["name"] for c in i.get("components", [])],
            "updates": [{"at": u["created_at"], "status": u["status"],
                         "body": " ".join(u["body"].split())}
                        for u in i.get("incident_updates", [])],
            "source": "v2",
        }
    page, empty_pages = 1, 0
    while page <= max_pages and empty_pages < 2:
        h = fetch(f"https://{host}/history.json?page={page}")
        months = (h or {}).get("months", [])
        got = 0
        for m in months:
            year = m.get("year")
            for i in m.get("incidents", []):
                got += 1
                if i["code"] in by_id:
                    continue
                by_id[i["code"]] = {
                    "host": host, "id": i["code"], "name": i.get("name"),
                    "impact": i.get("impact"), "status": "resolved",
                    "created_at": parse_history_ts(i.get("timestamp"), year),
                    "started_at": parse_history_ts(i.get("timestamp"), year),
                    "resolved_at": None, "shortlink": None,
                    "components": [], "updates": [],
                    "raw_timestamp": i.get("timestamp"), "source": "history",
                }
        empty_pages = empty_pages + 1 if got == 0 else 0
        page += 1
    return list(by_id.values())


def fingerprint(rec):
    """The parts of an incident whose change is worth recording.

    Deliberately excludes first_seen/last_seen, which change every run, and
    excludes ordering of components, which the API does not guarantee.
    """
    return {
        "name": rec.get("name"),
        "impact": rec.get("impact"),
        "status": rec.get("status"),
        "started_at": rec.get("started_at"),
        "resolved_at": rec.get("resolved_at"),
        "components": sorted(rec.get("components") or []),
        "updates": [(u["at"], u["status"], u["body"]) for u in rec.get("updates") or []],
    }


def load_existing(path):
    if not os.path.exists(path):
        return {}
    out = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                r = json.loads(line)
                out[(r["host"], r["id"])] = r
    return out


def incremental(hosts, now):
    """Re-read the v2 feeds, merge into the existing file, log what changed."""
    inc_path = os.path.join(OUT, "incidents.jsonl")
    chg_path = os.path.join(OUT, "changes.jsonl")
    existing = load_existing(inc_path)
    if not existing:
        sys.exit("incidents.jsonl is empty - run a full collect first")

    fresh = {}
    with cf.ThreadPoolExecutor(8) as ex:
        futs = {ex.submit(v2_only, h["host"]): h["host"] for h in hosts}
        for f in cf.as_completed(futs):
            for r in f.result():
                fresh[(r["host"], r["id"])] = r

    changes, added = [], 0
    for key, new in fresh.items():
        old = existing.get(key)
        if old is None:
            new["first_seen"] = now
            new["last_seen"] = now
            existing[key] = new
            added += 1
            continue
        before, after = fingerprint(old), fingerprint(new)
        old["last_seen"] = now
        if before != after:
            changed = sorted(k for k in after if before.get(k) != after.get(k))
            changes.append({"at": now, "host": key[0], "id": key[1],
                            "fields": changed, "before": before, "after": after})
            old.update({k: new[k] for k in
                        ("name", "impact", "status", "started_at", "resolved_at",
                         "components", "updates")})
            old["last_changed"] = now

    # An incident present in a feed before and absent now is worth a line of its
    # own. It may simply have aged past the 50-item window, so this is recorded
    # as an observation, never asserted as a withdrawal.
    seen_hosts = {h["host"] for h in hosts}
    for key, rec in existing.items():
        stale = (key[0] in seen_hosts and key not in fresh
                 and rec.get("last_seen") and rec.get("last_seen") != now
                 and not rec.get("left_feed_at"))
        if stale:
            rec["left_feed_at"] = now

    rows = sorted(existing.values(), key=lambda r: (r.get("created_at") or "", r["host"]))
    with open(inc_path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    if changes:
        with open(chg_path, "a", encoding="utf-8") as fh:
            for c in changes:
                fh.write(json.dumps(c, ensure_ascii=False) + "\n")

    print(f"incidents: {len(rows)} total, {added} new")
    print(f"edits to already-published incidents: {len(changes)}")
    for c in changes[:10]:
        print(f"  {c['host'].split('.')[0]:<24} {c['id']}  changed: {', '.join(c['fields'])}")


def v2_only(host):
    d = fetch(f"https://{host}/api/v2/incidents.json")
    out = []
    for i in (d or {}).get("incidents", []):
        out.append({
            "host": host, "id": i["id"], "name": i["name"],
            "impact": i.get("impact"), "status": i.get("status"),
            "created_at": i.get("created_at"), "started_at": i.get("started_at"),
            "resolved_at": i.get("resolved_at"), "shortlink": i.get("shortlink"),
            "components": [c["name"] for c in i.get("components", [])],
            "updates": [{"at": u["created_at"], "status": u["status"],
                         "body": " ".join(u["body"].split())}
                        for u in i.get("incident_updates", [])],
            "source": "v2",
        })
    return out



def main():
    max_pages = 40
    if "--max-pages" in sys.argv:
        max_pages = int(sys.argv[sys.argv.index("--max-pages") + 1])

    hosts = discover()
    live = [h for h in hosts if "alias_of" not in h]
    json.dump(hosts, open(os.path.join(OUT, "hosts.json"), "w"), indent=1)
    print(f"status pages: {len(hosts)} probed hostnames, {len(live)} distinct pages")
    if "--hosts-only" in sys.argv:
        return

    if "--incremental" in sys.argv:
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        return incremental(live, now)

    rows = []
    with cf.ThreadPoolExecutor(8) as ex:
        futs = {ex.submit(incidents_for, h["host"], max_pages): h["host"] for h in live}
        for f in cf.as_completed(futs):
            got = f.result()
            rows += got
            print(f"  {futs[f]:<46} {len(got)} incidents")

    rows.sort(key=lambda r: (r.get("created_at") or ""))
    with open(os.path.join(OUT, "incidents.jsonl"), "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    dated = [r["created_at"][:10] for r in rows if r.get("created_at")]
    print(f"\ntotal incidents: {len(rows)}")
    if dated:
        print(f"range: {min(dated)} .. {max(dated)}")


if __name__ == "__main__":
    main()
