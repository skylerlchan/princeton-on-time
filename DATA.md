# Data dictionary

All feeds are polled by `logger/logger.py` and written as one JSON object per line, one file per feed per day
(`<feed>_<YYYY-MM-DD>.jsonl`, gzipped after two days). Times are Unix seconds (`poll`) unless noted.

| File | Source | Poll | Key fields |
|---|---|---|---|
| `vp_*` | TripShot GTFS-Realtime VehiclePosition | 30 s | `poll`, `ts`, `veh`, `trip_id`, `stop_id` (next stop), `lat`, `lon`, `speed`, `status`, `occ` |
| `loop_*` | TripShot route live pages (TPL, TPLEXP) | 30 s (2 min before Oct 4) | `route`, `visits[]` (stop state per trip), `liveRides[].ride.stopStatus[]` (`scheduledAt`, `arrivalTime`, `departureTime`, state), `vehicleName`, `riderCount` |
| `dv_*` | NJ Transit DepartureVision, Princeton Junction and Princeton | 30 s | `station`, `line` (NEC, PRIN), `train`, `sched`, `status` ("in N Min", CANCELLED...) |
| `mybus_*` | NJ Transit MyBus, 7 Princeton stops | 30 s | `route`, `stop_id`, `trip`, `sched`, `predicted`, `capacity` |
| `tu_*` | TripShot GTFS-Realtime TripUpdate | 5 min | predicted arrival per remaining stop |
| `amtrak_*` | Amtraker, Princeton Junction | 30 s | trains at the station |
| `events_*` | NWS KTTN, NWS alerts, NJ Transit status and RSS, TripShot alerts | 5 min | `weather.temperature`, `weather.text`, `nws_alerts[]` |
| `usgs_*` | USGS 01401000 and nearby gauges | 15 min | discharge, gauge height, precipitation |
| `gtfs/gtfs_<date>.zip` | TripShot GTFS static | daily | the timetable in force that day |

## Derived tables (results/)

| File | One row per | Columns |
|---|---|---|
| `tt_arrivals.csv` | TigerTransit stop departure | `date, route, trip_id, stop_id, stop, seq, sched_s, actual_s, epoch, delay, arr_delay, veh, how` |
| `loop_visits.csv` | Loop stop departure | same, `veh` = LOOP-<vehicle> |
| `loop_skips.csv` | scheduled Loop stop marked Skipped | `date, route, trip_id, stop_id, stop, sched_s, hour` |
| `loop_trips.csv` | Loop trip | `vehicle, riders` (highest operator rider count), `stops, skipped` |
| `rail.csv` | train departure | `date, station, line, train, sched, delay, status, cancelled` |
| `njt_bus.csv` | NJ Transit bus at a stop | `date, route, stop_id, trip, stop, delay` |
| `weather.csv` | hour | `temp, wind, rain, text` |

`delay` is minutes, positive = late. `sched_s` and `actual_s` are seconds after local midnight of the service day.

## Privacy

Raw `loop_*` files logged through Nov 15, 2026 (the study period) contain operator driver, device and shift identifiers.
The logger was changed that evening to drop them before saving, so later files do not. No step reads them, the sample has them
removed, and no output contains them. Publish only route- and stop-level results.
