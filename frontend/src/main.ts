// UI wiring: URL state <-> controls, session lifecycle (SSE progress), the three views
// (flipbook, sky sphere, Aladin), plots and overlays.
import { lang, t } from "./i18n";   // first: translates the page before anything else runs
import "./theme.css";
import "./app.css";
import { api, type CatSource, type FrameRecord, type MoverCandidate, type MoverList, type PhotRow, type ProductInfo, type ProductList, type Snapshot, type Suggestion, type WiseMotion, type WisePrediction } from "./api";
import type { Context } from "./aladin";
import { CoordinateError, formatDecimal, formatSexagesimal, parseCoordinates } from "./coords";
import { MotionPlot } from "./motion";
import { DETECTOR_COLORS, Player, Timeline, skyToGrid, type Marker } from "./player";
import { PlateFrame } from "./plate";
import { Plots } from "./plots";
import type { SkyMarker, SkySphere } from "./sphere";
import { Autocomplete } from "./suggest";
import { DEFAULTS, KEYS, SKY_LAYERS, hashStore, productParams, sessionKey, type Diff, type Tab, type View, type ViewState } from "./state";
import skyConfig from "../sky.config.json";

declare const __SKY_AVAILABLE__: string[];

const $ = <T extends HTMLElement = HTMLInputElement>(id: string) => document.getElementById(id) as T;
const MJD_UNIX0 = 40587;
const mjdToEpoch = (mjd: number) => 2000 + (mjd - 51544.5) / 365.25;
const mjdToDate = (mjd: number) => new Date((mjd - MJD_UNIX0) * 86400000).toISOString().slice(0, 10);
const dateToMjd = (d: string) => Date.parse(d + "T00:00:00Z") / 86400000 + MJD_UNIX0;
// The date range starts out as the whole mission: SPHEREx launch (11 March 2025 UTC) to
// today. Those two dates mean "no limit" (t0/t1 stay null), so an untouched range keeps
// taking in new observations and adds nothing to the URL.
const MISSION_START = "2025-03-11";
const today = () => {                       // the user's own calendar date
  const d = new Date(), p2 = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p2(d.getMonth() + 1)}-${p2(d.getDate())}`;
};
const dateDefault = (id: string) => (id === "t0" ? MISSION_START : today());
const esc = (s: string) => s.replace(/[&<>"]/g, (c) => `&#${c.charCodeAt(0)};`);

// The five acceptance targets, as presets on the sky sphere (J2000; a click searches by name,
// so proper motion comes from the resolver).
const PRESET_TARGETS = [
  { id: "Barnard's star", label: "Barnard's Star", ra: 269.45208, dec: 4.69339 },
  { id: "eps Ind B", label: "ε Indi B", ra: 331.04375, dec: -56.78278 },
  { id: "WISE 0855-0714", label: "WISE 0855−0714", ra: 133.79475, dec: -7.24514 },
  { id: "RW Aur", label: "RW Aur", ra: 76.95654, dec: 30.40144 },
  { id: "R Dra", label: "R Dra", ra: 248.1675, dec: 66.755 },
];

// ---------------------------------------------------------------------------------------
let state: ViewState = hashStore.read().state;
let session: Snapshot | null = null;
let events: EventSource | null = null;
let plist: ProductList | null = null;
let shown: ProductInfo[] = [];
let autoLimits: { vmin: number; vmax: number } | null = null;
let autoLimitsN = 0;
let phot: PhotRow[] = [];
const catalogs: Record<string, CatSource[] | null> = { gaia: null, catwise: null };
let refreshSeq = 0;
let refreshTimer: number | undefined;
let photTimer: number | undefined;
let pendingFrame: number | null = state.frame || null;
let lastDiff: Diff = state.diff !== "none" ? state.diff : "median";
let lastProgress: Snapshot["progress"] | null = null;

// The view tabs are wired before anything else so they keep working even if a later part of
// the page (e.g. a sky map) fails to initialise.
for (const b of document.querySelectorAll<HTMLButtonElement>("#viewtabs button"))
  b.addEventListener("click", () => update({ view: b.dataset.view as View }));
for (const b of document.querySelectorAll<HTMLButtonElement>("#tabs button"))
  b.addEventListener("click", () => update({ tab: b.dataset.tab as Tab }));

const embed = hashStore.isEmbed();
document.body.classList.toggle("embed", embed);
$("watermark").hidden = !embed;

// Title screen: covers the app on open; a click or any key dismisses it. Keys are swallowed
// while it is up so they do not trigger the shortcuts underneath. (Removed inline for embeds.)
const titleScreen = document.getElementById("title");
if (titleScreen) {
  const onKey = (e: KeyboardEvent) => {
    if (e.ctrlKey || e.metaKey || e.altKey || ["Shift", "Control", "Alt", "Meta", "Tab"].includes(e.key)) return;
    if ((e.target as Element).closest?.("#langpick")) return;      // Enter/Space work the language buttons
    e.preventDefault();
    e.stopImmediatePropagation();
    dismiss();
  };
  const dismiss = () => {
    window.removeEventListener("keydown", onKey, true);
    titleScreen.classList.add("out");
    setTimeout(() => titleScreen.remove(), 300);
    $("q").focus();
  };
  window.addEventListener("keydown", onKey, true);
  titleScreen.addEventListener("click", dismiss);
}

const player = new Player($<HTMLCanvasElement>("canvas"));
const timeline = new Timeline($<HTMLCanvasElement>("ticks"), (i) => { player.pause(); player.go(i); syncPlayButton(); });
const plateFrame = new PlateFrame($<HTMLCanvasElement>("plateframe"), $<HTMLCanvasElement>("canvas"), $("stage"), $("canvaswrap"));
let acquiredFor = "";
const plots = new Plots($<HTMLCanvasElement>("spec"), $<HTMLCanvasElement>("lc"));
const motionPlot = new MotionPlot($<HTMLCanvasElement>("motionplot"));
// Aladin Lite and the Three.js sphere are created (and their code downloaded) only when
// their tab is first opened.
let context: Context | null = null;
let sphere: SkySphere | null = null;

function setMsg(text: string, cls = "") {
  const m = $("msg");
  m.textContent = text;
  m.className = cls;
}

// ---------------------------------------------------------------------------------------
// Controls <-> state
type Binding = [id: string, key: keyof ViewState, kind: "num" | "numOrNull" | "bool" | "str" | "date" | "ref1" | "intList"];
const BINDINGS: Binding[] = [
  ["fov", "fov", "num"], ["rel", "rel", "str"], ["deep", "deep", "bool"],
  ["pm", "pm", "bool"], ["pmra", "pmra", "num"], ["pmdec", "pmdec", "num"], ["pmep", "pmep", "num"],
  ["wfit", "wfit", "bool"],
  ["mode", "mode", "str"], ["win", "win", "num"], ["rgb", "rgb", "intList"], ["diff", "diff", "str"],
  ["ref", "ref", "ref1"], ["lmin", "lmin", "numOrNull"], ["lmax", "lmax", "numOrNull"],
  ["t0", "t0", "date"], ["t1", "t1", "date"], ["stretch", "stretch", "str"],
  ["vmin", "vmin", "numOrNull"], ["vmax", "vmax", "numOrNull"], ["inv", "inv", "bool"],
  ["zoom", "zoom", "num"], ["xhair", "xhair", "bool"], ["flag", "flag", "str"],
  ["gaia", "gaia", "bool"], ["catwise", "catwise", "bool"], ["hips", "hips", "str"],
  ["speed", "speed", "num"], ["ap", "ap", "num"], ["lcmin", "lcmin", "numOrNull"], ["lcmax", "lcmax", "numOrNull"],
  ["slayer", "slayer", "str"], ["sgrid", "sgrid", "bool"], ["secl", "secl", "bool"], ["sgal", "sgal", "bool"],
];

function readControl(id: string, kind: Binding[2]): unknown {
  const el = $(id);
  if (kind === "bool") return el.checked;
  const v = el.value.trim();
  switch (kind) {
    case "num": return v === "" ? undefined : Number(v);
    case "numOrNull": return v === "" ? null : Number(v);
    case "date": return v === "" || v === dateDefault(el.id) ? null : dateToMjd(v);
    case "ref1": return Math.max(0, (Number(v) || 1) - 1);
    case "intList": return v.split(",").map(Number).filter((x) => Number.isInteger(x));
    default: return v;
  }
}

function writeControls() {
  for (const [id, key, kind] of BINDINGS) {
    const el = $(id);
    const v = state[key] as unknown;
    if (kind === "bool") el.checked = Boolean(v);
    else if (kind === "date") el.value = v === null ? dateDefault(el.id) : mjdToDate(v as number);
    else if (kind === "ref1") el.value = String((v as number) + 1);
    else if (kind === "intList") el.value = (v as number[]).join(",");
    else el.value = v === null ? "" : String(v);
  }
  $("speedv").textContent = `${state.speed} ms`;
  $("zoomv").textContent = `${state.zoom}×`;
  for (let d = 1; d <= 6; d++) $(`det${d}`).checked = state.dets.includes(d);
  const fb = $<HTMLSelectElement>("fbits");
  for (const o of Array.from(fb.options)) o.selected = state.fbits.includes(o.value);
  $("fovwarn").hidden = state.fov <= 10;
  $("fovwarn").textContent = state.fov > 10
    ? `Large field (${state.fov}′): cutouts are bigger and the first load takes longer.` : "";
  if (state.ra !== null && document.activeElement !== $("q") && state.pra === null)
    $("q").value = state.name || formatDecimal(state.ra, state.dec!);
  $<HTMLSelectElement>("preset").value = presetOf(state);
  $<HTMLSelectElement>("bpreset").value = presetOf(state);
  $("bfov").value = String(state.fov);
  $("difftoggle").setAttribute("aria-pressed", String(state.diff !== "none"));
  updateSummaries();
}

