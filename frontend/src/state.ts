// URL state. SCHEMA is the single definition of every parameter: its name, type, default,
// and how it is written to and read from the URL hash. Everything else (ViewState, DEFAULTS,
// toHash, fromHash) is derived from it, and hashStore is the only code that touches
// location.hash. No DOM access at import time, so the module is unit tested under Node.
import skyConfig from "../sky.config.json";

/** One URL parameter: its default and its (de)serialisation. */
export interface Param<T> {
  default: T;
  /** Value -> text for the URL; null leaves the key out. */
  encode(v: T): string | null;
  /** Text from the URL -> value; throws on invalid input (the default is then used). */
  decode(raw: string): T;
  /** Written even when equal to the default, so a URL keeps its meaning if defaults change. */
  core?: boolean;
  /** Other names accepted when reading (WiseView-style links). */
  aliases?: string[];
}

// Up to 7 decimals (~0.4 mas in Dec), no trailing zeros, no exponent for normal values.
const fmtNum = (x: number) => String(Number(x.toFixed(7)));
const toNum = (raw: string) => {
  const x = Number(raw);
  if (raw.trim() === "" || !Number.isFinite(x)) throw new Error(`not a number: ${raw}`);
  return x;
};
const toInt = (raw: string) => {
  const x = Number(raw);
  if (raw.trim() === "" || !Number.isInteger(x)) throw new Error(`not an integer: ${raw}`);
  return x;
};
type Extra = { core?: boolean; aliases?: string[] };

const num = (d: number, x: Extra = {}): Param<number> => ({ default: d, encode: fmtNum, decode: toNum, ...x });
const int = (d: number, x: Extra = {}): Param<number> => ({ default: d, encode: fmtNum, decode: toInt, ...x });
const optNum = (x: Extra = {}): Param<number | null> => ({
  default: null, encode: (v) => (v === null ? null : fmtNum(v)), decode: (r) => (r === "" ? null : toNum(r)), ...x });
const bool = (d: boolean, x: Extra = {}): Param<boolean> => ({
  default: d, encode: (v) => (v ? "1" : "0"), decode: (r) => r === "1" || r === "true", ...x });
const str = (d: string): Param<string> => ({ default: d, encode: (v) => v || null, decode: (r) => r });
const ints = (d: number[]): Param<number[]> => ({
  default: d, encode: (v) => v.join(","), decode: (r) => (r === "" ? [] : r.split(",").map(toInt)) });
const strs = (d: string[]): Param<string[]> => ({
  default: d, encode: (v) => v.join(","), decode: (r) => (r === "" ? [] : r.split(",")) });
function oneOf<const C extends readonly string[]>(choices: C, d: C[number], x: Extra & { legacy?: Record<string, C[number]> } = {}): Param<C[number]> & { choices: C } {
  return {
    default: d, choices, encode: (v) => v, core: x.core, aliases: x.aliases,
    decode: (r) => {
      const v = x.legacy?.[r] ?? r;
      if (!choices.includes(v)) throw new Error(`invalid value: ${r}`);
      return v as C[number];
    },
  };
}

export const SKY_LAYERS = skyConfig.layers.map((l) => l.id);

export const SCHEMA = {
  // Basic (flipbook + sky map), Advanced (controls | viewport | telemetry) or Movers
  // (flipbook | candidate moving sources in the field)
  tab: oneOf(["basic", "adv", "movers"], "basic", { legacy: { about: "basic" } }),
  // which view is open, and how the sky sphere is seen
  view: oneOf(["flipbook", "sphere", "aladin"], "flipbook"),
  sphere: oneOf(["inside", "outside"], "inside"),
  map: oneOf(["sphere", "aladin"], "sphere"),   // the sky map shown beside the flipbook in Basic
  // target and data
  ra: optNum({ core: true }),          // deg, ICRS
  dec: optNum({ core: true }),
  name: str(""),                       // object name as typed (informational)
  fov: num(5, { core: true, aliases: ["size"] }),   // arcmin
  rel: str("all"),                     // release id or "all"
  deep: bool(false),
  pm: bool(false),                     // track proper motion
  pmra: num(0),                        // mas/yr (includes cos dec)
  pmdec: num(0),
  pmep: num(2000),                     // Julian epoch of ra/dec
  wfit: bool(false),                   // predict the position from a fit to WISE epochs
  // what the flipbook shows
  // Default: one stack per visit (60 day window). Stacks are several times less noisy than
  // single exposures and each visit becomes one frame, which is what shows motion best.
  mode: oneOf(["frames", "detector", "epoch", "wave", "rgb"], "epoch", { core: true }),
  win: num(60, { core: true }),        // epoch window, days
  dets: ints([]),                      // detector filter ([] = all)
  lmin: optNum(),                      // wavelength filter, um
  lmax: optNum(),
  t0: optNum(),                        // MJD range filter
  t1: optNum(),
  // diff=0/1 (WiseView style) is also accepted, as none/median
  diff: oneOf(["none", "median", "ref"], "none", { core: true, legacy: { "0": "none", "1": "median" } }),
  ref: int(0),                         // reference product index for diff=ref
  speed: int(500, { core: true }),     // ms per frame
  stretch: oneOf(["linear", "asinh", "log", "sqrt"], "asinh", { core: true }),
  vmin: optNum(),                      // null = auto
  vmax: optNum(),
  // dark sources on a white sky by default (as WiseView shows them); always written to the URL
  inv: bool(true, { core: true, aliases: ["invert"] }),
  zoom: num(1),                        // magnification; 1 = image fits its box
  flag: oneOf(["off", "overlay", "mask"], "off"),
  fbits: strs([]),                     // flag names to overlay/mask ([] = default bad set)
  frame: int(0),
  xhair: bool(true),
  // overlays
  gaia: bool(false),
  catwise: bool(false),
  hips: oneOf(["none", "spherex", "unwise", "2mass", "dss"], "spherex"),   // Aladin imagery
  rgb: ints([6, 4, 2]),                // detectors for R,G,B
  ap: num(2),                          // aperture radius, native px
  lcmin: optNum(),                     // light-curve wavelength range, um
  lcmax: optNum(),
  // sky sphere: texture layer, line overlays, and a clicked position not yet loaded
  slayer: oneOf(SKY_LAYERS, skyConfig.default),
  sgrid: bool(true),
  secl: bool(false),
  sgal: bool(false),
  pra: optNum(),
  pdec: optNum(),
} satisfies Record<string, Param<never> | Param<unknown>>;

