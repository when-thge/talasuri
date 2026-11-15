// Sky-sphere geometry tests (run with `npm test`).
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  ECLIPTIC_POLE, GALACTIC_POLE, cameraPose, eastAt, greatCircle, northAt, radecToScreen, radecToUv,
  radecToVec, screenToRadec, separation, slerpRadec, vecToRadec, type Lens, type RaDec,
} from "../src/sphere-math";

const LENS: Lens = { tanHalfFov: Math.tan((35 * Math.PI) / 180), aspect: 16 / 9 };
const INSIDE = 0, OUTSIDE = 1, DIST = 2.6;
const close = (a: number, b: number, tol = 1e-9) => Math.abs(a - b) <= tol;
const sameSky = (a: RaDec, b: RaDec, tol = 1e-7) => separation(a, b) <= tol;

let seed = 7;
const rnd = () => ((seed = (seed * 1103515245 + 12345) % 2 ** 31) / 2 ** 31);
const randomSky = (): RaDec => [rnd() * 360, (Math.asin(2 * rnd() - 1) * 180) / Math.PI];

test("RA/Dec -> vector -> RA/Dec round-trips over the whole sky", () => {
  for (let i = 0; i < 2000; i++) {
    const p = randomSky();
    const v = radecToVec(...p);
    assert.ok(close(Math.hypot(...v), 1));
    assert.ok(sameSky(vecToRadec(v), p), `${p}`);
  }
  for (const p of [[0, 0], [359.999, 0], [180, 0], [90, 45], [270, -45], [12.3, 89.999], [200, -89.999]] as RaDec[]) {
    const [ra, dec] = vecToRadec(radecToVec(...p));
    assert.ok(close(dec, p[1], 1e-9) && close(((ra - p[0] + 540) % 360) - 180, 0, 1e-6), `${p}`);
  }
  assert.ok(close(vecToRadec(radecToVec(0, 90))[1], 90) && close(vecToRadec(radecToVec(0, -90))[1], -90));
});

test("the scene frame is right-handed: north = +Y, east x north = outward (away from the centre)", () => {
  assert.deepEqual(radecToVec(0, 90).map((x) => Math.round(x * 1e9) / 1e9 + 0), [0, 1, 0]);
  const ra = 40, dec = 25;
  const v = radecToVec(ra, dec), n = northAt(ra, dec), e = eastAt(ra);
  const cross = [e[1] * n[2] - e[2] * n[1], e[2] * n[0] - e[0] * n[2], e[0] * n[1] - e[1] * n[0]];
  cross.forEach((c, i) => assert.ok(close(c, v[i], 1e-12)));
  // The tangents really are the directions of increasing Dec and RA.
  const dv = radecToVec(ra, dec + 1e-4), de = radecToVec(ra + 1e-4, dec);
  assert.ok(n.reduce((s, c, i) => s + c * (dv[i] - v[i]), 0) > 0);
  assert.ok(e.reduce((s, c, i) => s + c * (de[i] - v[i]), 0) > 0);
});

test("inside view: target at the centre, north up, east to the LEFT", () => {
  for (let i = 0; i < 300; i++) {
    const [ra, dec] = [rnd() * 360, rnd() * 160 - 80];
    const pose = cameraPose(INSIDE, ra, dec, DIST);
    assert.deepEqual(pose.pos.map((x) => x + 0), [0, 0, 0]);           // camera at the centre
    const c = radecToScreen(pose, ra, dec, LENS)!;
    assert.ok(close(c[0], 0, 1e-9) && close(c[1], 0, 1e-9));
    const east = radecToScreen(pose, ra + 1 / Math.cos((dec * Math.PI) / 180), dec, LENS)!;
    const north = radecToScreen(pose, ra, dec + 1, LENS)!;
    assert.ok(east[0] < -1e-4, `east must be left (x<0), got ${east[0]} at ${ra},${dec}`);
    assert.ok(Math.abs(east[1]) < Math.abs(east[0]));
    assert.ok(north[1] > 1e-4 && close(north[0], 0, 1e-9), "north must be up");
  }
});

test("outside view: target at the centre, north up, east to the RIGHT (mirrored)", () => {
  for (let i = 0; i < 300; i++) {
    const [ra, dec] = [rnd() * 360, rnd() * 160 - 80];
    const pose = cameraPose(OUTSIDE, ra, dec, DIST);
    assert.ok(close(Math.hypot(...pose.pos), DIST));                   // camera outside the sphere
    const c = radecToScreen(pose, ra, dec, LENS)!;
    assert.ok(close(c[0], 0, 1e-9) && close(c[1], 0, 1e-9));
    const east = radecToScreen(pose, ra + 1 / Math.cos((dec * Math.PI) / 180), dec, LENS)!;
    const north = radecToScreen(pose, ra, dec + 1, LENS)!;
    assert.ok(east[0] > 1e-4, `east must be right (x>0) from outside, got ${east[0]}`);
    assert.ok(north[1] > 1e-4, "north is still up");
    // the far side of the globe is hidden
    assert.equal(radecToScreen(pose, ra + 180, -dec, LENS), null);
  }
});

