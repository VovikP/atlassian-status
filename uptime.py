#!/usr/bin/env python3
"""Read the uptime percentages Atlassian publishes, from every status page.

Statuspage renders the 90-day uptime bars lazily: the page carries
data-uptime-lazy="<component>" placeholders and the browser fetches
/uptime_showcase?components=... when they scroll into view. This reads the same
endpoint directly, so the numbers are exactly what a visitor would see.

  python uptime.py                       # summary for all pages
  python uptime.py --component yjqnzm0tkgsd --host developer.status.atlassian.com
"""
import json, re, sys, os, argparse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
UA = {"User-Agent": "atlassian-status-index/0.1", "Accept": "application/json"}


def get(url, as_json=True):
    # The status page serves different content when asked for JSON, so the HTML
    # request must not send Accept: application/json - with it, no placeholders
    # come back and every page silently reads as "no uptime published".
    headers = UA if as_json else {"User-Agent": UA["User-Agent"]}
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=40) as r:
        body = r.read().decode("utf-8", "replace")
    return json.loads(body) if as_json else body


def showcase(host):
    html = get(f"https://{host}/", as_json=False)
    codes = sorted(set(re.findall(r'data-uptime-lazy="([a-z0-9]+)"', html)))
    names = dict(re.findall(r'data-component-id="([a-z0-9]+)"[^>]*>\s*<span class="name"[^>]*>\s*([^<]+?)\s*<', html))
    out = []
    for i in range(0, len(codes), 50):
        d = get(f"https://{host}/uptime_showcase?components=" + ",".join(codes[i:i + 50]))
        for v in d.get("values", []):
            v["name"] = names.get(v["component"], "?")
            out.append(v)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host")
    ap.add_argument("--component")
    a = ap.parse_args()

    if a.component and a.host:
        d = get(f"https://{a.host}/uptime_showcase?components={a.component}")
        v = [x for x in d["values"] if x["component"] == a.component][0]
        tl = d["timelines"][a.component]
        print(f"{tl['component']['name']}: 90d {v['ninety']}%  60d {v['sixty']}%  30d {v['thirty']}%")
        for day in tl["days"]:
            if day["outages"] or day["related_events"]:
                ev = "; ".join(e["name"] for e in day["related_events"])
                print(f"  {day['date']}  outages={day['outages'] or '-'}  events: {ev}")
        return

    hosts = [h["host"] for h in json.load(open(os.path.join(HERE, "hosts.json"))) if "alias_of" not in h]
    total = at100 = 0
    for h in hosts:
        vals = showcase(h)
        if not vals:
            print(f"{h.split('.')[0]:<26} -  no uptime published")
            continue
        n = [v["ninety"] for v in vals]
        total += len(n); at100 += sum(1 for x in n if x == 100.0)
        print(f"{h.split('.')[0]:<26} {len(n):>3} shown, {sum(1 for x in n if x == 100.0):>3} at 100.0%, lowest {min(n):.2f}")
    print(f"\n{total} components publish a 90-day uptime; {at100} of them read exactly 100.0%")


if __name__ == "__main__":
    main()
