"""Every headline number in the report must match the committed full-data results (catches stale text after a rerun)."""
import json, pathlib, pytest

R = pathlib.Path(__file__).parents[1]
pytestmark = pytest.mark.skipif(not (R / "results" / "summary.json").exists(), reason="full results not present")


def test_report_numbers_match_results():
    S = json.load(open(R / "results/summary.json")); T = json.load(open(R / "results/timetable.json"))
    F = json.load(open(R / "results/forecast.json")); G = json.load(open(R / "results/gnn.json")); V = json.load(open(R / "results/validation.json"))
    txt = (R / "report/report.md").read_text()
    sk, tt, lpl, lpe, nec = S["loop_skips"], S["services"]["TigerTransit"], S["loop_route"]["TPL"], S["loop_route"]["TPLEXP"], S["nec"]
    tpl = T["per_route"]["TPL"]
    want = [f"{tt['n']:,}", f"{tt['on_time']}%", f"{lpl['on_time']}%", f"{lpe['on_time']}%", f"{lpl['n']:,}", f"{lpe['n']:,}",
            f"{S['services']['NJT bus 600/605/606']['on_time']}%", f"{nec['n']:,}", f"{nec['departures']:,}", f"{nec['late5']}%",
            f"{nec['weekend_late5']}%", f"{S['dinky']['runs']:,}", f"{sk['local_skip_rate']}%", f"{sk['local_senior_skip_rate']}%",
            f"{sk['local_other_skip_rate']}%", f"{sk['senior_by_period']['before_7pm']['senior']}%", f"{sk['senior_by_period']['before_7pm']['other']}%",
            f"{sk['local_skip_rate_upper']}%", f"{S['arrival_based']['TigerTransit']['on_time']}%", f"{S['arrival_based']['Loop']['on_time']}%",
            f"{S['weather']['tt_on_time_rain']}%", f"{tpl['today']}%", f"{tpl['today + hold']}%",
            f"{tpl['re-timed + hold']}%", f"{tpl['today + hold (half)']}%", f"{tpl['re-timed + hold (half)']}%",
            f"{F['results']['M1 local features']['mae']:.2f} min", f"{F['results']['B2 route-stop-hour history']['mae']:.2f} min",
            f"{G['mae']['graph']:.2f} min", f"{G['mae']['no graph']:.2f} min",
            f"{V['gps_vs_logged']['within_1min_share']}%", f"{S['tt_method']['passed_share']}%"]
    missing = [w for w in want if w not in txt]
    assert not missing, f"report.md lacks current values: {missing}"



def test_timetable_table_matches_results():
    """Every row of the report's replay table (section 4.6) matches results/timetable.json."""
    T = json.load(open(R / "results/timetable.json"))["per_route"]; txt = (R / "report/report.md").read_text()
    name = {"TPL": "Loop Local", "TPLEXP": "Loop Express"}
    for r, v in T.items():
        row = (f"| {name.get(r, 'TigerTransit ' + r)} | {v['today']}% | {v['today + hold (half)']}% / {v['today + hold']}% | "
               f"{v['re-timed + hold (half)']}% / {v['re-timed + hold']}% | {v['re-timed, no hold']}% |")
        assert row in txt, f"stale replay row for route {r}: expected {row}"