// ---------------------------------------------------------------------------------------
// Settings: section summaries, options shown only when they apply
const DET_RANGES: Record<number, string> = {
  1: "0.75–1.1", 2: "1.1–1.6", 3: "1.6–2.4", 4: "2.4–3.8", 5: "3.8–4.4", 6: "4.4–5.0",
};
const MODE_HINTS: Record<ViewState["mode"], string> = {
  frames: "Every exposure in time order. Each one sees a different infrared wavelength.",
  epoch: "Images taken within the epoch window are stacked into one sharper image per visit. Best for spotting motion.",
  detector: "All images from each detector stacked: six deep images from shortest to longest wavelength.",
  wave: "Everything inside the selected wavelength range stacked into one deep image.",
  rgb: "Stacks from three detectors shown as red, green and blue.",
};
const MODE_SHORT: Record<ViewState["mode"], string> = {
  frames: "every image", epoch: "stack per epoch", detector: "stack per detector",
  wave: "one wavelength stack", rgb: "false colour",
};
const DIFF_SHORT: Record<Diff, string> = { none: "", median: "minus median", ref: "minus reference" };

/** The atlas-plate label above the image: the target's name, set like a chart label, and
 * a catalogue line beneath it (position, motion, field, frames). Only known facts appear. */
let plateName = "";
function updatePlate() {
  const has = state.ra !== null && state.dec !== null;
  const [ra, dec] = has ? formatSexagesimal(state.ra!, state.dec!, 1, 0).split(" ") : ["", ""];
  const coordName = !!has && !state.name;      // no catalogue name: the coordinates are the name
  const name = has ? state.name || `${ra} ${dec.replace("-", "−")}` : "Choose a target";
  const el = $("platename");
  if (name !== plateName) {
    plateName = name;
    el.textContent = name;
    el.classList.remove("acquire"); void el.offsetWidth; el.classList.add("acquire");   // replay the set-in
  }
  const meta: [string, string][] = [];
  if (has) {
    if (!coordName) meta.push(["RA", ra], ["Dec", dec.replace("-", "−")]);
    if (state.pm) meta.push(["μ", `${state.pmra}, ${state.pmdec} mas/yr`.replace(/-/g, "−")]);
    meta.push(["Field", `${state.fov}′`]);
    const loaded = lastProgress?.loaded ?? 0;
    if (loaded) meta.push(["Frames", String(loaded)]);
  }
  $("platemeta").innerHTML = meta.map(([k, v]) => `<div data-k="${k === "μ" ? "pm" : k.toLowerCase()}"><dt>${k}</dt><dd>${esc(v)}</dd></div>`).join("");
}

function updateSummaries() {
  updatePlate();
  $("row-rgb").hidden = state.mode !== "rgb";
  $("row-ref").hidden = state.diff !== "ref";
  $("modehint").textContent = MODE_HINTS[state.mode];
  $("sum-fov").textContent = t("{0}′ · {1}× magnification", state.fov, state.zoom);
  const dates = `${state.t0 !== null ? mjdToDate(state.t0) : MISSION_START} → ${state.t1 !== null ? mjdToDate(state.t1) : t("today")}`;
  $("sum-time").textContent = `${dates} · ${t("{0} d epochs", state.win)} · ${state.speed} ms`;
  const sel: string[] = [];
  if (state.dets.length) sel.push(`D${state.dets.join(", D")}`);
  if (state.lmin !== null || state.lmax !== null) sel.push(`${state.lmin ?? "…"}–${state.lmax ?? "…"} µm`);
  $("sum-select").textContent = sel.length ? sel.join(" · ") : "all detectors, all λ";
  const ref = state.diff === "ref" ? ` #${state.ref + 1}` : "";
  $("sum-combine").textContent = `${t(MODE_SHORT[state.mode])}${DIFF_SHORT[state.diff] ? `, ${t(DIFF_SHORT[state.diff])}` : ""}${ref}`;
  const levels = t(state.vmin === null && state.vmax === null ? "auto levels" : "manual levels");
  const flags = state.flag === "off" ? "" : ` · ${t(state.flag === "overlay" ? "flags highlighted" : "flags blanked")}`;
  $("sum-display").textContent = `${state.stretch}, ${levels}, ${t(state.inv ? "dark on white" : "bright on black")}${flags}`;
  $("sum-data").textContent = state.pm ? t("tracking ({0}, {1}) mas/yr", state.pmra, state.pmdec) : t("not tracking");
  const ov = [state.xhair && "crosshair", state.wfit && "WISE prediction", state.gaia && "Gaia", state.catwise && "CatWISE", state.sgrid && "grid",
    state.secl && "ecliptic", state.sgal && "galactic"].filter((x): x is string => !!x).map((x) => t(x)).join(", ") || t("none");
  $("sum-overlays").textContent = ov;
}

/** Back to defaults for every setting except what was searched for and which view is open. */
function resetSettings() {
  const keep = new Set<keyof ViewState>(["tab", "view", "sphere", "map", "ra", "dec", "name", "fov", "pm", "pmra", "pmdec", "pmep", "wfit", "rel", "deep", "pra", "pdec"]);
  const patch: Record<string, unknown> = {};
  for (const k of KEYS) if (!keep.has(k)) patch[k] = DEFAULTS[k];
  autoLimits = null;
  update(patch as Partial<ViewState>);
}

// ---------------------------------------------------------------------------------------
// "Quick view" presets on top of the technical modes
type Preset = "every" | "visits" | "motion" | "colour" | "custom";
const PRESETS: Record<Exclude<Preset, "custom">, Partial<ViewState>> = {
  every: { mode: "frames", diff: "none" },
  visits: { mode: "epoch", win: 60, diff: "none" },
  motion: { mode: "epoch", win: 60, diff: "ref", ref: 0 },
  colour: { mode: "rgb", diff: "none" },
};

function presetOf(s: ViewState): Preset {
  if (s.mode === "frames" && s.diff === "none") return "every";
  if (s.mode === "epoch" && s.diff === "none") return "visits";
  if (s.mode === "epoch" && s.diff === "ref" && s.ref === 0) return "motion";
  if (s.mode === "rgb") return "colour";
  return "custom";
}

const NICE_DATE = (iso: string) => new Date(iso.slice(0, 10) + "T00:00:00Z")
  .toLocaleDateString(lang === "fil" ? "fil-PH" : undefined, { year: "numeric", month: "short", day: "numeric", timeZone: "UTC" });

/** Plain-language caption under the image. */
function simpleLabel(i: number, n: number, p: ProductInfo): string {
  const flag = p.target_bad ? ` <span class="flagged">${t("· ⚠ bad pixels at the target in this image")}</span>` : "";
  if (state.mode === "rgb") return t("False-colour composite of {0} images", p.n) + flag;
  if (p.n === 1) return t("Image {0} of {1} · {2} · infrared {3} µm", i + 1, n, NICE_DATE(p.date), p.lam_um.toFixed(2)) + flag;
  const span = `${NICE_DATE(mjdToDate(p.mjd_range[0]))} – ${NICE_DATE(mjdToDate(p.mjd_range[1]))}`;
  const what = state.mode === "epoch" ? "Visit {0} of {1} · {2} · {3} images combined" : "Combined image {0} of {1} · {2} · {3} images combined";
  const diff = state.diff === "ref" ? ` · ${t(i === state.ref ? "reference (shows as blank)" : "change since the reference")}` : "";
  return t(what, i + 1, n, span, p.n) + diff + flag;
}

// ---------------------------------------------------------------------------------------
// Views: flipbook | sky sphere | Aladin
/** Basic shows the flipbook with a sky map beside it; Advanced shows the chosen view
 * (flipbook, sky sphere or Aladin) between Settings and Measurements; Movers shows the
 * flipbook beside the list of candidate moving sources. */
function applyView(chosen: View) {
  document.body.dataset.tab = state.tab;
  for (const t of ["basic", "adv", "movers"] as const) $(`tabbtn-${t}`).setAttribute("aria-selected", String(t === state.tab));
  const view: View = state.tab === "adv" ? chosen : "flipbook";
  for (const v of ["flipbook", "sphere", "aladin"] as const) {
    $(`view-${v}`).hidden = v !== view;
    $(`vt-${v}`).setAttribute("aria-selected", String(v === view));
    $(`vt-${v}`).tabIndex = v === view ? 0 : -1;
  }
  // One sphere and one Aladin instance: each lives in its own tab's slot, and whichever is
  // chosen as the companion map moves beside the flipbook while that tab is open.
  const beside = state.tab === "basic" && !embed ? state.map : null;
  $(beside === "sphere" ? "mapslot" : "sphereslot").appendChild($("spherestage"));
  $(beside === "aladin" ? "mapslot" : "aladinslot").appendChild($("aladin"));
  for (const b of document.querySelectorAll<HTMLButtonElement>("[data-map]"))
    b.setAttribute("aria-pressed", String(b.dataset.map === state.map));
  if (view === "flipbook") { player.resize(); player.draw(); }
  if (view === "sphere" || beside === "sphere") openSphere();
  if (view === "aladin" || beside === "aladin") openAladin();
  if (state.tab === "movers") refreshMovers();
  player.draw();     // candidate rings are drawn in the Movers tab only
}

function sphereMarkers(): SkyMarker[] {
  // A preset that is the current target is drawn as the target only (no doubled label).
  const near = (t: { ra: number; dec: number }) => state.ra !== null && Math.abs(t.dec - state.dec!) < 0.5
    && Math.abs(((t.ra - state.ra + 540) % 360) - 180) * Math.cos((t.dec * Math.PI) / 180) < 0.5;
  const m: SkyMarker[] = PRESET_TARGETS.filter((t) => !near(t)).map((t) => ({ ...t, kind: "preset" as const }));
  if (state.ra !== null) m.push({ ra: state.ra, dec: state.dec!, label: state.name || t("target"), kind: "target" });
  if (state.pra !== null && state.pdec !== null) m.push({ ra: state.pra, dec: state.pdec, label: t("picked"), kind: "pick" });
  return m;
}

