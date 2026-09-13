# Atlassian status index

Every incident Atlassian has published, from all of its status pages, in one
queryable file.

**3,865 incidents · 19 status pages · 2016-10-03 to 2026-09-11**

## Why

Atlassian does not have a status page. It has nineteen, split by product, plus
`status.atlassian.com`, which still resolves but reports zero components and has
published nothing since 4 March 2025 — the page most people mean when they say
"the Atlassian status page".

So when a customer says an API is broken, there is no single place to look. A
Marketplace partner [described the consequence](https://community.developer.atlassian.com/t/12-hour-api-outage-with-no-incident-report/102601)
on 10 September 2026: a Confluence endpoint returned 503 for about twelve hours,
the status page showed nothing, support confirmed an active incident privately,
and no incident was ever published. Hours went into debugging a platform
failure.

This repository is the place to look. It is built only from what Atlassian
publishes itself — public Statuspage v2 endpoints, no credentials, no probing of
anyone's site, nothing installed anywhere.

## Use

```bash
python collect.py                 # rebuild incidents.jsonl (a few minutes)
python query.py --stats
python query.py --window 2026-09-01T12:00 2026-09-02T12:00
python query.py --grep "confluence cloud api" --since 2026-01
python query.py --page confluence --impact major
```

The window query is the one that matters. Given a time a customer reported
trouble, it answers: did Atlassian declare anything, anywhere, around then.

## What the index shows

Declared incidents per year, normalised by how many status pages were live that
year — because the number of pages grew from 3 to 19 over the period, and a
raw count would mostly measure that.

| year | incidents | pages live | per page |
|-----:|----------:|-----------:|---------:|
| 2019 | 377 | 9 | 41.9 |
| 2020 | 337 | 8 | 42.1 |
| 2021 | 452 | 9 | 50.2 |
| 2022 | 504 | 12 | 42.0 |
| 2023 | 579 | 14 | 41.4 |
| 2024 | 631 | 15 | 42.1 |
| 2025 | 479 | 18 | 26.6 |
| 2026 | 218 | 19 | 11.5 |

2026 is partial (through 11 September). Even annualised it lands near 16.

Declared incidents per page have fallen by roughly half since 2024. **This index
cannot tell you why.** Fewer failures and less publishing produce exactly the
same line, and the partner report above is a documented case of the second:
support confirmed the incident, then declined to publish it because the cause
was a planned engineering change and so, by their definition, not a service
disruption.

Take the table as a measure of what Atlassian declares. Not of what breaks.

## Limitations

Stated plainly, because a record that overstates itself is worse than none.

- **Only declared incidents.** Anything not published is invisible here, by
  construction. That is the whole point of the partner's complaint and it
  applies to this dataset too.
- **The developer page files broadly.** `developer.status.atlassian.com` lists a
  median of 46 of its 53 components per incident. Component lists from that page
  indicate very little about actual scope. Other pages are specific.
- **Two sources, different detail.** Recent incidents come from the v2 API and
  carry the full update timeline. Older ones come from the `history.json`
  archive, which has no components and no updates. The `source` field says which.
- **history.json dates carry no year.** They are HTML fragments like
  `Sep <var...>11</var>, 07:46 UTC`; the year comes from the enclosing month
  object. `parse_history_ts` handles this and returns `None` rather than a guess
  when the shape is unfamiliar. The raw string is kept in `raw_timestamp`.
- **Page discovery is by guessing subdomains.** `CANDIDATES` in `collect.py` is a
  list of probes; unknown names 404 and drop out. A status page whose subdomain
  is not in that list is missing. Additions welcome.
- **`access.` and `guard.` are the same page** under two names, de-duplicated by
  Statuspage page id. There may be other aliases.

## The record, not just the data

The index is collected on a schedule by a GitHub Action. That is not for freshness. It
is because a status page can be edited after publication, and an incident can be
withdrawn — which is precisely the complaint that prompted this.

Each run re-reads the live feeds and compares them against what was stored.
Differences are appended to `changes.jsonl` with both the before and after, and
the commit history keeps the rest. Once a version is committed it cannot be
quietly revised.

The first incremental run, minutes after the initial build, already caught two
incidents changing from ongoing to resolved. That is the mechanism working, not
a finding.

Notes on what the collector adds, including two things I got wrong at first:

- **It is not hourly.** The schedule asks for hourly. Over the first 41 hours
  GitHub ran it 12 times — a median of one run every 3.4 hours, the longest gap
  5.2 hours. GitHub deprioritises scheduled jobs on low-activity repositories.
  An edit that is made and reverted inside a few hours can be missed.
- **The first version recorded noise.** It stamped a `last_seen` time on every
  incident on every run, so each of the first 12 commits rewrote all ~720 rows
  and contained no real edit at all. A genuine change would have been buried.
  That field is gone; feed membership now lives in `feed_state.json`, which
  changes only when an incident actually enters or leaves a feed. A run where
  nothing happened now produces an empty diff and no commit.
- `first_seen` exists only for incidents that appeared while the collector was
  running. Everything from the initial build lacks it, because we genuinely do
  not know when it was first published.
- `left_feed_at` records that an incident stopped appearing in a page's feed. The
  v2 API returns only the 50 most recent per page, so ageing out is the ordinary
  explanation and the field is an observation, never a claim of withdrawal.

In those first 41 hours Atlassian declared no new incident on any of its
nineteen pages, confirmed against the live feeds directly rather than trusted
from the collector. That is a quiet stretch, not a finding: at this year's rate
of roughly one a day, two days without one is unremarkable.

## Data

`incidents.jsonl`, one JSON object per line:

```
host, id, name, impact, status, created_at, started_at, resolved_at,
shortlink, components[], updates[{at,status,body}], source, raw_timestamp
```

`hosts.json` lists the status pages found, their display names and component
counts. `feed_state.json` holds the incident ids currently in each page's feed.

## Corrections

If a number here is wrong, that is worth more to me than if it is right. Open an
issue with the query that shows it.
