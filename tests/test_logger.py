"""The logger must drop driver and device identifiers before anything is saved."""
import importlib.util, pathlib, pytest

pytest.importorskip("google.transit.gtfs_realtime_pb2")


def test_scrub_removes_personal_fields_at_any_depth():
    spec = importlib.util.spec_from_file_location("logger_mod", pathlib.Path(__file__).parents[1] / "logger" / "logger.py")
    lg = importlib.util.module_from_spec(spec); spec.loader.exec_module(lg)
    rec = {"liveRides": [{"ride": {"rideId": "r1", "driverId": "d9", "stopStatus": [{"Departed": {"stopId": "s"}}],
                                   "acceptingDeviceId": "x", "shiftId": "y"}, "vehicle": {"name": "22006", "deviceId": "z"}}]}
    out = lg._scrub(rec)
    flat = repr(out)
    for k in ("driverId", "acceptingDeviceId", "shiftId", "deviceId", "d9"):
        assert k not in flat
    assert out["liveRides"][0]["ride"]["rideId"] == "r1" and out["liveRides"][0]["vehicle"]["name"] == "22006"