function syncSphere() {
  for (const b of document.querySelectorAll<HTMLButtonElement>("[data-sphere]"))
    b.setAttribute("aria-pressed", String(b.dataset.sphere === state.sphere));
  $("mirrorbadge").hidden = state.sphere !== "outside";
  if (!sphere) return;
  sphere.setOptions({ grid: state.sgrid, ecliptic: state.secl, galactic: state.sgal });
  sphere.setMarkers(sphereMarkers());
  sphere.setLayer(__SKY_AVAILABLE__.includes(state.slayer) ? state.slayer : __SKY_AVAILABLE__[0] ?? state.slayer);
}

let sphereLoading: Promise<void> | null = null;
function openSphere() {
  sphereLoading ??= (async () => {
    $("spherestate").hidden = false;
    $("spherestate").classList.add("busy");
    try {
      const { SkySphere } = await import("./sphere");
      sphere = new SkySphere($("spherestage"));
      sphere.onPick = pickPosition;
      sphere.onPreset = (id) => runExample(id, {});
      sphere.onHover = (t) => { $("spherecursor").hidden = !t; $("spherecursor").textContent = t ? `RA Dec  ${t}` : ""; };
      sphere.onStatus = (t) => { $("spherenote").textContent = t; };
      sphere.setMode(state.sphere, false);
      const at = state.pra !== null ? [state.pra, state.pdec!] : state.ra !== null ? [state.ra, state.dec!] : null;
      if (at) sphere.goTo(at[0], at[1], false);
      syncSphere();
      $("spherestate").hidden = true;
    } catch (e) {
      $("spherestate").classList.remove("busy");
      $("spherestate").classList.add("warnstate");
      $("spherestate").querySelector(".head")!.textContent = `Sky sphere unavailable: ${(e as Error).message}`;
    }
  })();
  sphere?.requestRender();
}

let aladinLoading: Promise<void> | null = null;
function openAladin() {
  aladinLoading ??= (async () => {
    const { Context } = await import("./aladin");
    context = new Context($("aladin"));
    context.onPick(pickPosition);
    if (session?.grid) context.show(session.grid, state.fov);
    await showHips();
    updateContextCatalogs();
    if (state.pra !== null) context.markPick(state.pra, state.pdec!, state.fov);
  })();
  context?.resize();
}

/** A click on either sky map: remember the position in the URL, put it in the search box,
 * and offer to load frames there. */
function pickPosition(ra: number, dec: number) {
  update({ pra: Number(ra.toFixed(5)), pdec: Number(dec.toFixed(5)) });
}

function showPick() {
  const has = state.pra !== null && state.pdec !== null;
  $("pickbar").hidden = !has;
  if (!has) return;
  $("q").value = formatDecimal(state.pra!, state.pdec!);
  $("picktext").textContent = `Picked ${formatDecimal(state.pra!, state.pdec!, 4)}  (${formatSexagesimal(state.pra!, state.pdec!, 1, 0)})`;
}

// ---------------------------------------------------------------------------------------
/** Apply a partial state change and do the minimum work it requires. */
function update(patch: Partial<ViewState>, opts: { fromHash?: boolean } = {}) {
  const prev = state;
  const next = { ...state, ...patch } as ViewState;
  for (const k of KEYS) {
    if (next[k] === undefined || (typeof next[k] === "number" && Number.isNaN(next[k]))) (next as Record<string, unknown>)[k] = prev[k];
  }
  state = next;
  if (next.diff !== "none") lastDiff = next.diff;
  if (!opts.fromHash) hashStore.write(state);
  writeControls();
  // UI-only changes apply even when the target also changes (that path returns early).
  if (prev.view !== next.view || prev.map !== next.map || prev.tab !== next.tab) applyView(next.view);
  if (prev.sphere !== next.sphere) sphere?.setMode(next.sphere);
  if (prev.pra !== next.pra || prev.pdec !== next.pdec) {
    showPick();
    if (next.pra !== null) context?.markPick(next.pra, next.pdec!, next.fov);
  }
  if (["sphere", "slayer", "sgrid", "secl", "sgal", "pra", "pdec", "ra", "dec", "name"].some((k) => prev[k as keyof ViewState] !== next[k as keyof ViewState])) syncSphere();
  if ((prev.ra !== next.ra || prev.dec !== next.dec) && next.ra !== null) sphere?.goTo(next.ra, next.dec!);
  if (sessionKey(prev) !== sessionKey(next)) {
    pendingFrame = next.frame || null;
    if (next.ra !== null) startSession();
    return;
  }
  const pp = (s: ViewState) => productParams(s).toString();
  if (pp(prev) !== pp(next)) { autoLimits = null; refreshProducts(); schedulePhot(0); }
  else if (["stretch", "vmin", "vmax", "inv", "flag", "fbits"].some((k) => JSON.stringify(prev[k as keyof ViewState]) !== JSON.stringify(next[k as keyof ViewState]))) rebuildUrls();
  if (prev.ap !== next.ap) schedulePhot(0);
  if (prev.lcmin !== next.lcmin || prev.lcmax !== next.lcmax) drawPlots();
  player.speed = next.speed;
  if (prev.zoom !== next.zoom) player.setZoom(next.zoom);
  if (prev.xhair !== next.xhair || prev.inv !== next.inv) { player.crosshair = next.xhair; player.lightSky = next.inv; player.draw(); }
  if (prev.gaia !== next.gaia || prev.catwise !== next.catwise) loadCatalogs();
  if (prev.wfit !== next.wfit) refreshMotion();
  if (prev.hips !== next.hips) showHips();
  if (opts.fromHash && prev.frame !== next.frame) player.go(next.frame);
}

function buildStaticControls() {
  const box = $("dets");
  for (let d = 1; d <= 6; d++) {
    const l = document.createElement("label");
    l.className = "band";
    l.title = `Detector ${d}: ${DET_RANGES[d]} µm`;
    l.innerHTML = `<input type="checkbox" id="det${d}"><i style="--c:${DETECTOR_COLORS[d]}"></i>D${d}`;
    box.appendChild(l);
    l.querySelector("input")!.addEventListener("change", () => update({ dets: [1, 2, 3, 4, 5, 6].filter((i) => $(`det${i}`).checked) }));
  }
  $("detlegend").innerHTML = [1, 2, 3, 4, 5, 6].map((d) => `<span><i style="--c:${DETECTOR_COLORS[d]}"></i>D${d} ${DET_RANGES[d]}</span>`).join("")
    + `<span><i style="--c:#9fb0d0"></i>stack</span><span><i style="--c:#f2b544"></i>flagged at target</span>`;
  $("slayer").innerHTML = skyConfig.layers.filter((l) => SKY_LAYERS.includes(l.id)).map((l) =>
    `<option value="${l.id}"${__SKY_AVAILABLE__.includes(l.id) ? "" : " disabled"}>${esc(l.label)}${__SKY_AVAILABLE__.includes(l.id) ? "" : " (not built)"}</option>`).join("");
  $("spherepresets").innerHTML = PRESET_TARGETS.map((t) => `<button type="button" data-ex="${esc(t.id)}">${esc(t.label)}</button>`).join("");
}

