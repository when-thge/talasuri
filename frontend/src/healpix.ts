// HEALPix (nested scheme) and HiPS tile addressing, for the Sky Sphere's detail tiles.
// Pure maths with no Three.js or DOM; unit tested against astropy-healpix reference values.
//
// A HiPS tile of order k is HEALPix pixel `ipix` of nside 2^k. Inside its base face the
// tile is the square [ix, ix+1] x [iy, iy+1] (in units of 1/nside), and its image stores
// the face's y axis along image columns and the x axis down image rows.

const HALF_PI = Math.PI / 2;
const JRLL = [2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4];
const JPLL = [1, 3, 5, 7, 0, 2, 4, 6, 1, 3, 5, 7];

/** Angular size of a base face, degrees: sqrt(4 pi / 12). A tile of order k is this / 2^k. */
export const FACE_DEG = (Math.sqrt(Math.PI / 3) * 180) / Math.PI;

function spread(v: number): number {          // abc -> 0a0b0c (v < 2^15)
  let r = 0;
  for (let b = 0; b < 15; b++) r += ((v >> b) & 1) * 4 ** b;
  return r;
}
function compress(v: number): number {        // every second bit of v, starting at bit 0
  let r = 0;
  for (let b = 0; b < 15; b++) r |= (Math.floor(v / 4 ** b) & 1) << b;
  return r;
}

/** Nested pixel -> base face and integer position inside it. */
export function pixToXyf(order: number, ipix: number): { face: number; ix: number; iy: number } {
  const npface = 4 ** order, inner = ipix % npface;
  return { face: Math.floor(ipix / npface), ix: compress(inner), iy: compress(Math.floor(inner / 2)) };
}

/** Sky position (degrees) of the point (x, y) of a base face, x and y in 0..1. */
export function faceToRadec(face: number, x: number, y: number): [ra: number, dec: number] {
  const jr = JRLL[face] - x - y;
  let nr: number, z: number;
  if (jr < 1) { nr = jr; z = 1 - (nr * nr) / 3; }
  else if (jr > 3) { nr = 4 - jr; z = (nr * nr) / 3 - 1; }
  else { nr = 1; z = ((2 - jr) * 2) / 3; }
  let tmp = JPLL[face] * nr + x - y;
  if (tmp < 0) tmp += 8;
  if (tmp >= 8) tmp -= 8;
  const phi = nr < 1e-15 ? 0 : (0.5 * HALF_PI * tmp) / nr;
  return [(phi * 180) / Math.PI, (Math.asin(Math.max(-1, Math.min(1, z))) * 180) / Math.PI];
}

/** Sky position of the point (fx, fy), each 0..1, inside tile `ipix` of `order`.
 * (0.5, 0.5) is the pixel centre. In the tile image, fy runs left to right and fx top to
 * bottom (see tileUv). */
export function tileToRadec(order: number, ipix: number, fx: number, fy: number): [number, number] {
  const { face, ix, iy } = pixToXyf(order, ipix), nside = 2 ** order;
  return faceToRadec(face, (ix + fx) / nside, (iy + fy) / nside);
}

/** Texture coordinate (u right, v up, as WebGL has it for an image stored top row first
 * and flipped on upload) of the point (fx, fy) of a tile. */
export function tileUv(fx: number, fy: number): [number, number] {
  return [fy, 1 - fx];
}

/** Nested pixel of `order` containing a sky position (degrees). */
export function radecToPix(order: number, ra: number, dec: number): number {
  const nside = 2 ** order;
  const z = Math.sin((dec * Math.PI) / 180), za = Math.abs(z);
  const tt = ((((ra / 90) % 4) + 4) % 4);                 // 0..4
  let face: number, ix: number, iy: number;
  if (za <= 2 / 3) {
    const t1 = nside * (0.5 + tt), t2 = nside * z * 0.75;
    const jp = Math.floor(t1 - t2), jm = Math.floor(t1 + t2);
    const ifp = Math.floor(jp / nside), ifm = Math.floor(jm / nside);
    face = ifp === ifm ? (ifp & 3) | 4 : ifp < ifm ? ifp & 3 : (ifm & 3) + 8;
    ix = jm & (nside - 1);
    iy = nside - (jp & (nside - 1)) - 1;
  } else {
    const ntt = Math.min(3, Math.floor(tt)), tp = tt - ntt;
    // sqrt(3 (1 - |z|)) from cos(dec), which keeps precision next to the poles
    const c = Math.cos((dec * Math.PI) / 180);
    const tmp = nside * (c / Math.sqrt((1 + za) / 3));
    const jp = Math.min(nside - 1, Math.floor(tp * tmp)), jm = Math.min(nside - 1, Math.floor((1 - tp) * tmp));
    if (z >= 0) { face = ntt; ix = nside - jm - 1; iy = nside - jp - 1; }
    else { face = ntt + 8; ix = jp; iy = jm; }
  }
  return face * nside * nside + spread(ix) + 2 * spread(iy);
}

/** Path of a tile below a HiPS root, e.g. "Norder5/Dir0/Npix1000". */
export function tilePath(order: number, ipix: number): string {
  return `Norder${order}/Dir${Math.floor(ipix / 10000) * 10000}/Npix${ipix}`;
}

/** The HiPS order whose tiles (of `tileWidth` pixels) are at least as sharp as the screen,
 * which shows `degPerPx` degrees of sky per pixel. May be negative for very wide views. */
export function orderFor(degPerPx: number, tileWidth = 512): number {
  return Math.ceil(Math.log2(FACE_DEG / tileWidth / degPerPx));
}
