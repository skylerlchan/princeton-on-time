"""The timetable replay must reproduce the observed day when nothing changes, and holding must never make a bus earlier."""
import numpy as np, pandas as pd
from pot.timetable import _simulate


def _day():
    # one bus, two trips; trip B starts 2 min after trip A ends (a tight layover); second stop of A runs 1 min late
    rows = [("A", 1, 36000, 36000), ("A", 2, 36600, 36660), ("A", 3, 37200, 37260),
            ("B", 1, 37380, 37380), ("B", 2, 37980, 37950)]
    df = pd.DataFrame(rows, columns=["trip_id", "seq", "sched_s", "actual_s"])
    df["veh"], df["date"], df["route"], df["stop_id"] = "v1", "2026-11-02", "1", ["s1", "s2", "s3", "s1", "s2"]
    df["delay"] = (df.actual_s - df.sched_s) / 60
    return df


def test_replay_reproduces_observed_day_without_changes():
    df = _day(); df["prop_s"] = df.sched_s
    out = _simulate(df, hold=False).sort_index()
    assert np.allclose(out.new_delay.values, df.delay.values)


def test_holding_only_removes_earliness_and_pushes_tight_next_trip():
    df = _day(); df["prop_s"] = df.sched_s + 120              # a later timetable: the bus is now 2 min early everywhere
    out = _simulate(df, hold=True).sort_index()
    assert (out.new_delay >= -1e-9).all()                     # with full holding nothing leaves early
    assert (out.new_delay * 60 + df.prop_s >= df.actual_s - 1e-6).all()   # holding never makes a bus leave sooner


def test_unobserved_last_leg_eats_the_layover():
    # trip A's last stop is never observed but ends at 37,320 s, so only 60 s of real layover remain before B
    df = _day(); df["prop_s"] = df.sched_s; df.loc[df.trip_id == "A", "prop_s"] += [0, 120, 120]
    df["obs_end"] = np.where(df.trip_id == "A", 37320.0, 38500.0)
    out = _simulate(df, hold=True).sort_index()
    # A waits 60 s at stop 2, ending 60 s later; no layover slack remains, so B starts 60 s late
    assert np.isclose(out.new_delay.values[3], 1.0)