function bindControls() {
  for (const [id, key, kind] of BINDINGS) {
    const el = $(id);
    const ev = el.type === "range" ? "input" : "change";
    el.addEventListener(ev, () => update({ [key]: readControl(id, kind) } as Partial<ViewState>));
  }
  $<HTMLSelectElement>("fbits").addEventListener("change", (e) => {
    const sel = Array.from((e.target as HTMLSelectElement).selectedOptions).map((o) => o.value);
    update({ fbits: sel, flag: state.flag === "off" && sel.length ? "overlay" : state.flag });
  });
  for (const id of ["preset", "bpreset"]) $<HTMLSelectElement>(id).addEventListener("change", (e) => {
    const v = (e.target as HTMLSelectElement).value as Preset;
    if (v !== "custom") update(PRESETS[v]);
  });
  $("bfov").addEventListener("change", () => update({ fov: Number($("bfov").value) || undefined }));
  $("pickgo").addEventListener("click", loadPicked);
  $("pickclear").addEventListener("click", () => update({ pra: null, pdec: null }));
  $("resetadv").addEventListener("click", resetSettings);
  $("auto").addEventListener("click", () => { autoLimits = null; update({ vmin: null, vmax: null }); refreshProducts(); });
  $("search").addEventListener("submit", (e) => { e.preventDefault(); autocomplete.close(); search($("q").value); });
  $("gaiapm").addEventListener("click", gaiaLookup);
  $("motionuse").addEventListener("click", trackFittedMotion);
  $("mvmin").addEventListener("input", renderMovers);
  $("mvnew").addEventListener("change", renderMovers);
  $("moverlist").addEventListener("click", (e) => {
    const tr = (e.target as HTMLElement).closest<HTMLElement>("tr[data-i]");
    if (tr) selectMover(Number(tr.dataset.i));
  });
  $("retry").addEventListener("click", () => session && api.retry(session.id).then(() => connectEvents()));
  $("prev").addEventListener("click", () => step(-1));
  $("next").addEventListener("click", () => step(1));
  $("play").addEventListener("click", togglePlay);
  $("difftoggle").addEventListener("click", toggleDiff);
  $("scrub").addEventListener("input", () => { player.pause(); player.go(Number($("scrub").value)); syncPlayButton(); });
  $("showflagged").addEventListener("change", drawPlots);
  for (const b of document.querySelectorAll<HTMLButtonElement>("[data-sphere]"))
    b.addEventListener("click", () => update({ sphere: b.dataset.sphere as ViewState["sphere"] }));
  for (const b of document.querySelectorAll<HTMLButtonElement>("[data-map]"))
    b.addEventListener("click", () => update({ map: b.dataset.map as ViewState["map"] }));

  // Help and share dialogs (native <dialog>: focus is trapped and Esc closes). Data credits
  // live in Help.
  $("help").addEventListener("click", () => $<HTMLDialogElement>("helpdlg").showModal());
  $("share").addEventListener("click", openShare);
  for (const d of document.querySelectorAll<HTMLDialogElement>("dialog")) {
    d.querySelector(".dlgclose")!.addEventListener("click", () => d.close());
    d.addEventListener("click", (e) => { if (e.target === d) d.close(); });   // click on the backdrop
  }
  for (const b of document.querySelectorAll<HTMLButtonElement>("[data-copy]"))
    b.addEventListener("click", async () => {
      const el = $(b.dataset.copy!);
      try { await navigator.clipboard.writeText(el.value); $("copynote").textContent = "Copied."; }
      catch { el.select(); $("copynote").textContent = "Press Ctrl/Cmd+C to copy."; }
    });

  // Example targets (help dialog and sphere presets): look the name up in the suggestion
  // index and load it.
  document.addEventListener("click", (e) => {
    const b = (e.target as HTMLElement).closest<HTMLElement>("[data-ex]");
    if (!b) return;
    const view: Partial<ViewState> = b.dataset.preset
      ? { ...PRESETS[b.dataset.preset as Exclude<Preset, "custom">], dets: b.dataset.dets ? b.dataset.dets.split(",").map(Number) : [] } : {};
    $<HTMLDialogElement>("helpdlg").close();
    runExample(b.dataset.ex!, view);
  });

  // Settings rail (desktop): the settings column is always open beside the rail, mirroring
  // Measurements on the right; each rail item shows its section there. The sections share
  // name="ctl", so opening one closes the others.
  const rail = Array.from(document.querySelectorAll<HTMLButtonElement>("#rail [data-sec]"));
  const sections = Array.from(document.querySelectorAll<HTMLDetailsElement>("#controls details.sec"));
  const syncRail = () => {
    const open = sections.find((d) => d.open)?.id ?? "";
    for (const b of rail) b.setAttribute("aria-pressed", String(b.dataset.sec === open));
  };
  for (const b of rail)
    b.addEventListener("click", () => {
      $<HTMLDetailsElement>(b.dataset.sec!).open = true;
      syncRail();
    });
  for (const d of sections) d.addEventListener("toggle", () => {
    // On the desktop column a section never closes to nothing: keep the last one open.
    if (!sections.some((x) => x.open) && window.matchMedia("(min-width: 901px)").matches) d.open = true;
    syncRail();
  });
  if (!sections.some((d) => d.open)) $<HTMLDetailsElement>("sec-combine").open = true;
  syncRail();

  // Mobile bottom sheets.
  for (const b of document.querySelectorAll<HTMLButtonElement>("[data-sheet]"))
    b.addEventListener("click", () => {
      const want = b.dataset.sheet!;
      const open = document.body.dataset.sheet === want || !want ? "" : want;
      document.body.dataset.sheet = open;
      for (const t of document.querySelectorAll<HTMLButtonElement>("#sheetbar button"))
        t.setAttribute("aria-expanded", String(t.dataset.sheet === open));
    });

  document.addEventListener("keydown", (e) => {
    const t = e.target as HTMLElement;
    if (e.ctrlKey || e.metaKey || e.altKey || document.querySelector("dialog[open]")) return;
    if (["INPUT", "SELECT", "TEXTAREA"].includes(t.tagName) || t.isContentEditable) return;
    const onButton = ["BUTTON", "SUMMARY", "A"].includes(t.tagName);   // Space/Enter activate these
    if (e.key === " " && !onButton) { e.preventDefault(); togglePlay(); }
    else if (e.key === "ArrowRight") step(1);
    else if (e.key === "ArrowLeft") step(-1);
    else if (e.key === "d" || e.key === "D") toggleDiff();
    else if (e.key === "s" || e.key === "S") toggleSphere();
    else if (e.key === "?") $<HTMLDialogElement>("helpdlg").showModal();
  });
  hashStore.onChange((s) => update(s, { fromHash: true }));
}

function openShare() {
  const url = hashStore.url(state), emb = hashStore.url(state, true);
  $("shareurl").value = url;
  $("embedurl").value = emb;
  $("embedcode").value = `<iframe src="${emb}" width="640" height="720" style="border:0" title="Talasuri: ${esc(state.name || "SPHEREx flipbook")}" loading="lazy"></iframe>`;
  $("copynote").textContent = "";
  $<HTMLDialogElement>("sharedlg").showModal();
}

/** S, and the "pick on the sphere" buttons: the sphere beside the flipbook in Basic, the
 * full Sky Sphere view (or back to the flipbook) in Advanced. */
function toggleSphere(open = false) {
  if (state.tab === "movers") return;
  if (state.tab === "basic") update({ map: "sphere" });
  else update({ view: state.view === "sphere" && !open ? "flipbook" : "sphere" });
}

function step(d: number) { player.pause(); player.step(d); syncPlayButton(); }

/** D: difference imaging on/off (remembers whether median or reference was last used). */
function toggleDiff() { update({ diff: state.diff === "none" ? lastDiff : "none" }); }

// The SPHEREx sky map shows the wavelength of the image on screen. Debounced: each new
// wavelength loads a fresh set of map tiles, so don't switch on every flipbook frame.
let waveTimer: number | undefined;
function followWavelength(um: number) {
  window.clearTimeout(waveTimer);
  if (!context || !Number.isFinite(um)) return;
  waveTimer = window.setTimeout(() => {
    if (context && state.hips === "spherex") $("hipsnote").textContent = context.setWavelength(um);
  }, player.playing ? 3000 : 400);
}

async function showHips() {
  if (context) $("hipsnote").textContent = await context.setHips(state.hips);
}

function togglePlay() {
  if (player.playing) player.pause(); else player.play();
  syncPlayButton();
}

function syncPlayButton(recordFrame = true) {
  $("play").classList.toggle("playing", player.playing);
  $("play").setAttribute("aria-label", player.playing ? "Pause" : "Play");
  if (recordFrame && !player.playing && player.products.length && state.frame !== player.index) {
    state = { ...state, frame: player.index };
    hashStore.write(state);
  }
  if (!player.playing) updateContextCatalogs();
}

// ---------------------------------------------------------------------------------------
// Search + session
async function search(q: string) {
  q = q.trim();
  if (!q) return;
  // Coordinates are parsed here, by the same rules the backend uses; names go to the resolver.
  try {
    const c = parseCoordinates(q);
    if (c) {
      setMsg(`${formatDecimal(c[0], c[1])}  (${formatSexagesimal(c[0], c[1])})`);
      update({ ra: c[0], dec: c[1], name: "", pm: false, pmra: 0, pmdec: 0, pmep: 2000, frame: 0, pra: null, pdec: null, view: "flipbook" });
      autoTrack();
      return;
    }
  } catch (e) {
    if (e instanceof CoordinateError) { setMsg(`Could not resolve: ${e.message}`, "warn"); return; }
    throw e;
  }
  setMsg(`Resolving ${q}…`);
  try {
    const t = await api.resolve(q);
    const hasPm = t.source === "sesame" && (t.pmra !== 0 || t.pmdec !== 0);
    setMsg(`${t.name ?? q}: ${t.sexagesimal}${hasPm ? `  μ=(${t.pmra}, ${t.pmdec}) mas/yr → tracking` : ""}`);
    update({ ra: t.ra, dec: t.dec, name: t.source === "sesame" ? q : "", pm: hasPm,
      pmra: hasPm ? t.pmra : 0, pmdec: hasPm ? t.pmdec : 0, pmep: t.epoch, frame: 0, pra: null, pdec: null });
    if (!hasPm) autoTrack();
  } catch (e) {
    setMsg(`Could not resolve: ${(e as Error).message}`, "warn");
  }
}

/** "Load frames here": the picked position becomes the target. */
function loadPicked() {
  if (state.pra === null || state.pdec === null) return;
  update({ ra: state.pra, dec: state.pdec, name: "", pm: false, pmra: 0, pmdec: 0, pmep: 2000, frame: 0,
    pra: null, pdec: null, view: "flipbook" });
}

/** A suggestion carries SIMBAD's J2000 position and proper motion, so it loads directly
 * without another name lookup (this keeps working when the name resolver is down). */
function chooseObject(s: Suggestion, extra: Partial<ViewState> = {}) {
  const hasPm = (s.pmra ?? 0) !== 0 || (s.pmdec ?? 0) !== 0;
  setMsg(`${s.label}${s.type ? ` (${s.type})` : ""}: ${formatDecimal(s.ra, s.dec, 4)}` +
    (hasPm ? ` · ${t("moving {0}″/yr, tracking it", (Math.hypot(s.pmra, s.pmdec) / 1000).toFixed(2))}` : ""));
  update({ ra: s.ra, dec: s.dec, name: s.label, pm: hasPm, pmra: hasPm ? s.pmra : 0,
    pmdec: hasPm ? s.pmdec : 0, pmep: 2000, frame: 0, pra: null, pdec: null, ...extra });
  if (!hasPm) autoTrack();
}

/** Slowest motion worth tracking automatically, mas/yr. Below it the target moves less
 * than a hundredth of a SPHEREx pixel (6.15 arcsec) per year. */
const AUTO_TRACK_MIN = 50;

/** After a search that gave no proper motion (typed coordinates, or a name the resolver
 * has no motion for): ask Gaia DR3 for the star at that position and, if it moves, turn
 * tracking on. The frames start loading meanwhile; Gaia takes a few seconds. */