test("screen -> RA/Dec inverts RA/Dec -> screen in both modes (click picking)", () => {
  for (const mode of [INSIDE, OUTSIDE]) {
    let n = 0;
    for (let i = 0; i < 4000; i++) {
      const centre = randomSky(), p = randomSky();
      const pose = cameraPose(mode, centre[0], centre[1], DIST);
      const s = radecToScreen(pose, p[0], p[1], LENS);
      if (!s || Math.abs(s[0]) > 1 || Math.abs(s[1]) > 1) continue;     // not on screen
      const back = screenToRadec(pose, s[0], s[1], LENS);
      assert.ok(back && sameSky(back, p, 1e-6), `mode ${mode}: ${p} -> ${s} -> ${back}`);
      n++;
    }
    assert.ok(n > 150, `only ${n} on-screen samples in mode ${mode}`);
  }
});

test("picking: centre click returns the view centre; outside misses return null", () => {
  for (const mode of [INSIDE, OUTSIDE]) {
    const pose = cameraPose(mode, 83.82, -5.39, DIST);
    assert.ok(sameSky(screenToRadec(pose, 0, 0, LENS)!, [83.82, -5.39], 1e-9));
  }
  const out = cameraPose(OUTSIDE, 10, 20, DIST);
  assert.equal(screenToRadec(out, 0.99, 0.99, LENS), null);             // beside the globe
  assert.notEqual(screenToRadec(cameraPose(INSIDE, 10, 20, DIST), 0.99, 0.99, LENS), null);
  // A click left of centre is east from inside and west from outside.
  const dRa = (p: RaDec) => ((p[0] - 10 + 540) % 360) - 180;
  assert.ok(dRa(screenToRadec(cameraPose(INSIDE, 10, 20, DIST), -0.2, 0, LENS)!) > 0);
  assert.ok(dRa(screenToRadec(out, -0.2, 0, LENS)!) < 0);
});

test("the mode transition is continuous and ends exactly at the two views", () => {
  let prev = cameraPose(0, 120, 30, DIST);
  for (let k = 1; k <= 100; k++) {
    const p = cameraPose(k / 100, 120, 30, DIST);
    assert.ok(Math.hypot(...p.pos.map((x, i) => x - prev.pos[i])) < 0.05);
    assert.ok(p.forward.reduce((s, c, i) => s + c * prev.forward[i], 0) > 0.99);
    assert.ok(close(Math.hypot(...p.forward), 1) && close(Math.hypot(...p.right), 1));
    prev = p;
  }
  const a = cameraPose(0, 120, 30, DIST), b = cameraPose(1, 120, 30, DIST);
  a.forward.forEach((c, i) => assert.ok(close(c, -b.forward[i], 1e-12)));
  a.right.forEach((c, i) => assert.ok(close(c, -b.right[i], 1e-12)));   // the mirror
});

test("slews follow the great circle; overlay planes pass through known points", () => {
  const a: RaDec = [10, 20], b: RaDec = [200, -40];
  assert.ok(sameSky(slerpRadec(a, b, 0), a) && sameSky(slerpRadec(a, b, 1), b));
  const mid = slerpRadec(a, b, 0.5);
  assert.ok(close(separation(a, mid), separation(mid, b), 1e-9));
  assert.ok(close(separation(a, mid) + separation(mid, b), separation(a, b), 1e-9));
  // ecliptic: through the equinoxes, 23.44 deg from the equator at RA 90
  const ecl = greatCircle(...ECLIPTIC_POLE, 720);
  assert.ok(ecl.some((p) => separation(p, [0, 0]) < 0.5) && ecl.some((p) => separation(p, [90, 23.439]) < 0.5));
  ecl.forEach((p) => assert.ok(close(separation(p, ECLIPTIC_POLE), 90, 1e-9)));
  // galactic plane: through the Galactic centre (Sgr A*)
  assert.ok(greatCircle(...GALACTIC_POLE, 720).some((p) => separation(p, [266.405, -28.936]) < 0.5));
});

test("texture mapping: RA 0 at the image centre, RA increasing to the left, north on top", () => {
  assert.deepEqual(radecToUv(0, 0), [0.5, 0.5]);
  assert.ok(radecToUv(90, 0)[0] < radecToUv(0, 0)[0]);
  assert.equal(radecToUv(0, 90)[1], 1);
  assert.ok(close(radecToUv(360, 0)[0] - radecToUv(0, 0)[0], -1));       // one full wrap
});
