// URL state round-trip tests (run with `npm test`).
import { test } from "node:test";
import assert from "node:assert/strict";
import { DEFAULTS, KEYS, SCHEMA, fromHash, sameState, toHash, type ViewState } from "../src/state";

test("defaults round-trip", () => {
  const { state, errors } = fromHash(toHash(DEFAULTS));
  assert.deepEqual(errors, []);
  assert.ok(sameState(state, DEFAULTS));
});

test("fully customised state round-trips exactly", () => {
  const s: ViewState = {
    ...DEFAULTS, view: "sphere", sphere: "outside", slayer: "spherex", sgrid: false, secl: true, sgal: true,
    pra: 83.82, pdec: -5.39, ra: 133.79513, dec: -7.24515, name: "WISE 0855-0714", fov: 7.5, rel: "dr1", deep: true,
    pm: true, pmra: -8123.7, pmdec: 673.2, pmep: 2000, mode: "epoch", win: 180, dets: [5, 6],
    lmin: 3.1, lmax: 5, t0: 60800.5, t1: 61300, diff: "ref", ref: 2, speed: 250, stretch: "log",
    vmin: -0.0123456, vmax: 1.5e3, inv: true, zoom: 6, flag: "mask", fbits: ["HOT", "OUTLIER"],
    frame: 17, xhair: false, gaia: true, catwise: true, hips: "2mass", rgb: [5, 3, 1], ap: 2.5,
    lcmin: 4.4, lcmax: 5,
  };
  const h = toHash(s);
  const { state, errors } = fromHash("#" + h);
  assert.deepEqual(errors, []);
  assert.ok(sameState(state, s), `mismatch:\n${JSON.stringify(state)}\n${JSON.stringify(s)}`);
  assert.equal(toHash(state), h, "serialisation is stable");
});

test("random states round-trip", () => {
  let seed = 42;
  const rnd = () => ((seed = (seed * 1103515245 + 12345) % 2 ** 31) / 2 ** 31);
  const pick = <T>(xs: T[]) => xs[Math.floor(rnd() * xs.length)];
  for (let i = 0; i < 200; i++) {
    const s: ViewState = {
      ...DEFAULTS, ra: Number((rnd() * 360).toFixed(6)), dec: Number((rnd() * 180 - 90).toFixed(6)),
      fov: pick([1, 2.5, 5, 30]), mode: pick(["frames", "detector", "epoch", "wave", "rgb"] as const),
      diff: pick(["none", "median", "ref"] as const), stretch: pick(["linear", "asinh", "log", "sqrt"] as const),
      dets: [1, 2, 3, 4, 5, 6].filter(() => rnd() > 0.5), lmin: rnd() > 0.5 ? null : Number((rnd() * 5).toFixed(3)),
      inv: rnd() > 0.5, speed: Math.round(rnd() * 2000), name: pick(["", "eps Indi B", "Barnard's Star", "a&b=c#d"]),
    };
    const { state } = fromHash(toHash(s));
    assert.ok(sameState(state, s), JSON.stringify(s));
  }
});

test("parses the brief's example URL (WiseView-style)", () => {
  const { state, errors } = fromHash("#ra=133.79513&dec=-7.24515&fov=5&mode=epoch&speed=500&stretch=asinh&diff=0&gaia=1");
  assert.deepEqual(errors, []);
  assert.equal(state.ra, 133.79513);
  assert.equal(state.dec, -7.24515);
  assert.equal(state.mode, "epoch");
  assert.equal(state.diff, "none");
  assert.equal(state.gaia, true);
  assert.equal(fromHash("#diff=1").state.diff, "median");
});

test("invalid values fall back to defaults and are reported", () => {
  const { state, errors } = fromHash("#ra=abc&mode=bogus&fov=3&unknown=1");
  assert.equal(state.ra, null);
  assert.equal(state.mode, "epoch");
  assert.equal(state.fov, 3);
  assert.equal(errors.length, 2);
});

test("the schema is the single definition: every key has a default and round-trips alone", () => {
  assert.deepEqual(KEYS, Object.keys(SCHEMA));
  for (const k of KEYS) {
    const p = SCHEMA[k] as { default: unknown; encode(v: unknown): string | null; decode(r: string): unknown };
    assert.deepEqual(DEFAULTS[k], p.default);
    const enc = p.encode(p.default);
    if (enc !== null) assert.deepEqual(p.decode(enc), p.default, k);
  }
});

test("view and sphere parameters", () => {
  assert.equal(DEFAULTS.view, "flipbook");
  assert.equal(DEFAULTS.sphere, "inside");
  assert.equal(DEFAULTS.map, "sphere");
  assert.equal(fromHash("#map=aladin").state.map, "aladin");
  const { state, errors } = fromHash("#view=sphere&sphere=outside&pra=10.5&pdec=-20");
  assert.deepEqual(errors, []);
  assert.deepEqual([state.view, state.sphere, state.pra, state.pdec], ["sphere", "outside", 10.5, -20]);
  assert.match(toHash(state), /view=sphere&sphere=outside/);
  assert.doesNotMatch(toHash(DEFAULTS), /view=|sphere=/);          // defaults stay out of the URL
  const bad = fromHash("#view=globe&sphere=upside-down");
  assert.equal(bad.errors.length, 2);
  assert.deepEqual([bad.state.view, bad.state.sphere], ["flipbook", "inside"]);
  // older links: tab=basic|adv still select the tab, tab=about (now the Help dialog) opens Basic
  const legacy = fromHash("#tab=adv&ra=10&dec=20&size=7&invert=1");
  assert.deepEqual(legacy.errors, []);
  assert.deepEqual([legacy.state.tab, legacy.state.ra, legacy.state.fov, legacy.state.inv], ["adv", 10, 7, true]);
  assert.equal(DEFAULTS.tab, "basic");
  assert.equal(fromHash("#tab=about").state.tab, "basic");
  // the Movers tab and the WISE motion prediction are part of the shared link
  const mv = fromHash("#tab=movers&wfit=1");
  assert.deepEqual([mv.state.tab, mv.state.wfit, mv.errors.length], ["movers", true, 0]);
  assert.equal(DEFAULTS.wfit, false);
  assert.ok(toHash({ ...DEFAULTS, wfit: true }).includes("wfit=1") && !toHash(DEFAULTS).includes("wfit"));
});