async function autoTrack() {
  const { ra, dec, pmep } = state;
  if (ra === null || dec === null) return;
  try {
    const g = await api.gaiaPm(ra, dec, pmep);
    // Only if the target is still the one searched for and nothing set a motion meanwhile.
    if (state.ra !== ra || state.dec !== dec || state.pm || g.pmra === null || g.pmdec === null) return;
    const total = Math.hypot(g.pmra, g.pmdec);
    if (total < AUTO_TRACK_MIN) return;
    setMsg(`Gaia DR3 ${g.id}: moving ${(total / 1000).toFixed(2)}″/yr, tracking it`);
    update({ pm: true, pmra: Number(g.pmra.toFixed(3)), pmdec: Number(g.pmdec.toFixed(3)) });
  } catch { /* no Gaia star there, or Gaia did not answer: stay untracked */ }
}

async function runExample(q: string, view: Partial<ViewState>) {
  try {
    const item = (await api.suggest(q)).items?.[0];
    if (item) { $("q").value = item.label; chooseObject(item, view); return; }
  } catch { /* fall back to the name resolver */ }
  update(view);
  search(q);
}

const autocomplete = new Autocomplete($("q"), $("qlist"), chooseObject);

async function gaiaLookup() {
  if (state.ra === null) return;
  setMsg("Looking up Gaia DR3 proper motion…");
  try {
    const g = await api.gaiaPm(state.ra, state.dec!, state.pmep);
    setMsg(`Gaia DR3 ${g.id}: μ=(${g.pmra?.toFixed(1)}, ${g.pmdec?.toFixed(1)}) mas/yr, G=${g.mag?.toFixed(2)}, ${g.sep_arcsec.toFixed(1)}″ from input at ${state.pmep}`);
    update({ pm: true, pmra: Number(g.pmra!.toFixed(3)), pmdec: Number(g.pmdec!.toFixed(3)) });
  } catch (e) {
    setMsg(`Gaia lookup failed: ${(e as Error).message}`, "warn");
  }
}

async function startSession() {
  events?.close();
  player.pause();
  syncPlayButton(false);  // keep a frame index that came from the URL
  plist = null; shown = []; autoLimits = null; autoLimitsN = 0; phot = [];
  session = null; lastProgress = null;
  catalogs.gaia = catalogs.catwise = null;
  movers = null; moverKey = ""; selectedMover = null;
  renderMovers();
  player.setProducts({ ra: 0, dec: 0, npix: 0, scale_arcsec: 6.15, center_pix: 0 }, [], []);
  drawPlots();
  refreshMotion();      // the fit needs only the target, so it starts while frames load
  setMsg("Querying IRSA…");
  showStage("busy", "Contacting IRSA…", "Looking for SPHEREx observations of this position.");
  try {
    session = await api.createSession(state);
  } catch (e) {
    setMsg(`Search failed: ${(e as Error).message}`, "warn");
    showStage("warn", "Search failed", (e as Error).message, [["Try again", startSession]]);
    return;
  }
  onSnapshot(session);
  connectEvents();
}

function connectEvents() {
  if (!session) return;
  events?.close();
  const sid = session.id;
  events = api.events(sid);
  events.onmessage = (ev) => {
    if (!session || session.id !== sid) return;
    const e = JSON.parse(ev.data);
    if (e.type === "progress") showProgress(e);
    else if (e.type === "observations") {
      session.grid = e.grid; session.center = e.center;
      session.records = e.records;
      if (context && session.grid) context.show(session.grid, state.fov);
      renderFrameList();
      if (state.tab === "movers") refreshMovers();
    } else if (e.type === "frame") {
      const i = session.records.findIndex((r) => r.key === e.record.key);
      if (i >= 0) session.records[i] = e.record; else session.records.push(e.record);
      scheduleRefresh();
      schedulePhot(5000);
    } else if (e.type === "done") {
      events?.close();
      api.snapshot(sid).then((s) => { onSnapshot(s); refreshProducts(); schedulePhot(0); });
    }
  };
  events.onerror = () => { /* EventSource reconnects automatically */ };
}

function onSnapshot(s: Snapshot) {
  session = s;
  showProgress(s.progress);
  // Warnings (e.g. large FOV) are already shown in the controls; only surface errors here.
  if (s.errors.length) setMsg(s.errors.join("; "), "warn");
  const fb = $<HTMLSelectElement>("fbits");
  if (s.flag_bits.length && fb.options.length !== s.flag_bits.length) {
    fb.innerHTML = s.flag_bits.map((b) =>
      `<option value="${b.name}" title="${esc(b.description)}">${b.bit}: ${b.name}${b.default_bad ? " *" : ""}</option>`).join("");
    writeControls();
  }
  if (context && s.grid) context.show(s.grid, state.fov);
  renderFrameList();
  if (s.records.some((r) => r.status === "ok")) { refreshProducts(); schedulePhot(0); }
  loadCatalogs();
  if (state.tab === "movers") refreshMovers();
}

/** The themed progress readout (header status line and, until frames show, the stage). */
function showProgress(p: Snapshot["progress"]) {
  lastProgress = p;
  const pct = p.total ? (100 * p.done) / p.total : p.state === "done" ? 100 : 0;
  $("barfill").style.width = `${pct}%`;
  const acquiring = p.state === "fetching" && p.total > 0;
  const text = acquiring ? `Acquiring frames ${p.done}/${p.total}…`
    : p.state === "done" && p.total === 0 ? "No SPHEREx coverage here yet"
    : p.message || (p.state === "querying" ? "Querying IRSA…" : "");
  setMsg([text, p.failed ? `${p.failed} failed` : ""].filter(Boolean).join(" — "), p.state === "error" ? "warn" : "");
  $("retry").hidden = !(p.failed && p.state === "done");
  updatePlate();
  updateStage();
}

type StageKind = "busy" | "warn" | "idle";
function showStage(kind: StageKind | null, title = "", text = "", actions: [string, () => void][] = []) {
  const card = $("stagestate");
  card.hidden = kind === null;
  $("hud").hidden = kind !== null;
  if (kind === null) return;
  card.className = `statecard ${kind === "busy" ? "busy" : kind === "warn" ? "warnstate" : ""}`;
  $("statetitle").textContent = title;
  $("statetext").textContent = text;
  const box = $("stateactions");
  box.replaceChildren(...actions.map(([label, fn]) => {
    const b = document.createElement("button");
    b.type = "button"; b.textContent = label; b.addEventListener("click", fn);
    return b;
  }));
}

/** Loading, empty and error states of the flipbook (shown whenever no image is on screen). */
function updateStage() {
  if (shown.length) { showStage(null); return; }
  const p = lastProgress;
  const toSphere: [string, () => void] = ["Pick on the Sky Sphere", () => toggleSphere(true)];
  if (state.ra === null) showStage("idle", "No target selected", "Search for a name or coordinates above, or click the sky map beside this panel.", [toSphere, ["Help", () => $<HTMLDialogElement>("helpdlg").showModal()]]);
  else if (!p || p.state === "querying") showStage("busy", "Contacting IRSA…", p?.message ?? "");
  else if (p.state === "error") showStage("warn", "Could not load frames", p.message, [["Try again", startSession]]);
  else if (p.state === "done" && p.total === 0) showStage("warn", "No SPHEREx coverage here yet", "No public SPHEREx image contains this position. Try another release, or another spot.", [toSphere]);
  else if (p.state === "done" && p.loaded === 0) showStage("warn", "No frames could be loaded", p.message, p.failed ? [["Retry failed", () => $("retry").click()]] : []);
  else if (plist && p.loaded > 0) showStage("warn", "No frames match the filters", "The detector, wavelength or date filters exclude every loaded frame.", [["Reset settings", resetSettings]]);
  else showStage("busy", `Acquiring frames ${p.done}/${p.total}…`, p.state === "paused" ? p.message : "Reading cutouts from the SPHEREx archive. Frames appear as they arrive.");
}

function scheduleRefresh() {
  if (refreshTimer !== undefined) return;
  const delay = state.mode === "frames" && state.diff === "none" ? 1500 : 5000;
  refreshTimer = window.setTimeout(() => { refreshTimer = undefined; refreshProducts(); }, delay);
}

// ---------------------------------------------------------------------------------------
// Products -> player
async function refreshProducts() {
  if (!session) return;
  const seq = ++refreshSeq;
  try {
    const pl = await api.products(session.id, state);
    if (seq !== refreshSeq) return;  // a newer request superseded this one
    plist = pl;
    // Freeze auto limits while frames stream in (so cached images stay valid), but improve
    // them as the sample grows (each doubling) and once loading is done.
    const loaded = pl.progress.loaded;
    if (pl.limits.vmin !== undefined && (!autoLimits || loaded >= 2 * autoLimitsN || pl.progress.state === "done")) {
      autoLimits = { vmin: pl.limits.vmin, vmax: pl.limits.vmax! };
      autoLimitsN = Math.max(loaded, 1);
    }
    rebuildUrls();
  } catch (e) {
    setMsg(`Could not build products: ${(e as Error).message}`, "warn");
  }
}

