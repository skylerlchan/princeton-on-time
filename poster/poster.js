// Poster, 48 x 36 in landscape, for the Dec 7 session at the municipal building. Most numbers are read from results/;
// a few short facts are typed in and match the report (39 unserved trips, 38% +/-7 aged 65+, 4 min and 3 of 7 layover minutes).
// Build (from the repository root): python poster/aspect.py && (cd poster && npm install) && node poster/poster.js
const pptxgen = require("pptxgenjs");
const path = require("path");
const ROOT = path.resolve(__dirname, "..");
const S = require(path.join(ROOT, "results/summary.json"));
const F = require(path.join(ROOT, "results/forecast.json"));
const T = require(path.join(ROOT, "results/timetable.json"));
const G = require(path.join(ROOT, "results/gnn.json"));
const C = require(path.join(ROOT, "results/coverage.json"));
const V = require(path.join(ROOT, "results/validation.json"));
const A = require(path.join(__dirname, "aspect.json"));
const fig = n => path.join(ROOT, "figures", n);

const pres = new pptxgen();
pres.defineLayout({ name: "POSTER", width: 48, height: 36 }); pres.layout = "POSTER";
pres.title = "Princeton On Time"; pres.author = "Skyler Chan, Victoria Spradlin";
const DARK = "102A30", AMBER = "F2B134", INK = "1C2A2E", MUTE = "4F5E62", TEAL = "7FB7BC", SAND = "F1EEE6", WHITE = "FFFFFF", PALE = "DCE3E4";
const H = "Georgia", B = "Arial";
const s = pres.addSlide(); s.background = { color: WHITE };
const r0 = x => Math.round(x), f1 = x => x.toFixed(1);
const tt = S.services.TigerTransit, lpL = S.loop_route.TPL, sk = S.loop_skips, W = S.weather;
const tpl = T.per_route.TPL, m1 = F.results["M1 local features"], b0 = F.results["B0 timetable"], b2 = F.results["B2 route-stop-hour history"];
const LT = Object.fromEntries(require("fs").readFileSync(path.join(ROOT, "results/timetable_test.csv"), "utf8").split("\n").filter(l => l.startsWith("TPL,") && !l.startsWith("TPL,\"")).map(l => { const c = l.split(","); return [c[1].replace(/"/g, ""), +c[5]]; }));
const nDep = S.services.TigerTransit.n + S.services.Loop.n + S.services["NJT bus 600/605/606"].n + S.services["NEC trains, Princeton Jct"].n;

// ---------- header band
s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 48, h: 5.7, fill: { color: DARK }, line: { color: DARK } });
s.addShape(pres.shapes.RECTANGLE, { x: 1, y: 0.9, w: 0.35, h: 3.7, fill: { color: AMBER }, line: { color: AMBER } });
s.addText("Princeton On Time", { x: 1.7, y: 0.55, w: 23, h: 2.2, fontFace: H, fontSize: 118, bold: true, color: WHITE, margin: 0 });
s.addText(`Does Princeton's transit keep its own timetable? We logged Princeton's buses and trains every 30 seconds for ${S.services.TigerTransit.days} days and scored ${(nDep / 1000).toFixed(0)},000 departures against the timetable.`,
  { x: 1.7, y: 2.8, w: 23.5, h: 1.6, fontFace: B, fontSize: 30, color: PALE, margin: 0, valign: "top" });
s.addText("Skyler Chan · Victoria Spradlin   |   CEE 420 Urban AI, Princeton University   |   Report to the Municipality of Princeton, December 2026",
  { x: 1.7, y: 4.65, w: 25, h: 0.6, fontFace: B, fontSize: 22, color: AMBER, margin: 0 });
const stats = [
  [`${f1(tt.on_time)}%`, "TigerTransit departures\non time (measured)", AMBER, 96],
  [`${r0(lpL.on_time)}%`, "Loop Local departures\non time (measured)", "F28B82", 96],
  [`${r0(sk.local_skip_rate)}%`, `of Loop Local stop visits skipped;\nSenior Resource Ctr ${r0(sk.senior_by_stop["Princeton Senior Resource Ctr."])}%`, WHITE, 96],
  [`${r0(tpl.today)}→${r0(tpl["today + hold"])}%`, `Loop Local, Nov test weeks, if every\nearly bus waits (${r0(tpl["today + hold (half)"])}% if half do)`, TEAL, 70],
];
stats.forEach(([big, lab, col, size], i) => {
  const x = 26.0 + i * 5.45;
  s.addText(big, { x, y: 0.75, w: 5.3, h: 2.3, fontFace: H, fontSize: size, bold: true, color: col, align: "center", valign: "middle", margin: 0 });
  s.addText(lab, { x, y: 3.15, w: 5.3, h: 1.5, fontFace: B, fontSize: 21, color: PALE, align: "center", margin: 0, valign: "top" });
});

// ---------- helpers
const COLW = 14.6, COLX = [1, 16.7, 32.4], BODY = 27, CAP = 21;
function head(col, y, n, t) {
  const x = COLX[col];
  s.addShape(pres.shapes.RECTANGLE, { x, y: y + 0.08, w: 0.8, h: 0.8, fill: { color: AMBER }, line: { color: AMBER } });
  s.addText(String(n), { x, y: y + 0.08, w: 0.8, h: 0.8, fontFace: H, fontSize: 34, bold: true, color: DARK, align: "center", valign: "middle", margin: 0 });
  s.addText(t, { x: x + 1.05, y, w: COLW - 1.05, h: 0.98, fontFace: H, fontSize: 38, bold: true, color: DARK, margin: 0, valign: "middle" });
  return y + 1.2;
}
function para(col, y, runs, h, size = BODY) {
  s.addText(runs, { x: COLX[col], y, w: COLW, h, fontFace: B, fontSize: size, color: INK, margin: 0, valign: "top", paraSpaceAfter: 4 });
  return y + h;
}
function img(col, y, name, w = COLW, cap = null, caph = 0.7) {
  const h = w * A[name];
  s.addImage({ path: fig(name), x: COLX[col] + (COLW - w) / 2, y, w, h });
  y += h;
  if (cap) { s.addText(cap, { x: COLX[col], y: y + 0.05, w: COLW, h: caph, fontFace: B, fontSize: CAP, color: MUTE, italic: true, margin: 0, valign: "top" }); y += caph + 0.1; }
  return y + 0.1;
}
const b = t => ({ text: t, options: { bold: true } });
const r = (t, o = {}) => ({ text: t, options: o });

// ---------- column 1: problem, data, method
let y = 6.35;
y = head(0, y, 1, "Problem");
y = para(0, y, [r("The free "), b("Loop"), r(" bus, TigerTransit, NJ Transit's 600, 605 and 606, the Dinky and the trains are how residents without a car reach groceries, doctors and work. Operators may track punctuality internally, but no reliability figure for Princeton is published. Yet every bus reports its position every few seconds. "),
  b("We ask: how late, where, why, and what free change would fix it?")], 2.9);
y = head(0, y + 0.15, 2, "Data, and where buses run late");
y = img(0, y, "fig2_map.png", 13.6, "Every stop we measured, coloured by median minutes behind the timetable, all routes at the stop combined (so it can differ from route figures). Grey: TigerTransit. Amber: the Loop.", 1.0);
y = para(0, y, [r("TripShot bus GPS and the Loop operator's ride records, NJ Transit boards, weather and rain, every 30 s from a cloud server, Sep 30 to Nov 15, 2026: "),
  b(`${(S.coverage.total_rows / 1e6).toFixed(1)} million records, no gap in the bus GPS over 5 minutes.`)], 2.3);
y = head(0, y + 0.15, 3, "Method");
y = para(0, y, [b("On time"), r(" = leaving between 1 minute early and 5 minutes late. We score "), b("departures"), r(": a bus that arrives early and waits strands nobody. Each day is scored against the timetable published that day. Trains and NJ Transit buses are estimated from the operator's countdown."),
  { text: "", options: { breakLine: true } }, b("Check: "), r(`Loop GPS agrees with the operator's logged departure within 1 minute ${r0(V.gps_vs_logged.within_1min_share)}% of the time; TigerTransit GPS agrees with TripShot's published times ${r0(V.tigertransit_gps_vs_published.within_1min_share)}% of the time.`)], 3.5);

// ---------- column 1 foot: what the town gets
{ const by = y + 0.15, bh = 34.4 - by;
  s.addShape(pres.shapes.RECTANGLE, { x: COLX[0], y: by, w: COLW, h: bh, fill: { color: SAND }, line: { color: SAND } });
  s.addText("Limits", { x: COLX[0] + 0.4, y: by + 0.2, w: COLW - 0.8, h: 0.7, fontFace: H, fontSize: 30, bold: true, color: DARK, margin: 0 });
  const bl1 = (t, last) => ({ text: t, options: { bullet: { indent: 26 }, breakLine: !last } });
  s.addText([bl1("No field timing: checked against other public records, all from TripShot."),
    bl1("Trains and NJ Transit buses are estimates from countdown boards."),
    bl1("The fixes are a replay that depends on drivers waiting, not a trial."),
    bl1("Seven mild autumn weeks; riders were not surveyed.", true)],
    { x: COLX[0] + 0.4, y: by + 0.85, w: COLW - 0.8, h: 2.1, fontFace: B, fontSize: 24, color: INK, margin: 0, valign: "top", paraSpaceAfter: 4 });
  s.addText("Who carries the risk", { x: COLX[0] + 0.4, y: by + 2.95, w: COLW - 0.8, h: 0.7, fontFace: H, fontSize: 30, bold: true, color: DARK, margin: 0 });
  s.addText([bl1("All five senior stops the Loop serves are on the Loop Local, the least reliable bus run in town. Report reliability per stop, not only per route."), bl1("Senior Resource Center tract: 38% aged 65+ (±7), against 13% town-wide (ACS).", true)],
    { x: COLX[0] + 0.4, y: by + 3.6, w: COLW - 0.8, h: bh - 3.7, fontFace: B, fontSize: 24, color: INK, margin: 0, valign: "top", paraSpaceAfter: 4 }); }

// ---------- column 2: findings
y = 6.35;
y = head(1, y, 4, "Campus buses clear 80%; the Loop Local does not");
y = img(1, y, "fig1_scorecard.png", 12.2, "Share of departures on time, Sep 30 to Nov 15, with 95% intervals. Red: below our 80% benchmark. Hatched: estimated from countdowns.", 0.7);
y = para(1, y, [r("The Loop Local misses both ways: "), b(`${r0(lpL.early)}% leave early, ${r0(lpL.late5)}% leave over 5 min late.`), r(` Downtown Nassau St at Palmer Square runs a median ${f1(S.tt_worst_stops[0].median)} min late on routes 1 and 5.`)], 2.6);
y = head(1, y + 0.1, 5, "The spread of lateness widens in the afternoon");
y = img(1, y, "fig3_hours.png", 10.4, "Weekdays in term: medians and 90th percentiles by scheduled hour. The Loop's worst tail is at 7 am and early afternoon.", 0.75);
y = para(1, y, [r(`No adverse rain effect on either service. TigerTransit: ${f1(W.tt_on_time_rain)}% on time in ${W.rain_hours} rain hours, ${f1(W.tt_on_time_dry)}% when dry. `), b("Buses run latest on the downtown blocks.")], 2.0);
y = head(1, y + 0.1, 6, "Some Loop stops are skipped far more than others");
y = img(1, y, "fig5_skips.png", 13.0, "Share of scheduled visits skipped (number of skips in brackets). Red: senior stops. Right: by scheduled hour.", 0.7);
y = para(1, y, [r(`The Loop Local skipped ${f1(sk.local_skip_rate)}% of scheduled visits. `), b(`Senior stops: ${f1(sk.local_senior_skip_rate)}% vs ${f1(sk.local_other_skip_rate)}%, mostly one stop: without the Senior Resource Ctr, ${f1(sk.senior_leave_one_out["Senior Resource"])}%.`), r("")], 2.1);

// ---------- column 3: forecast, fixes, council box
y = 6.35;
y = head(2, y, 7, "Prediction: a lookup table nearly matches ML");
y = img(2, y, "fig6b_forecast_poster.png", 10.6, "Each departure predicted 30 min ahead from data logged before then. Trained Sep 30 to Oct 31; tested Nov 1 to 15.", 0.75);
y = para(2, y, [r(`Boosted trees predict lateness 30 minutes ahead within ${m1.mae.toFixed(2)} min on average, vs ${b2.mae.toFixed(2)} for a table of past lateness. `),
  b(`Using the route network did not help: a graph network scored ${G.mae.graph.toFixed(2)} min, the same network with its stop links removed ${G.mae["no graph"].toFixed(2)}.`)], 2.4);
y = head(2, y + 0.1, 8, "Fixes, replayed on held-out weeks");
y = img(2, y, "fig7b_timetable_poster.png", COLW * 0.92, "Replay of Nov 1 to 15 (held out): real running times, early buses wait for the timetable, delays carry into the next trip. Waiting at only 4 stops per trip gives 75%.", 0.75);
y = para(2, y, [b(`Loop Local: early buses waiting on every trip lifts it from ${r0(tpl.today)}% to ${r0(tpl["today + hold"])}% (gain ${T.loop_local_gain_ci95_points["today + hold"][0]} to ${T.loop_local_gain_ci95_points["today + hold"][1]} points, 95%)`), r(` (but more run 5+ min late, ${r0(LT["today + hold"])}% vs ${r0(LT.today)}%)`), r(`; with a re-timed schedule, ${r0(tpl["re-timed + hold"])}% (about ${r0(T.trip_length["TPL|pm"].retimed_min - T.trip_length["TPL|pm"].scheduled_min)} min more per afternoon trip). Waiting on half the trips gives ${r0(tpl["today + hold (half)"])}%; re-timing without waiting, ${r0(tpl["re-timed, no hold"])}%. Waiting does not help TigerTransit, already near 88%.`)], 3.0);
const ry = y + 0.1, rh = 34.45 - ry;
s.addShape(pres.shapes.RECTANGLE, { x: COLX[2], y: ry, w: COLW, h: rh, fill: { color: DARK }, line: { color: DARK } });
s.addText("For the Council", { x: COLX[2] + 0.4, y: ry + 0.2, w: COLW - 0.8, h: 0.75, fontFace: H, fontSize: 34, bold: true, color: AMBER, margin: 0 });
const bl = (t, last) => ({ text: t, options: { bullet: { indent: 26 }, breakLine: !last } });
s.addText([
  bl("Mar to May 2027 (contract manager, WeDriveU, about 30 staff hours): 12-week trial, waiting in alternate weeks, after a contract and labour check. Success: early departures about 5% or less."),
  bl("Fall 2027 (town, WeDriveU): re-time Loop afternoons, 4 min per trip, leaving 3 of the 7 layover minutes; needs WeDriveU agreement."),
  bl("Weekly page (owner to be named): TripShot, WeDriveU and University sign-off first. Under $30/month + 1 hour/week.", true),
], { x: COLX[2] + 0.4, y: ry + 0.95, w: COLW - 0.8, h: rh - 1.1, fontFace: B, fontSize: 24, color: WHITE, margin: 0, valign: "top", paraSpaceAfter: 6 });

// ---------- footer band: limits, privacy, AI note
s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 34.6, w: 48, h: 1.4, fill: { color: SAND }, line: { color: SAND } });
s.addText([b("Code: "), r("github.com/skylerlchan/princeton-on-time (code, tests and a scrubbed three-day sample; every number here is reproducible).", { breakLine: true }),
  b("Privacy: "), r("no rider data; driver ids removed from the sample and all outputs; raw files held by the team and scrubbed after grading.  "), b("AI note: "), r("code and drafts by Claude Code; questions, rules and choices by the team.  Contact: sc8742@princeton.edu.  "),
  b("Sources: "), r("TripShot, NJ Transit, NWS, USGS, ACS 2020-24; TCQSM 2013; Zhao 2006; Cats 2012.")],
  { x: 1, y: 34.65, w: 46, h: 1.3, fontFace: B, fontSize: 24, color: INK, margin: 0, valign: "middle" });

pres.writeFile({ fileName: path.join(__dirname, "Princeton On Time - poster.pptx") }).then(f => console.log("wrote", f));
