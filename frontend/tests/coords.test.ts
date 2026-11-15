// The frontend half of the shared coordinate cases (backend: tests/test_units.py).
import { test } from "node:test";
import assert from "node:assert/strict";
import cases from "../../shared/coords_cases.json";
import { CoordinateError, checkRange, formatDecimal, formatSexagesimal, parseCoordinates } from "../src/coords";

test("parsing agrees with the backend on every shared case", () => {
  for (const c of cases.parse) {
    if (c.expect === "error") assert.throws(() => parseCoordinates(c.text), CoordinateError, c.text);
    else if (c.expect === null) assert.equal(parseCoordinates(c.text), null, c.text);
    else {
      const got = parseCoordinates(c.text);
      const want = c.expect as number[];
      assert.ok(got && Math.abs(got[0] - want[0]) < 1e-9 && Math.abs(got[1] - want[1]) < 1e-9, `${c.text}: ${got}`);
    }
  }
  assert.ok(cases.parse.length > 50);
});

test("formatting agrees with the backend on every shared case, and reads back", () => {
  for (const c of cases.format) {
    assert.equal(formatSexagesimal(c.ra, c.dec), c.sexagesimal);
    assert.equal(formatSexagesimal(c.ra, c.dec, 1, 0), c.sexagesimal_1_0);
    assert.equal(formatDecimal(c.ra, c.dec), c.decimal);
    const [ra, dec] = parseCoordinates(c.decimal)!;
    assert.ok(Math.abs(((ra - c.ra + 540) % 360) - 180) < 1e-5 && Math.abs(dec - c.dec) < 1e-5);
    const [ra2, dec2] = parseCoordinates(c.sexagesimal)!;
    assert.ok(Math.abs(((ra2 - c.ra + 540) % 360) - 180) < 1e-4 && Math.abs(dec2 - c.dec) < 1e-5, c.sexagesimal);
  }
});

test("range check", () => {
  assert.deepEqual(checkRange(359.9, -90), [359.9, -90]);
  for (const [ra, dec] of [[360, 0], [-0.1, 0], [10, 90.5], [NaN, 0]]) assert.throws(() => checkRange(ra, dec), CoordinateError);
});