function rebuildUrls() {
  if (!session || !plist || !plist.grid) { updateStage(); return; }
  const sid = session.id;
  const lim = autoLimits ?? { vmin: plist.limits.vmin ?? 0, vmax: plist.limits.vmax ?? 1 };
  $("vmin").placeholder = lim.vmin.toPrecision(3);
  $("vmax").placeholder = lim.vmax.toPrecision(3);
  const loaded = plist.progress.loaded;
  let prods = plist.products;
  let urls: string[];
  if (state.mode === "rgb") {
    // The server composes R,G,B from the three detector stacks into one image.
    prods = prods.length >= 3 ? [{ ...prods[0], label: `RGB = ${prods.map((p) => `D${p.detectors[0]}`).join("/")}`,
      detectors: prods.flatMap((p) => p.detectors) }] : [];
    urls = prods.map(() => api.imageUrl(sid, state, 0, lim, loaded));
  } else {
    const stable = state.mode === "frames" && state.diff === "none";
    urls = prods.map((p) => api.imageUrl(sid, state, stable && p.key ? p.key : p.index, lim, loaded));
  }
  shown = prods;
  updateStage();
  player.setProducts(plist.grid, prods, urls);
  // Restore a frame index from the URL once enough products exist (only before the user
  // has moved the player).
  if (pendingFrame !== null && pendingFrame < prods.length) { player.go(pendingFrame); pendingFrame = null; }
  $("scrub").max = String(Math.max(0, prods.length - 1));
  scheduleMotion();     // predictions for the dates now on show
}

/** Scale bar: the longest round angle that fits in ~110 screen pixels. */
function drawScaleBar() {
  const g = player.grid;
  if (!g || !g.npix) return;
  const pxPerArcsec = player.zoom / g.scale_arcsec;
  const arcsec = [600, 300, 120, 60, 30, 10, 5].find((a) => a * pxPerArcsec <= 110) ?? 5;
  const bar = $("hud-scale");
  (bar.firstElementChild as HTMLElement).style.width = `${Math.round(arcsec * pxPerArcsec)}px`;
  bar.lastElementChild!.textContent = arcsec >= 60 ? `${arcsec / 60}′` : `${arcsec}″`;
}

player.onFrame = (i, p) => {
  $("scrub").value = String(i);
  timeline.set(shown, i);
  showMotionFrame(p);
  if (!p) {
    $("simplelabel").textContent = "";
    $("flagread").textContent = "";
    $("sum-flags").textContent = "";
    plateFrame.draw(null, player.zoom, null);
    return;
  }
  $("simplelabel").innerHTML = simpleLabel(i, shown.length, p);
  followWavelength(p.lam_um);
  // HUD readouts
  const [d0, d1] = [mjdToDate(p.mjd_range[0]), mjdToDate(p.mjd_range[1])];
  $("hud-date").textContent = p.n === 1 ? `${p.date.replace("T", " ").slice(0, 16)} UTC`
    : d0 === d1 ? d0 : `${d0} → ${d1.slice(0, 4) === d0.slice(0, 4) ? d1.slice(5) : d1}`;
  $("hud-det").textContent = `D${p.detectors.join(" D")}`;
  $("hud-lam").textContent = p.n === 1 ? `λ ${p.lam_um.toFixed(3)} µm  Δλ ${p.bw_um?.toFixed(3) ?? "?"}`
    : `${p.lam_range_um[0].toFixed(2)}–${p.lam_range_um[1].toFixed(2)} µm`;
  $("hud-frame").textContent = `${i + 1}/${shown.length}`;
  $("hud-label").textContent = p.n > 1 ? `${p.n} images` : "";
  $("caption").title = `${p.label} · MJD ${p.mjd.toFixed(3)}`;
  const flagText = p.n === 1 ? `⚠ target flagged: ${p.target_flag_names.join(", ")}` : `⚠ target flagged in ${p.n_members_flagged}/${p.n} members`;
  $("hud-flag").textContent = p.target_bad ? flagText : p.n > 1 && p.n_members_flagged ? `${p.n_members_flagged}/${p.n} flagged at target` : "";
  drawScaleBar();
  plateFrame.draw(player.grid, player.zoom, p.target_xy);
  const targetKey = `${state.ra},${state.dec}`;
  if (targetKey !== acquiredFor) { acquiredFor = targetKey; plateFrame.acquire(p.target_xy); }
  // Telemetry: flag readout and frame metadata
  $("flagread").innerHTML = p.target_flag_names.length
    ? p.target_flag_names.map((n) => `<span class="chip${p.target_bad ? " bad" : ""}">${esc(n)}</span>`).join("")
      + `<div class="hint">${p.n === 1 ? "FLAGS at the target pixel in this frame." : `OR of ${p.n} members; ${p.n_members_flagged} flagged as bad at the target.`}</div>`
    : `<span class="chip">no flags at target</span>`;
  const nf = p.target_flag_names.length;
  $("sum-flags").textContent = nf ? `${nf} flag${nf > 1 ? "s" : ""} at target` : "none";
  $("sum-flags").classList.toggle("warn", nf > 0);
  const rec = p.key ? session?.records.find((r) => r.key === p.key) : undefined;
  $("hdrtext").textContent = rec ? describeRecord(rec) : `${p.label}\nmembers: ${p.n}\nflags at target (OR of members): ${p.target_flag_names.join(", ") || "none"}`;
  if (session) {
    const pid = state.mode === "frames" && state.diff === "none" && p.key ? p.key : p.index;
    $("links").innerHTML = `<a href="${api.fitsUrl(session.id, state, pid)}">⬇ FITS</a>` +
      (rec?.url ? `<a href="${rec.url}" target="_blank" rel="noopener">Original at IRSA ↗</a>` : "") +
      `<a href="${hashStore.url(state, true)}" target="_blank" rel="noopener">Player-only link ↗</a>`;
    $<HTMLAnchorElement>("watermark").href = hashStore.url(state);
  }
  if (player.playing) throttledContextCatalogs();
};

function describeRecord(r: FrameRecord): string {
  const ph = r.phot as Record<string, unknown> | undefined;
  const lines = [
    `obs_id ${r.obs_id}  D${r.detector}  ${r.collection}  status=${r.status}`,
    `date ${r.date} UTC  MJD ${r.mjd.toFixed(5)}  epoch ${r.epoch}`,
    `λ at target ${r.lam_um?.toFixed(4)} µm  bandwidth ${r.bw_um?.toFixed(4)} µm`,
    `FLAGS at target: ${r.target_flags ?? 0} = ${(r.target_flag_names ?? []).join(", ") || "none"}`,
  ];
  if (ph) lines.push(`photometry: ${Number(ph.flux_ujy).toFixed(2)} ± ${Number(ph.err_ujy).toFixed(2)} µJy  bkg ${Number(ph.bkg_mjysr).toFixed(4)} MJy/sr  zodi ${Number(ph.zodi_mjysr).toFixed(3)} MJy/sr  ${ph.note ?? ""}`);
  if (r.error) lines.push(`error: ${r.error}`);
  if (r.header) lines.push("", ...Object.entries(r.header).map(([k, v]) => `${k.padEnd(13)} ${v}`));
  return lines.join("\n");
}

player.onHover = (ra, dec, x, y) => {
  $("cursor").textContent = `cursor ${formatDecimal(ra, dec)}  (x ${x.toFixed(1)}, y ${y.toFixed(1)})`;
};

// ---------------------------------------------------------------------------------------
// Catalog overlays (positions propagated to each frame's epoch)
function propagate(s: Pick<CatSource, "ra" | "dec" | "pmra" | "pmdec" | "epoch">, mjd: number): [number, number] {
  if (s.pmra === null || s.pmdec === null || s.epoch === null) return [s.ra, s.dec];
  const dt = mjdToEpoch(mjd) - s.epoch;
  return [s.ra + (s.pmra * dt) / 3.6e6 / Math.cos((s.dec * Math.PI) / 180), s.dec + (s.pmdec * dt) / 3.6e6];
}

const CATALOGS = [["gaia", "Gaia DR3", "#86b6ef", 1.4], ["catwise", "CatWISE2020", "#ffb547", 1.9]] as const;

player.markers = (p: ProductInfo): Marker[] => {
  const out: Marker[] = [];
  for (const [name, , color, r] of CATALOGS) {
    if (!state[name]) continue;
    for (const s of catalogs[name] ?? []) {
      const [ra, dec] = propagate(s, p.mjd);
      out.push({ ra, dec, color, r });
    }
  }
  if (state.tab === "movers") {
    const [strong, weak, pick] = state.inv ? ["#2f5ea8", "#5b6b8c", "#d92d20"] : ["#8fb3e8", "#8a98ae", "#ff5a4e"];
    for (const c of visibleMovers()) {
      // A likely mover is drawn where its motion puts it at this image's date; an unlikely
      // one stays at its catalogue position (its "motion" is probably not real).
      const likely = c.prob >= 0.5 || untested(c);
      const [ra, dec] = likely ? propagate(c, p.mjd) : [c.ra, c.dec];
      const sel = c === selectedMover;
      out.push({ ra, dec, color: sel ? pick : likely ? strong : weak, r: sel ? 2.6 : 2.1, width: sel ? 2.5 : likely ? 1.5 : 1,
        label: sel ? `P ${c.prob.toFixed(2)}` : undefined });
    }
  }
  const pred = state.wfit ? predictions.get(p.mjd) : undefined;
  if (pred && motion) {
    out.push({ ra: pred.ra, dec: pred.dec, color: state.inv ? "#6d3fd6" : "#b79cff", r: 0, width: 1.5,
      ellipse: { a: (motion.k95 * pred.a_mas) / 1000, b: (motion.k95 * pred.b_mas) / 1000, pa: pred.pa_deg } });
  }
  return out;
};

// ---------------------------------------------------------------------------------------
// Motion prediction: a fit to the object's WISE epochs, extrapolated to each image's date
let motion: WiseMotion | null = null;
let motionFor = "";                 // the target (position + starting motion) the fit is for
let motionSeq = 0;
let motionTimer: number | undefined;
const predictions = new Map<number, WisePrediction>();   // by image MJD

const motionTarget = (s: ViewState) => JSON.stringify([s.ra, s.dec, s.pm ? [s.pmra, s.pmdec, s.pmep] : null]);