export type ViewState = { -readonly [K in keyof typeof SCHEMA]: (typeof SCHEMA)[K]["default"] };
export type Mode = ViewState["mode"];
export type Diff = ViewState["diff"];
export type View = ViewState["view"];
export type Tab = ViewState["tab"];
export type SphereMode = ViewState["sphere"];
export type Hips = ViewState["hips"];

// Stable key order so URLs are deterministic and diffable.
export const KEYS = Object.keys(SCHEMA) as (keyof ViewState)[];
const param = (k: keyof ViewState) => SCHEMA[k] as unknown as Param<unknown>;
export const DEFAULTS = Object.fromEntries(KEYS.map((k) => [k, param(k).default])) as ViewState;
const ALIASES: Record<string, keyof ViewState> = Object.fromEntries(
  KEYS.flatMap((k) => (param(k).aliases ?? []).map((a) => [a, k])));
const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

/** Serialise to "k=v&k=v" (without '#'). Defaults are left out, except the core keys. */
export function toHash(s: ViewState): string {
  const parts: string[] = [];
  for (const k of KEYS) {
    const p = param(k);
    const enc = p.encode(s[k]);
    if (enc === null || (same(s[k], p.default) && !p.core)) continue;
    parts.push(`${k}=${encodeURIComponent(enc).replace(/%2C/g, ",")}`);
  }
  return parts.join("&");
}

/** Parse a hash ("#a=1&b=2" or "a=1&b=2"). Unknown keys are ignored; invalid values fall
 * back to defaults and are reported in ``errors``. */
export function fromHash(hash: string): { state: ViewState; errors: string[] } {
  const state: ViewState = structuredClone(DEFAULTS);
  const errors: string[] = [];
  for (const part of hash.replace(/^#/, "").split("&")) {
    if (!part) continue;
    const eq = part.indexOf("=");
    const name = decodeURIComponent(eq < 0 ? part : part.slice(0, eq));
    const raw = eq < 0 ? "1" : decodeURIComponent(part.slice(eq + 1).replace(/\+/g, " "));
    const k = ALIASES[name] ?? (name as keyof ViewState);
    if (!Object.hasOwn(SCHEMA, k)) continue;
    try {
      (state as Record<string, unknown>)[k] = param(k).decode(raw);
    } catch (e) {
      errors.push(`${name}: ${(e as Error).message}`);
    }
  }
  return { state, errors };
}

export function sameState(a: ViewState, b: ViewState): boolean {
  return KEYS.every((k) => same(a[k], b[k]));
}

/** The browser side of the URL state: the only reader and writer of location.hash. */
export const hashStore = {
  read: () => fromHash(location.hash),
  hasHash: () => location.hash.length > 1,
  write(s: ViewState) {
    history.replaceState(null, "", `${location.pathname}${location.search}#${toHash(s)}`);
  },
  onChange(fn: (s: ViewState) => void) {
    window.addEventListener("hashchange", () => fn(fromHash(location.hash).state));
  },
  /** ?embed=1 selects the compact player (a page option, not view state). */
  isEmbed: () => new URLSearchParams(location.search).get("embed") === "1",
  /** A shareable link to exactly this state. */
  url: (s: ViewState, embed = false) =>
    `${location.origin}${location.pathname}${embed ? "?embed=1" : ""}#${toHash(s)}`,
};

/** Parameters that define the backend session (a change means a new search). */
export function sessionKey(s: ViewState): string {
  return JSON.stringify([s.ra, s.dec, s.fov, s.rel, s.deep, s.pm, s.pm ? [s.pmra, s.pmdec, s.pmep] : null]);
}

/** Query string for /products, /photometry and image URLs. */
export function productParams(s: ViewState): URLSearchParams {
  const p = new URLSearchParams();
  p.set("mode", s.mode);
  p.set("window", String(s.win));
  if (s.dets.length) p.set("dets", s.dets.join(","));
  if (s.lmin !== null) p.set("lam_min", String(s.lmin));
  if (s.lmax !== null) p.set("lam_max", String(s.lmax));
  if (s.t0 !== null) p.set("mjd_min", String(s.t0));
  if (s.t1 !== null) p.set("mjd_max", String(s.t1));
  p.set("diff", s.diff);
  if (s.diff === "ref") p.set("ref", String(s.ref));
  p.set("rgb", s.rgb.join(","));
  return p;
}
