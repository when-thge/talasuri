// Sky-sphere geometry: RA/Dec <-> unit vectors, the camera pose for the inside and outside
// views, projection and picking. Pure maths with no Three.js or DOM, so the handedness
// rules (east is left from inside, mirrored from outside) are unit tested. sphere.ts drives
// the real camera, the overlays and click picking from these same functions.

export type Vec3 = readonly [number, number, number];
export type RaDec = [ra: number, dec: number];
export interface Pose { pos: Vec3; forward: Vec3; up: Vec3; right: Vec3 }
/** Half-height of the view at unit distance, and width / height. */
export interface Lens { tanHalfFov: number; aspect: number }

const RAD = Math.PI / 180;
const dot = (a: Vec3, b: Vec3) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const cross = (a: Vec3, b: Vec3): Vec3 => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const add = (a: Vec3, b: Vec3, kb = 1): Vec3 => [a[0] + kb * b[0], a[1] + kb * b[1], a[2] + kb * b[2]];
const scale = (a: Vec3, k: number): Vec3 => [a[0] * k, a[1] * k, a[2] * k];
const unit = (a: Vec3): Vec3 => scale(a, 1 / Math.hypot(a[0], a[1], a[2]));

/** Unit vector of a sky position, in the scene's right-handed frame: +Y is the north
 * celestial pole, RA 0 is along -Z and RA increases towards -X. With that choice a
 * camera at the centre with north up has east on its left, as the real sky does. */
export function radecToVec(ra: number, dec: number): Vec3 {
  const a = ra * RAD, d = dec * RAD;
  return [-Math.cos(d) * Math.sin(a), Math.sin(d), -Math.cos(d) * Math.cos(a)];
}

export function vecToRadec(v: Vec3): RaDec {
  const r = Math.hypot(v[0], v[1], v[2]);
  const ra = Math.atan2(-v[0], -v[2]) / RAD;
  return [((ra % 360) + 360) % 360, Math.asin(Math.max(-1, Math.min(1, v[1] / r))) / RAD];
}

/** Unit tangent towards the north pole at (ra, dec); defined at the poles too. */
export function northAt(ra: number, dec: number): Vec3 {
  const a = ra * RAD, d = dec * RAD;
  return [Math.sin(d) * Math.sin(a), Math.cos(d), Math.sin(d) * Math.cos(a)];
}

/** Unit tangent towards increasing RA (east) at right ascension `ra`. */
export function eastAt(ra: number): Vec3 {
  const a = ra * RAD;
  return [-Math.cos(a), 0, Math.sin(a)];
}

/** Camera pose centred on (ra, dec), north up.
 *  t = 0: inside view. The camera sits at the centre of the sphere and looks out at the
 *         target, so east is to the left.
 *  t = 1: outside view. The camera sits `distance` radii out, above the target, and looks
 *         back at the centre: the sky is a globe and appears mirror-reversed (east right).
 *  In between, the camera backs out along the target direction while turning half a turn
 *  about the north axis, which is the animated transition between the two. */
export function cameraPose(t: number, ra: number, dec: number, distance: number): Pose {
  const v = radecToVec(ra, dec), up = northAt(ra, dec), east = eastAt(ra);
  const turn = Math.PI * t;
  const forward = unit(add(scale(v, Math.cos(turn)), east, Math.sin(turn)));
  return { pos: scale(v, distance * t), forward, up, right: cross(forward, up) };
}

/** Screen position of a point in normalised device coordinates (x right, y up, both
 * -1..1 inside the view); null if it is behind the camera. */
export function project(pose: Pose, p: Vec3, lens: Lens): [x: number, y: number] | null {
  const d = add(p, pose.pos, -1);
  const z = dot(d, pose.forward);
  if (z <= 1e-9) return null;
  return [dot(d, pose.right) / (z * lens.tanHalfFov * lens.aspect), dot(d, pose.up) / (z * lens.tanHalfFov)];
}

/** Is a point of the unit sphere facing the camera (not on the far side of the globe)? */
export function facesCamera(pose: Pose, p: Vec3): boolean {
  const r2 = dot(pose.pos, pose.pos);
  return r2 <= 1 ? true : dot(p, pose.pos) > 1;   // beyond the horizon cone when outside
}

/** Screen position of a sky position, or null when it cannot be seen. */
export function radecToScreen(pose: Pose, ra: number, dec: number, lens: Lens): [number, number] | null {
  const p = radecToVec(ra, dec);
  return facesCamera(pose, p) ? project(pose, p, lens) : null;
}

/** The sky position under a screen point (NDC), or null if the ray misses the sphere.
 * The ray is intersected with the unit sphere and the nearest hit in front of the camera
 * is used: from inside that is the sky itself, from outside the near face of the globe.
 * No sign flip is needed for the mirrored view; the geometry takes care of it. */
export function screenToRadec(pose: Pose, x: number, y: number, lens: Lens): RaDec | null {
  const dir = unit(add(add(pose.forward, pose.right, x * lens.tanHalfFov * lens.aspect), pose.up, y * lens.tanHalfFov));
  const b = dot(pose.pos, dir), c = dot(pose.pos, pose.pos) - 1;
  const disc = b * b - c;
  if (disc < 0) return null;
  const root = Math.sqrt(disc);
  const s = -b - root > 1e-9 ? -b - root : -b + root;
  if (s <= 1e-9) return null;
  return vecToRadec(add(pose.pos, dir, s));
}

/** Great-circle interpolation between two sky positions (for smooth slews). */
export function slerpRadec(a: RaDec, b: RaDec, t: number): RaDec {
  const va = radecToVec(...a), vb = radecToVec(...b);
  const omega = separation(a, b) * RAD;
  if (omega < 1e-9) return [...b];
  if (Math.PI - omega < 1e-6) {             // antipodes: go over the pole side, via RA/Dec
    return [a[0] + (((b[0] - a[0] + 540) % 360) - 180) * t, a[1] + (b[1] - a[1]) * t];
  }
  const ka = Math.sin((1 - t) * omega) / Math.sin(omega), kb = Math.sin(t * omega) / Math.sin(omega);
  return vecToRadec(add(scale(va, ka), vb, kb));
}

/** Angular separation in degrees (atan2 form: accurate for tiny and near-180 angles). */
export function separation(a: RaDec, b: RaDec): number {
  const va = radecToVec(...a), vb = radecToVec(...b), c = cross(va, vb);
  return Math.atan2(Math.hypot(c[0], c[1], c[2]), dot(va, vb)) / RAD;
}

/** `n` + 1 points around the great circle whose pole is (poleRa, poleDec). */
export function greatCircle(poleRa: number, poleDec: number, n = 180): RaDec[] {
  const pole = radecToVec(poleRa, poleDec);
  const u = unit(cross(pole, Math.abs(pole[1]) < 0.9 ? [0, 1, 0] : [1, 0, 0]));
  const w = cross(pole, u);
  return Array.from({ length: n + 1 }, (_, i) => {
    const th = (2 * Math.PI * i) / n;
    return vecToRadec(add(scale(u, Math.cos(th)), w, Math.sin(th)));
  });
}

/** North poles (ICRS) of the two planes drawn as overlays. */
export const ECLIPTIC_POLE: RaDec = [270.0, 66.560709];
export const GALACTIC_POLE: RaDec = [192.85948, 27.12825];

/** Texture coordinate of a sky position on the all-sky CAR image (RA 0 at the centre,
 * RA increasing to the left, north at v = 1). u is continuous in RA: the texture repeats. */
export function radecToUv(ra: number, dec: number): [number, number] {
  return [0.5 - ra / 360, (dec + 90) / 180];
}
