"""End-to-end check on the shipped sample: the measurement step runs and its output is sane. About 1 minute."""
import os, pathlib, subprocess, sys, json
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_measure_on_sample(tmp_path):
    env = dict(os.environ, POT_DATA=str(ROOT / "data" / "sample"), POT_OUT=str(tmp_path))
    subprocess.run([sys.executable, "-c", "from pot import measure; measure.run()"], cwd=ROOT, env=env, check=True)
    tt = pd.read_csv(tmp_path / "tt_arrivals.csv"); lp = pd.read_csv(tmp_path / "loop_visits.csv")
    assert len(tt) > 3000 and tt.delay.between(-5, 90).all()
    assert len(lp) > 300 and lp.delay.between(-5, 60).all()
    assert "driverId" not in "".join(lp.columns)
    cov = json.load(open(tmp_path / "coverage.json")); assert cov["gaps_over_5min"] == []


def test_whole_pipeline_on_sample(tmp_path):
    """run_all.py end to end on the sample, written to a temporary folder (about 1 minute)."""
    env = dict(os.environ, POT_DATA=str(ROOT / "data" / "sample"), POT_OUT=str(tmp_path / "r"), POT_FIG=str(tmp_path / "f"))
    subprocess.run([sys.executable, "run_all.py"], cwd=ROOT, env=env, check=True, capture_output=True)
    for f in ["summary.json", "validation.json", "forecast.json", "timetable.json", "weekly.html"]:
        assert (tmp_path / "r" / f).exists(), f
    assert len(list((tmp_path / "f").glob("fig*.png"))) >= 6
    # golden values: the sample must reproduce these exactly (any change to the measurement rules shows up here)
    S = json.load(open(tmp_path / "r" / "summary.json"))
    assert (S["services"]["TigerTransit"]["n"], S["services"]["TigerTransit"]["on_time"]) == (6895, 88.1)
    assert (S["loop_route"]["TPL"]["n"], S["loop_route"]["TPL"]["on_time"], S["loop_skips"]["total"]) == (576, 73.6, 66)
    page = (tmp_path / "r" / "weekly.html").read_text()
    assert "Senior Resource" in page and "Elm Court" in page   # senior stops are always listed on the weekly page
    T = json.load(open(tmp_path / "r" / "timetable.json"))
    assert set(T["per_route"]) >= {"TPL", "TPLEXP", "1"} and all(0 <= v["today"] <= 100 for v in T["per_route"].values())
