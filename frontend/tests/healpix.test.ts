// HEALPix / HiPS tile addressing against astropy-healpix reference values
// (tests/healpix_cases.json: order, ra, dec, pixel, pixel centre, and the point dx=.25 dy=.75).
import { test } from "node:test";
import assert from "node:assert/strict";
import rawCases from "./healpix_cases.json";
import { FACE_DEG, orderFor, pixToXyf, radecToPix, tilePath, tileToRadec, tileUv } from "../src/healpix";
import { separation } from "../src/sphere-math";

type Case = [order: number, ra: number, dec: number, ipix: number, lon: number, lat: number, qlon: number, qlat: number];
const cases = rawCases as Case[];

test("radecToPix matches astropy-healpix (nested)", () => {
  for (const [order, ra, dec, ipix] of cases) assert.equal(radecToPix(order, ra, dec), ipix, `order ${order} at ${ra}, ${dec}`);
});

test("tileToRadec gives the pixel centre and interior points", () => {
  for (const [order, , , ipix, lon, lat, qlon, qlat] of cases) {
    const tol = (FACE_DEG / 2 ** order) * 1e-9 + 1e-10;
    assert.ok(separation(tileToRadec(order, ipix, 0.5, 0.5), [lon, lat]) < tol, `centre, order ${order} pixel ${ipix}`);
    assert.ok(separation(tileToRadec(order, ipix, 0.25, 0.75), [qlon, qlat]) < tol, `offset, order ${order} pixel ${ipix}`);
  }
});

test("a position maps back into its own tile", () => {
  for (const [order, , , ipix] of cases)
    for (const [fx, fy] of [[0.01, 0.01], [0.99, 0.01], [0.01, 0.99], [0.99, 0.99], [0.5, 0.5]])
      assert.equal(radecToPix(order, ...tileToRadec(order, ipix, fx, fy)), ipix);
});

test("children tile their parent: pixel >> 2 is the parent, x and y split in halves", () => {
  for (const [order, ra, dec, ipix] of cases) {
    if (order === 0) continue;
    assert.equal(radecToPix(order - 1, ra, dec), Math.floor(ipix / 4));
    const c = pixToXyf(order, ipix), p = pixToXyf(order - 1, Math.floor(ipix / 4));
    assert.deepEqual([c.face, c.ix >> 1, c.iy >> 1], [p.face, p.ix, p.iy]);
  }
});

test("tile image orientation: y along columns, x down rows", () => {
  assert.deepEqual(tileUv(0, 0), [0, 1]);      // top-left of the image
  assert.deepEqual(tileUv(1, 0), [0, 0]);      // x runs down
  assert.deepEqual(tileUv(0, 1), [1, 1]);      // y runs right
});

test("tile paths and the order needed for a given screen scale", () => {
  assert.equal(tilePath(5, 1000), "Norder5/Dir0/Npix1000");
  assert.equal(tilePath(9, 2731234), "Norder9/Dir2730000/Npix2731234");
  assert.equal(orderFor(FACE_DEG / 512), 0);
  assert.equal(orderFor(FACE_DEG / 512 / 8), 3);
  assert.equal(orderFor(FACE_DEG / 512 / 9), 4);    // sharper than order 3 can show
});