function scheduleMotion() {
  window.clearTimeout(motionTimer);
  motionTimer = window.setTimeout(refreshMotion, 400);
}

async function refreshMotion() {
  window.clearTimeout(motionTimer);
  const seq = ++motionSeq;
  if (!state.wfit || state.ra === null || state.dec === null) {
    motion = null; motionFor = ""; predictions.clear();
    renderMotion(""); player.draw();
    return;
  }
  const key = motionTarget(state);
  const mjds = shown.map((p) => p.mjd);
  if (key === motionFor && motion && mjds.every((m) => predictions.has(m))) { renderMotion(""); return; }
  if (key !== motionFor) { motion = null; predictions.clear(); motionFor = key; renderMotion("Fitting the WISE epochs… (a first fit reads the WISE archive: about 10 s)"); player.draw(); }
  try {
    const r = await api.wiseMotion({ ra: state.ra, dec: state.dec, epoch: state.pmep,
      pmra: state.pm ? state.pmra : 0, pmdec: state.pm ? state.pmdec : 0, mjds });
    if (seq !== motionSeq) return;
    motion = r;
    predictions.clear();
    r.predictions.forEach((p, i) => predictions.set(mjds[i], p));
    renderMotion("");
  } catch (e) {
    if (seq !== motionSeq) return;
    motion = null; predictions.clear();
    renderMotion(`No prediction: ${(e as Error).message}`, true);
  }
  player.draw();
}

const pm1 = (v: number, e: number) => `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(1)} ± ${e.toFixed(1)}`;

function renderMotion(status: string, failed = false) {
  const m = motion;
  $("motionstate").textContent = failed ? "" : status;
  $("motionwarn").textContent = failed ? status : (m?.warnings ?? []).map((w) => `⚠ ${w}`).join("\n");
  for (const id of ["motionread", "motionbox", "motionkey", "motionuse"]) $(id).hidden = !m;
  $("sum-motion").textContent = !state.wfit ? "off" : m ? `μ ${(m.pm / 1000).toFixed(3)}″/yr from ${m.n_visits_used} WISE visits` : failed ? "no fit" : "fitting…";
  showMotionFrame(shown[player.index]);
}

/** The fit's numbers, the prediction for the image on screen, and the plot. */
function showMotionFrame(p: ProductInfo | undefined) {
  const m = motion;
  const range = shown.length ? [Math.min(...shown.map((s) => s.mjd)), Math.max(...shown.map((s) => s.mjd))] as [number, number] : null;
  motionPlot.set(m, range, p?.mjd ?? null);
  if (!m) return;
  const plx = m.parallax.mas === null ? "not fitted (too few visits)"
    : `${m.parallax.mas.toFixed(0)} ± ${m.parallax.err_mas!.toFixed(0)} mas${m.parallax.used ? "" : " (not detected; left out)"}`;
  const lines = [
    `μ α·cosδ  ${pm1(m.pmra, m.pmra_err)} mas/yr`,
    `μ δ       ${pm1(m.pmdec, m.pmdec_err)} mas/yr`,
    `parallax  ${plx}`,
    `position  ${formatDecimal(m.ra, m.dec, 6)}  at ${m.ref_epoch.toFixed(3)}`,
    `data      ${m.n_visits_used}/${m.n_visits} visits, ${m.n_exposures} exposures, ${mjdToEpoch(m.first_mjd).toFixed(1)}–${mjdToEpoch(m.last_mjd).toFixed(1)}`,
    `fit       χ²ᵣ ${m.chi2_red.toFixed(2)}, rms ${m.rms_mas?.toFixed(0) ?? "?"} mas per visit; started from ${m.seed}`,
  ];
  const pred = p ? predictions.get(p.mjd) : undefined;
  if (p && pred && plist?.grid) {
    const [gx, gy] = skyToGrid(plist.grid, pred.ra, pred.dec);
    const off = Math.hypot(gx - p.target_xy[0], gy - p.target_xy[1]) * plist.grid.scale_arcsec;
    lines.push("", `this image (${mjdToDate(p.mjd)}):`,
      `predicted ${formatDecimal(pred.ra, pred.dec, 6)}`,
      `95% ellipse ${((m.k95 * pred.a_mas) / 1000).toFixed(2)}″ × ${((m.k95 * pred.b_mas) / 1000).toFixed(2)}″ at PA ${pred.pa_deg.toFixed(0)}°`,
      `${off.toFixed(2)}″ from the crosshair (${(off / plist.grid.scale_arcsec).toFixed(2)} px)`);
  }
  $("motionread").textContent = lines.join("\n");
}

/** Make the fitted position and motion the tracked target (parallax is not tracked; the
 * prediction mark keeps showing it). */
function trackFittedMotion() {
  if (!motion) return;
  setMsg(`Tracking the WISE fit: μ=(${motion.pmra.toFixed(1)}, ${motion.pmdec.toFixed(1)}) mas/yr at ${motion.ref_epoch.toFixed(2)}`);
  update({ ra: Number(motion.ra.toFixed(7)), dec: Number(motion.dec.toFixed(7)), pm: true, pmra: Number(motion.pmra.toFixed(2)),
    pmdec: Number(motion.pmdec.toFixed(2)), pmep: Number(motion.ref_epoch.toFixed(4)), frame: 0 });
}

// ---------------------------------------------------------------------------------------
// Movers tab: CatWISE sources of the field ranked by the classifier
let movers: MoverList | null = null;
let moverKey = "";
let selectedMover: MoverCandidate | null = null;
let moverRows: MoverCandidate[] = [];

/** No Gaia star at the source, and a strong CatWISE motion. Outside Gaia the classifier
 * has confirmed movers to learn from (SIMBAD brown dwarfs) but no confirmed non-movers, so
 * its precision there cannot be measured. These are listed separately, by significance,
 * whatever their probability, so that a low score never hides one. */
const UNTESTED_MIN_SNR = 10;
const untested = (c: MoverCandidate) => !c.gaia && c.pm_snr >= UNTESTED_MIN_SNR;

function rankedMovers(): MoverCandidate[] {
  if (!movers) return [];
  const min = Number($("mvmin").value), hideKnown = $("mvnew").checked;
  return movers.candidates.filter((c) => c.prob >= min && !(hideKnown && c.gaia?.pm != null));
}
function untestedMovers(): MoverCandidate[] {
  const ranked = new Set(rankedMovers());
  return (movers?.candidates ?? []).filter((c) => untested(c) && !ranked.has(c)).sort((a, b) => b.pm_snr - a.pm_snr);
}
const visibleMovers = () => [...rankedMovers(), ...untestedMovers()];

async function refreshMovers() {
  if (!session?.grid) { renderMovers(); return; }
  const [ra, dec] = session.center;
  const radius = Math.min(30, (state.fov / 2) * Math.SQRT2 + 0.5);
  const key = `${session.id}|${ra}|${dec}|${radius}`;
  if (key === moverKey) { renderMovers(); return; }
  moverKey = key; movers = null; selectedMover = null;
  renderMovers("Reading CatWISE2020 and Gaia DR3 for this field…");
  try {
    const r = await api.movers(ra, dec, radius);
    if (key !== moverKey) return;
    movers = r;
    renderMovers();
  } catch (e) {
    if (key !== moverKey) return;
    moverKey = "";
    renderMovers(`Could not list candidates: ${(e as Error).message}`);
  }
}

function renderMovers(status?: string | Event) {
  $("mvminv").textContent = Number($("mvmin").value).toFixed(1);
  const note = typeof status === "string" ? status : "";
  const list = $("moverlist");
  if (!movers) {
    list.innerHTML = "";
    $("moverdetail").hidden = true;
    $("moverstate").textContent = note || (state.ra === null ? "Choose a target first: the candidates are listed for the field on show." : "");
    $("movermodel").textContent = "";
    player.draw();
    return;
  }
  const ranked = rankedMovers(), extra = untestedMovers();
  moverRows = [...ranked, ...extra];
  if (selectedMover && !moverRows.includes(selectedMover)) selectedMover = null;
  $("moverstate").textContent = note || `${ranked.length} of ${movers.n_candidates} CatWISE sources with a significant-looking motion pass the probability filter.`
    + (moverRows.length ? "" : " Lower the probability, or widen the field.");
  const f1 = (v: number | null | undefined, d = 1) => (v === null || v === undefined ? `<span class="none">–</span>` : v.toFixed(d));
  const head = `<tr><th>P(moving)</th><th title="CatWISE2020 total proper motion, mas/yr">μ CatWISE</th><th>S/N</th><th>W1</th><th>W2</th><th title="Gaia DR3 total proper motion of the counterpart, mas/yr">μ Gaia</th></tr>`;
  const row = (c: MoverCandidate, i: number) => `<tr data-i="${i}" aria-selected="${c === selectedMover}" title="${esc(c.id)}"><td><span class="pbar"><i style="width:${Math.round(c.prob * 100)}%"></i></span>${c.prob.toFixed(2)}</td>`
    + `<td>${c.pm.toFixed(0)} ± ${c.pm_err.toFixed(0)}</td><td>${c.pm_snr.toFixed(1)}</td><td>${f1(c.w1)}</td><td>${f1(c.w2)}</td>`
    + `<td>${c.gaia ? f1(c.gaia.pm, 0) : `<span class="none">not in Gaia</span>`}</td></tr>`;
  list.innerHTML = (ranked.length ? `<table>${head}${ranked.map(row).join("")}</table>` : "")
    + (extra.length ? `<h3>Not in Gaia, strong CatWISE motion <small>S/N ≥ ${UNTESTED_MIN_SNR}, by significance</small></h3>`
      + `<p class="hint">Listed whatever their probability. Outside Gaia the classifier's precision cannot be measured, so check these in the flipbook and with a WISE motion fit.</p>`
      + `<table>${head}${extra.map((c, i) => row(c, ranked.length + i)).join("")}</table>` : "");
  const m = movers.model;
  const pct = (x: number, d = 0) => (100 * x).toFixed(d);
  const bd = m.brown_dwarfs;
  $("movermodel").innerHTML = t("Gradient-boosted trees on {0} CatWISE2020 sources ({1} movers) from {2} random fields at |b| ≥ {3}°, trained {4}.",
      esc(String(m.n_train)), m.n_movers, m.n_fields, m.min_abs_glat, esc(m.trained)) + " "
    + t("Truth: Gaia DR3 proper motion ≥ {0} mas/yr.", m.mover_min_mas) + " "
    + t("Tested on fields held out of training: at P ≥ {0}, <b>{1}%</b> of flagged sources are real movers and <b>{2}%</b> of real movers are flagged (ranking by motion significance alone: {3}% and {4}%).",
      m.threshold, pct(m.cv.precision), pct(m.cv.recall), pct(m.baseline.precision), pct(m.baseline.recall)) + " "
    + (bd ? t("Plus {0} confirmed brown dwarfs from SIMBAD as movers Gaia cannot supply: held out of training, <b>{1}%</b> are flagged", bd.n_objects, pct(bd.cv_recall))
      + (bd.cv_recall_not_in_gaia !== null ? t(" (<b>{0}%</b> of those Gaia does not see)", pct(bd.cv_recall_not_in_gaia)) : "") + ". " : "")
    + t("Limits: for sources <i>not in Gaia</i> there are no confirmed non-movers, so the share of flagged sources that are real is unknown there")
    + (bd ? t(" (the model flags {0}% of such sources in random fields)", pct(bd.unlabelled_flagged, 2)) : "") + "; "
    + t("near the Galactic plane the model is outside its training range. Mid-infrared colour is deliberately not used.");
  showMoverDetail();
  player.draw();
}

