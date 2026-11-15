// Coordinate parsing, formatting and validation: the only implementation in the frontend.
// It is the line-for-line twin of backend/spherex_viewer/coords.py; both run the cases in
// shared/coords_cases.json, so the browser and the API accept and print the same things.

const N = "(\\d+(?:\\.\\d*)?|\\.\\d+)";
const NUM = new RegExp(`^[+-]?${N}$`);
const COLONS = new RegExp(`^([+-]?)${N}(?::${N}(?::${N})?)?$`);                  // 08:55:10.8
const UNITS = new RegExp(`^([+-]?)${N}([hd])(?:${N}[m']?(?:${N}[s"]?)?)?$`);     // 08h55m10.8s
const LETTERS = /[a-ce-gi-ln-rt-zA-Z]/;        // any letter other than d, h, m, s

/** The text is a coordinate pair, but an impossible one. */
export class CoordinateError extends Error {}

export function checkRange(ra: number, dec: number): [number, number] {
  if (!(ra >= 0 && ra < 360) || !(dec >= -90 && dec <= 90))
    throw new CoordinateError(`coordinates out of range: RA=${ra}, Dec=${dec}`);
  return [ra, dec];
}

/** '-07:14:42.53', '08h55m10.8s', '12d30m' -> degrees. `hours` says whether a value with
 * no unit letter is in hours (RA) or degrees (Dec); an explicit h or d wins. */
function sexagesimalDegrees(token: string, hours: boolean): number | null {
  let m = UNITS.exec(token);
  let parts: (string | undefined)[];
  if (m) {
    hours = m[3] === "h";
    parts = [m[2], m[4], m[5]];
  } else {
    m = COLONS.exec(token);
    if (!m) return null;
    parts = [m[2], m[3], m[4]];
  }
  const vals = parts.filter((p): p is string => p !== undefined).map(Number);
  if (vals.slice(1).some((v) => v > 60)) return null;
  const value = vals.reduce((sum, v, i) => sum + v / 60 ** i, 0);
  return (m[1] === "-" ? -value : value) * (hours ? 15 : 1);
}

/** Parse "RA Dec" in decimal degrees or sexagesimal. Returns null if `text` does not look
 * like coordinates (so the caller can try name resolution); throws CoordinateError if it
 * does but is out of range. Two plain numbers are degrees; sexagesimal RA is in hours. */
export function parseCoordinates(text: string): [number, number] | null {
  const s = text.trim().replace(/[−–]/g, "-").replace(/′/g, "'").replace(/″/g, '"').replace(/°/g, "d");
  if (!s || LETTERS.test(s.replace(/deg/g, ""))) return null;
  let tokens = s.replace(/,/g, " ").replace(/deg/g, " ").split(/\s+/).filter(Boolean);
  let ra: number | null, dec: number | null;
  if (tokens.length === 2 && tokens.every((t) => NUM.test(t))) {
    [ra, dec] = tokens.map(Number);
  } else {
    if (tokens.length === 6) tokens = [tokens.slice(0, 3).join(":"), tokens.slice(3).join(":")];
    if (tokens.length !== 2) return null;
    ra = sexagesimalDegrees(tokens[0], true);
    dec = sexagesimalDegrees(tokens[1], false);
    if (ra === null || dec === null) return null;
  }
  return checkRange(ra, dec);
}

const pad = (n: number, width: number) => String(n).padStart(width, "0");

/** Non-negative `value` (hours or degrees) as HH:MM:SS.ss; rounding carries, and with
 * `modulo` (24 for RA) a value that rounds up to it wraps to zero. */
function sexagesimalText(value: number, precision: number, modulo = 0): string {
  const scale = 10 ** precision;
  let total = Math.floor(value * 3600 * scale + 0.5);
  if (modulo) total %= modulo * 3600 * scale;
  const whole = Math.floor(total / scale), frac = total % scale;
  const h = Math.floor(whole / 3600), m = Math.floor((whole % 3600) / 60), sec = whole % 60;
  return `${pad(h, 2)}:${pad(m, 2)}:${pad(sec, 2)}` + (precision ? `.${pad(frac, precision)}` : "");
}

/** `17:57:48.50 +04:41:36.21` (RA in hours, Dec in degrees). */
export function formatSexagesimal(ra: number, dec: number, raPrecision = 2, decPrecision = 2): string {
  return `${sexagesimalText(ra / 15, raPrecision, 24)} ${dec < 0 ? "-" : "+"}${sexagesimalText(Math.abs(dec), decPrecision)}`;
}

/** Fixed-point text built from integers, so both languages round identically. */
function fixed(value: number, precision: number, modulo = 0): string {
  const scale = 10 ** precision;
  let n = Math.floor(Math.abs(value) * scale + 0.5);
  if (modulo) n %= modulo * scale;
  return `${value < 0 && n > 0 ? "-" : ""}${Math.floor(n / scale)}` + (precision ? `.${pad(n % scale, precision)}` : "");
}

/** `133.79513 -7.24515`: decimal degrees, which parseCoordinates reads back (an RA that
 * rounds up to 360 wraps to 0). */
export function formatDecimal(ra: number, dec: number, precision = 5): string {
  return `${fixed(ra, precision, 360)} ${fixed(dec, precision)}`;
}
