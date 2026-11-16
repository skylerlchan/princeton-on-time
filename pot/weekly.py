"""Step 7. The weekly reliability page: one static HTML file the town could post each week.

Reads the step 1 tables, keeps the last 7 service days, and reports on-time share by route and the ten latest stops,
plus skipped Loop stops. Routes and stops only, never vehicles or drivers. Output: results/weekly.html.
"""
from __future__ import annotations
import datetime as dt, html, os
import pandas as pd
from .common import EARLY_MIN, LATE_MIN, OUT

NAMES = {"TPL": "Loop Local", "TPLEXP": "Loop Express"}


def _ot(d): return ((d >= EARLY_MIN) & (d <= LATE_MIN)).mean() * 100


def run(days: int = 7):
    tt = pd.read_csv(OUT / "tt_arrivals.csv", dtype={"route": str}); tt = tt[tt.route != "WS"]
    lp = pd.read_csv(OUT / "loop_visits.csv", dtype={"route": str}); sk = pd.read_csv(OUT / "loop_skips.csv", dtype={"route": str})
    import os
    agreed = os.environ.get("POT_UNIVERSITY_AGREED") == "1"   # TigerTransit is the University's service: shown only once it agrees
    ev = pd.concat([tt.assign(service="TigerTransit"), lp.assign(service="Princeton Loop")] if agreed else [lp.assign(service="Princeton Loop")])
    # the week runs Sunday to Saturday and ends on the last Saturday in the log, so a partial final day is never included
    end = pd.Timestamp(max(ev.date))
    while end.dayofweek != 5: end -= pd.Timedelta(days=1)
    span = lambda a, b: [(end - pd.Timedelta(days=k)).date().isoformat() for k in range(a, b)]
    # a log that stops partway through the final Saturday: step back a week rather than publish a partial day
    per = ev.groupby("date").size()
    if end.date().isoformat() in per.index and per[end.date().isoformat()] < 0.5 * per[[d for d in per.index if pd.Timestamp(d).dayofweek == 5]].median():
        end -= pd.Timedelta(days=7)
    last = sorted(span(0, days))
    if not ev.date.isin(last).any():   # a log shorter than a full week (the shipped sample): use its last days instead
        end = pd.Timestamp(max(ev.date)); last = sorted(span(0, days))
    w = ev[ev.date.isin(last)]; prev = ev[ev.date.isin(span(days, 2 * days))]
    rows = []
    for (svc, r), g in w.groupby(["service", "route"]):
        if len(g) < 50: continue   # too few departures this week to score fairly
        # the 4 full weeks before this one, as 7-day blocks counted back from the end of this week
        p4 = ev[ev.date.isin(span(days, 5 * days)) & (ev.route == r)]
        blk = p4.assign(b=[(end - pd.Timestamp(d)).days // 7 for d in p4.date])
        full = blk.groupby("b").date.nunique()
        enough = len(full) == 4 and (full >= 5).all()   # all 4 prior weeks logged (at least 5 service days each), else no comparison
        wk = blk.groupby("b").delay.apply(_ot)
        # normal variation: 2 x the spread of one week's share around a 4-week mean = 2 x sd x sqrt(1 + 1/4)
        band = 2 * wk.std() * (1 + 1 / 4) ** 0.5 if enough else float("nan")
        rows.append((svc, NAMES.get(r, "Route " + r), len(g), _ot(g.delay), _ot(p4.delay) if enough else float("nan"), (g.delay > LATE_MIN).mean() * 100, band))
    small = sorted(NAMES.get(r, "Route " + r) for r, g in w.groupby("route") if len(g) < 50)
    # a partial day = under half the median departures for that day of the week across the whole log (a logger gap)
    allday = ev.groupby("date").size(); dow = pd.to_datetime(allday.index).dayofweek
    usual = pd.Series(allday.values, index=dow).groupby(level=0).median()
    got = w.groupby("date").size()   # days with no rows at all count as 0 departures
    thin = [d for d in last if got.get(d, 0) < 0.5 * usual.get(pd.Timestamp(d).dayofweek, 0)]
    stops = w.groupby(["route", "stop"]).delay.agg(n="size", med="median", late=lambda d: (d > LATE_MIN).mean() * 100).reset_index()
    stops = stops[stops.n >= 50].sort_values("med", ascending=False).head(10)
    ws = sk[sk.date.isin(last)]; wv = lp[lp.date.isin(last)]
    skr = pd.concat([wv.groupby(["route", "stop"]).size().rename("served"), ws.groupby(["route", "stop"]).size().rename("skipped")], axis=1).fillna(0)
    # stops with at least 20 scheduled visits this week; senior stops are always shown, however few their visits
    from .summarize import SENIOR
    sen = pd.Series(skr.index.get_level_values("stop"), index=skr.index).str.contains("|".join(SENIOR), case=False)
    skr = skr[(skr.served + skr.skipped >= 20) | sen]
    skr["rate"] = skr.skipped / (skr.served + skr.skipped) * 100; sen_ = sen.reindex(skr.index, fill_value=False); skr = skr[(skr.skipped > 0) | sen_].sort_values("rate", ascending=False)
    skr = skr[skr.index.isin(skr.head(15).index) | sen_.reindex(skr.index, fill_value=False)]   # the 15 most skipped, plus every senior stop
    e = html.escape
    uni_note = ("TigerTransit is run by Princeton University; its figures are shown with the University's agreement." if agreed
                else "TigerTransit (run by Princeton University) is left out until the University agrees to publication.")
    tr = "".join(f"<tr><td>{e(a)}</td><td>{e(b)}</td><td>{n:,}</td><td class='{('ok' if v >= 80 else 'bad')}'>{v:.0f}%</td>"
                 f"<td>{'n/a (under 4 prior weeks logged)' if pv != pv else ('no change' if abs(round(v - pv)) < 1 else f'{round(v - pv):+d}') + ('' if bd != bd else (' (unusual drop)' if v - pv < -bd else ' (normal)'))}</td><td>{l:.0f}%</td></tr>" for a, b, n, v, pv, l, bd in rows)
    st = "".join(f"<tr><td>{e(NAMES.get(r.route, 'Route ' + r.route))}</td><td>{e(r.stop)}</td><td>{r.n}</td><td>{r.med:+.1f} min</td><td>{r.late:.0f}%</td></tr>" for r in stops.itertuples())
    sr = "".join(f"<tr><td>{e(NAMES.get(rt, rt))}</td><td>{e(st_)}</td><td>{int(r.skipped)}</td><td>{int(r.served + r.skipped)}</td><td>{r.rate:.0f}%</td></tr>" for (rt, st_), r in skr.iterrows())

    nice = lambda d: pd.Timestamp(d).strftime("%b %-d, %Y")
    page = f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Princeton transit reliability, week ending {last[-1]}</title>
<style>body{{font:15px/1.45 Arial,sans-serif;color:#1c2a2e;max-width:860px;margin:24px auto;padding:0 16px}}h1{{font-family:Georgia,serif;font-size:26px;margin:0}}
h2{{font-family:Georgia,serif;font-size:19px;margin:26px 0 6px}}.sub{{color:#5e6e72;margin:4px 0 16px}}table{{border-collapse:collapse;width:100%}}
th{{text-align:left;background:#102a30;color:#fff;padding:6px 8px;font-size:13px}}td{{padding:6px 8px;border-bottom:1px solid #e3e0d8}}
.ok{{color:#1d6b3a;font-weight:bold}}.bad{{color:#c8443f;font-weight:bold}}.note{{color:#5e6e72;font-size:13px;margin-top:20px}}</style></head><body>
<h1>Is Princeton's transit on time?</h1><p class="sub">Week of {e(nice(last[0]))} to {e(nice(last[-1]))}. On time = leaving between 1 minute early and 5 minutes late.</p>
<h2>By route</h2><table><tr><th>Service</th><th>Route</th><th>Departures</th><th>On time</th><th>vs previous 4 weeks (points)</th><th>Over 5 min late</th></tr>{tr}</table>
<h2>Latest stops this week</h2><table><tr><th>Route</th><th>Stop</th><th>Departures</th><th>Median</th><th>Over 5 min late</th></tr>{st}</table>
<h2>Loop stops skipped this week</h2><p class="note">Stops with fewer than 20 scheduled visits this week are left out, except senior stops, which are always shown; small counts swing widely from week to week.</p>
<table><tr><th>Route</th><th>Stop</th><th>Skipped</th><th>Scheduled visits</th><th>Share skipped</th></tr>{sr}</table>
<p class="note">Routes with fewer than 50 departures this week are left out{(': ' + e(', '.join(small))) if small else ''}.
{('Partial days (under half the usual departures for that weekday, likely a logging gap): ' + e(', '.join(thin)) + '.') if thin else 'Every day this week was fully logged.'}
Loop Local and Loop Express run different stop patterns, so compare each with its own past weeks, not with each other.
"Unusual drop" means the share fell by more than twice the route's usual week-to-week swing over the previous 4 weeks; staff should then check the feed status and ask WeDriveU about that week before posting. Rises are not flagged, since the Loop has been drifting upward.</p>
<p class="note">Sources: TripShot GPS and Loop ride records, scored against the published timetable. Routes and stops only; no rider or driver data.
{uni_note} Data through {e(nice(last[-1]))}.
Questions: Municipality of Princeton (contact to be named). Built with princeton-on-time (pot/weekly.py).</p></body></html>"""
    (OUT / "weekly.html").write_text(page)
    print(f"  weekly page: {OUT / 'weekly.html'}, week {last[0]} to {last[-1]}")