function selectMover(i: number) {
  selectedMover = moverRows[i] === selectedMover ? null : moverRows[i] ?? null;
  for (const tr of document.querySelectorAll<HTMLElement>("#moverlist tr[data-i]"))
    tr.setAttribute("aria-selected", String(moverRows[Number(tr.dataset.i)] === selectedMover));
  showMoverDetail();
  player.draw();
}

function showMoverDetail() {
  const c = selectedMover, box = $("moverdetail");
  box.hidden = !c;
  if (!c) return;
  const g = c.gaia;
  box.innerHTML = `<b>CatWISE ${esc(c.id)}</b><pre>${esc([
    `P(moving ≥ ${movers?.model.mover_min_mas ?? 50} mas/yr)  ${c.prob.toFixed(3)}`,
    `position   ${formatDecimal(c.ra, c.dec, 5)}  at ${c.epoch.toFixed(1)}`,
    `μ CatWISE  (${c.pmra.toFixed(0)}, ${c.pmdec.toFixed(0)}) mas/yr, total ${c.pm.toFixed(0)} ± ${c.pm_err.toFixed(0)}`,
    `W1 ${c.w1?.toFixed(2) ?? "–"}  W2 ${c.w2?.toFixed(2) ?? "–"}${c.flagged ? "   ⚠ artifact flags set" : ""}`,
    g ? `Gaia DR3 ${g.id}: ${g.pm === null ? "no proper motion measured" : `μ (${g.pmra!.toFixed(1)}, ${g.pmdec!.toFixed(1)}) mas/yr, total ${g.pm.toFixed(1)}`}, G ${g.mag?.toFixed(1) ?? "?"}`
      : "No Gaia DR3 star within 1.5″: unconfirmed, and outside what the classifier was tested on.",
  ].join("\n"))}</pre><div class="actions"><button type="button" class="primary" id="moveropen">Open as target, with a WISE motion fit</button></div>`;
  $("moveropen").addEventListener("click", () => {
    setMsg(`CatWISE ${c.id}: tracking μ=(${c.pmra.toFixed(0)}, ${c.pmdec.toFixed(0)}) mas/yr`);
    update({ ra: c.ra, dec: c.dec, name: "", pm: true, pmra: Number(c.pmra.toFixed(1)), pmdec: Number(c.pmdec.toFixed(1)),
      pmep: Number(c.epoch.toFixed(4)), wfit: true, tab: "adv", view: "flipbook", frame: 0, pra: null, pdec: null });
    (document.getElementById("motionsec") as HTMLDetailsElement).open = true;
  });
}

async function loadCatalogs() {
  if (!session?.grid) return;
  const radius = Math.min(30, (state.fov / 2) * Math.SQRT2 + 0.5);
  const [ra, dec] = session.center;
  for (const [name] of CATALOGS) {
    if (!state[name]) { context?.setCatalog(name, "", "", null); player.draw(); continue; }
    if (!catalogs[name]) {
      try {
        catalogs[name] = (await api.catalog(name, ra, dec, radius)).sources;
      } catch (e) {
        setMsg(`${name} query failed: ${(e as Error).message}`, "warn");
        continue;
      }
    }
    player.draw();
  }
  updateContextCatalogs();
}

let lastContextUpdate = 0;
function throttledContextCatalogs() {
  if (Date.now() - lastContextUpdate > 1500) updateContextCatalogs();
}

function updateContextCatalogs() {
  lastContextUpdate = Date.now();
  if (!context) return;
  const mjd = shown[player.index]?.mjd ?? 61000;
  for (const [name, label, color] of CATALOGS) {
    const src = state[name] ? catalogs[name] : null;
    context.setCatalog(name, label, color, src ? src.map((s) => {
      const [ra, dec] = propagate(s, mjd);
      return { ra, dec, src: s };
    }) : null);
  }
}

// ---------------------------------------------------------------------------------------
// Photometry
function schedulePhot(delay: number) {
  if (delay === 0) { window.clearTimeout(photTimer); photTimer = undefined; refreshPhot(); return; }
  if (photTimer !== undefined) return;
  photTimer = window.setTimeout(() => { photTimer = undefined; refreshPhot(); }, delay);
}

async function refreshPhot() {
  if (!session) return;
  try {
    const r = await api.photometry(session.id, state);
    phot = r.rows;
    drawPlots();
    $<HTMLAnchorElement>("csv").href = api.photometryCsvUrl(session.id, state);
  } catch (e) {
    setMsg(`Photometry failed: ${(e as Error).message}`, "warn");
  }
}

function drawPlots() {
  plots.update(phot, [state.lcmin, state.lcmax], $("showflagged").checked);
  const sat = phot.filter((r) => r.saturated).length;
  const withheld = phot.filter((r) => r.flux_ujy === null).length;
  $("photnote").textContent = sat
    ? t("⚠ Target saturated in {0}/{1} frames (OVERFLOW in aperture)", sat, phot.length) +
      (withheld ? `; ${t("{0} fluxes withheld because the saturated core is blank", withheld)}` : "") +
      `. ${t("Aperture fluxes of saturated stars are not reliable.")}`
    : "";
  const tooBright = sat > phot.length / 2
    ? "This object is too bright for SPHEREx: the detector saturates on it, so its measured brightness isn't reliable. The images and its motion are still fine to look at."
    : "";
  $("basicnote").textContent = $("basicwarn").textContent = tooBright;
}

function showFrame(key: string | null) {
  const i = shown.findIndex((p) => p.key === key);
  if (i >= 0) { player.pause(); player.go(i); syncPlayButton(); if (state.view !== "flipbook") update({ view: "flipbook" }); }
  return i >= 0;
}

plots.onPick = (row) => {
  if (!showFrame(row.key) && state.mode !== "frames") update({ mode: "frames" });
};

// ---------------------------------------------------------------------------------------
function renderFrameList() {
  if (!session) return;
  const rows = [...session.records].sort((a, b) => a.mjd - b.mjd);
  $("obscount").textContent = `(${rows.length})`;
  $("framelist").innerHTML = `<table><tr><th>#</th><th>date (UTC)</th><th>MJD</th><th>det</th><th>λ (µm)</th><th>obs_id</th><th>collection</th><th>status</th><th>target flags</th></tr>` +
    rows.map((r, i) => `<tr class="${r.status === "error" ? "error" : ""}" data-key="${r.key}"><td>${i + 1}</td><td>${r.date}</td><td>${r.mjd.toFixed(4)}</td><td>D${r.detector}</td><td>${r.lam_um?.toFixed(3) ?? ""}</td><td>${r.obs_id}</td><td>${r.collection}</td><td title="${esc(r.error ?? "")}">${r.status}</td><td>${r.target_bad ? "⚠ " : ""}${(r.target_flag_names ?? []).join(",")}</td></tr>`).join("") + "</table>";
}

$("framelist").addEventListener("click", (e) => {
  const tr = (e.target as HTMLElement).closest("tr[data-key]") as HTMLElement | null;
  if (tr) showFrame(tr.dataset.key!);
});

window.addEventListener("resize", () => context?.resize());

async function init() {
  buildStaticControls();
  bindControls();
  player.fitInside($("canvaswrap"));
  new ResizeObserver(drawScaleBar).observe($("canvaswrap"));
  player.userZoom = Math.max(1, state.zoom);
  player.speed = state.speed;
  player.crosshair = state.xhair;
  player.lightSky = state.inv;
  writeControls();
  showPick();
  syncSphere();
  applyView(state.view);
  updateStage();
  try {
    const r = await api.releases();
    const sel = $<HTMLSelectElement>("rel");
    for (const rel of r.releases) {
      const o = document.createElement("option");
      o.value = rel;
      o.textContent = `${rel.toUpperCase()} only`;
      sel.appendChild(o);
    }
    sel.value = state.rel;
  } catch { /* backend not reachable: search will report it */ }
  if (state.ra !== null && state.dec !== null) startSession();
  else if (!hashStore.hasHash()) hashStore.write(state);
}

init();
