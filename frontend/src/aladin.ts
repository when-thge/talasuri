// Aladin Lite v3 (CDS) context view: HiPS backgrounds, catalog overlays, the cutout footprint.
import type { CatSource, Grid } from "./api";
import type { Hips } from "./state";

/* eslint-disable @typescript-eslint/no-explicit-any */
let A: any = null;

// The CDS-hosted ".../api/v3/latest/aladin.js" path returned 404 (Nov 2026); the npm build
// is an ES module whose default export is the `A` namespace. Pinned for reproducibility.
const ALADIN_JS = "https://cdn.jsdelivr.net/npm/aladin-lite@3.8.2/dist/aladin.js";

// HiPS service URLs, in order of preference. URLs rather than IDs because ID resolution goes
// through CDS mirror lists; the IRSA copies keep context imagery working when CDS is down.
const SPHEREX_HIPS = "https://irsa.ipac.caltech.edu/data/hips/SPHEREx/spherex_allsky_cube";
// The same map re-served by this app's backend one slice at a time, as plain image HiPS
// (backend data_access/hips.py): Aladin keeps coarser tiles on screen while zooming for
// those, but blanks a cube until every new tile arrives; the backend also caches tiles.
const SPHEREX_SLICES = new URL("api/hips/spherex", document.baseURI).href;
// Shown until a frame is chosen: 2.2 um, where stars are bright and dust extinction is low.
const SPHEREX_DEFAULT_UM = 2.2;

// ``sliced``: ``{url}/properties`` describes a cube, and ``{url}/{k}`` is slice k as an image HiPS.
export const HIPS_URLS: Record<Hips, { label: string; urls: string[]; sliced?: boolean }[]> = {
  spherex: [{ label: "SPHEREx DR1 all-sky", urls: [SPHEREX_SLICES], sliced: true },
    { label: "SPHEREx DR1 all-sky (direct from IRSA)", urls: [SPHEREX_HIPS] }],
  unwise: [
    { label: "unWISE color", urls: ["https://alasky.cds.unistra.fr/unWISE/color-W2-W1W2-W1"] },
    { label: "AllWISE color (unWISE unavailable)", urls: ["https://irsa.ipac.caltech.edu/data/hips/CDS/AllWISE/RGB-W4-W2-W1"] },
  ],
  "2mass": [{ label: "2MASS color", urls: ["https://alasky.cds.unistra.fr/2MASS/Color",
    "https://irsa.ipac.caltech.edu/data/hips/CDS/2MASS/Color"] }],
  dss: [{ label: "DSS2 color", urls: ["https://alasky.cds.unistra.fr/DSS/DSSColor",
    "https://alaskybis.cds.unistra.fr/DSS/DSSColor"] }],
  none: [{ label: "Mellinger optical", urls: ["https://alasky.cds.unistra.fr/MellingerRGB"] }],
};

interface HipsPick { label: string; url: string; waves: number[] | null; em: [number, number] | null; sliced: boolean }

/** First candidate whose HiPS `properties` file answers. For a cube, also its slice
 *  wavelengths (um), which the SPHEREx cube lists in `data_cube_crval3_arr`. */
async function pickHips(h: Hips): Promise<HipsPick | null> {
  for (const c of HIPS_URLS[h]) {
    for (const url of c.urls) {
      try {
        const r = await fetch(`${url}/properties`, { signal: AbortSignal.timeout(8000) });
        if (!r.ok) continue;
        const text = await r.text();
        const prop = (k: string) => text.match(new RegExp(`^${k}\\s*=\\s*(.+)$`, "m"))?.[1].trim();
        const waves = prop("data_cube_crval3_arr")?.split(/\s+/).map(Number);
        const em = [Number(prop("em_min")), Number(prop("em_max"))].sort((a, b) => a - b) as [number, number];
        const cube = !!waves?.length && waves.every(Number.isFinite) && em.every((v) => v > 0);
        if (c.sliced && !cube) continue;
        return { label: c.label, url, waves: cube ? waves! : null, em: cube ? em : null, sliced: !!c.sliced };
      } catch { /* try the next mirror */ }
    }
  }
  return null;
}

let loading: Promise<void> | null = null;
function loadScript(): Promise<void> {
  if (!loading) {
    const url = ALADIN_JS;  // non-literal specifier: esbuild leaves this import to the browser
    loading = import(url).then((m) => { A = m.default; });
  }
  return loading;
}

export class Context {
  private al: any = null;
  private overlay: any = null;
  private pickOverlay: any = null;
  private cats = new Map<string, any>();
  private pickHandler: ((ra: number, dec: number) => void) | null = null;
  private hips: any = null;              // the current background layer
  private waves: number[] | null = null; // its slice wavelengths, if it is a cube
  private em: [number, number] = [1, 1]; // its em_min, em_max (m)
  private blank = new Set<number>();    // slices with no data
  private label = "";
  private wantUm = SPHEREX_DEFAULT_UM;
  private sliced: string | null = null;  // base URL of per-slice image HiPS, if in use
  private shownSlice: number | null = null;
  ready: Promise<void>;

  constructor(div: HTMLElement) {
    this.ready = loadScript().then(() => A.init).then(() => {
      this.al = A.aladin(div, {
        // Start on an IRSA-hosted survey so Aladin doesn't fetch its default (CDS DSS) first;
        // setHips() then switches to the chosen one (and its wavelength slice).
        // Opens on a wide view (Orion) so it reads as a sky map to pick from.
        survey: "https://irsa.ipac.caltech.edu/data/hips/CDS/2MASS/Color", fov: 40,
        target: "83.82 -5.39", cooFrame: "ICRSd", showReticle: false,
        showCooGrid: false, showLayersControl: false, showGotoControl: false,
        showFullscreenControl: false, showProjectionControl: false, showFrame: false,
        showZoomControl: true,
      });
      this.overlay = A.graphicOverlay({ color: "#ff5a4e", lineWidth: 1.5 });
      this.al.addOverlay(this.overlay);
      this.pickOverlay = A.graphicOverlay({ color: "#f2b544", lineWidth: 2 });
      this.al.addOverlay(this.pickOverlay);
      // A click (not the end of a drag) picks a position.
      this.al.on("click", (e: { ra: number; dec: number; isDragging?: boolean }) => {
        if (!e || e.isDragging || !Number.isFinite(e.ra)) return;
        this.pickHandler?.(((e.ra % 360) + 360) % 360, e.dec);
      });
    }).catch((e) => { div.textContent = `Aladin Lite unavailable: ${e?.message ?? e}`; });
  }

  async show(grid: Grid, fovArcmin: number) {
    await this.ready;
    if (!this.al) return;
    this.pickOverlay.removeAll();
    this.al.gotoRaDec(grid.ra, grid.dec);
    this.al.setFoV((fovArcmin * 2.2) / 60);
    // Footprint of the flipbook grid (TAN, north up).
    this.overlay.removeAll();
    this.overlay.add(A.polygon(square(grid.ra, grid.dec, (grid.npix * grid.scale_arcsec) / 2 / 3600)));
  }

  /** Called with (ra, dec) when the user clicks the sky. */
  onPick(fn: (ra: number, dec: number) => void) { this.pickHandler = fn; }

  /** Outline the field that would be loaded at a picked position. */
  async markPick(ra: number, dec: number, fovArcmin: number) {
    await this.ready;
    if (!this.al) return;
    this.pickOverlay.removeAll();
    this.pickOverlay.add(A.polygon(square(ra, dec, fovArcmin / 2 / 60)));
    // Zoom in enough to see the outline, but never zoom out the user's view.
    if (this.al.getFov()[0] > 3) this.al.setFoV(Math.max(fovArcmin / 60 * 6, 0.5));
    this.al.gotoRaDec(ra, dec);
  }

  /** Aladin needs a nudge after its container was hidden (tab switch). */
  async resize() {
    await this.ready;
    this.al?.view?.fixLayoutDimensions?.();
  }

  /** Returns a status line for the UI (which survey is shown, or why none is). */
  async setHips(h: Hips): Promise<string> {
    await this.ready;
    if (!this.al) return "Aladin Lite unavailable";
    const pick = await pickHips(h);
    if (!pick) return `Background ${h}: no HiPS server reachable`;
    this.waves = pick.waves;
    if (pick.em) this.em = pick.em;
    // The SPHEREx cube's frames 50 and 51 (band 3 ch 17, band 4 ch 1: the dichroic
    // channels, 2.40 and 2.45 um) are blank, per its obs_description.
    this.blank = new Set(h === "spherex" ? [50, 51] : []);
    this.label = pick.label;
    this.sliced = pick.sliced ? pick.url : null;
    this.shownSlice = null;
    if (this.sliced) { this.showSliced(); return this.note(); }
    const slice = this.slice();
    const layer = A.imageHiPS(pick.url, {
      // the slice only takes effect once the layer is in the view
      successCallback: () => { if (slice !== null) this.showSlice(layer, slice); },
    });
    this.hips = layer;
    this.al.setImageSurvey(layer);
    return this.note();
  }

  /** Show the cube slice nearest ``um`` (no-op for single-image backgrounds). */
  setWavelength(um: number): string {
    this.wantUm = um;
    if (this.sliced) { this.showSliced(); return this.note(); }
    const slice = this.slice();
    if (slice !== null && this.hips) this.showSlice(this.hips, slice);
    return this.note();
  }

  /** Switch to the per-slice image HiPS of the slice nearest the wanted wavelength. */
  private showSliced() {
    const k = this.slice();
    if (k === null || k === this.shownSlice) return;
    this.shownSlice = k;
    this.hips = A.imageHiPS(`${this.sliced}/${k}`, { name: `${this.label}, ${this.waves![k].toFixed(2)} µm` });
    this.al.setImageSurvey(this.hips);
  }

  /** Aladin's setSliceNumber() assumes slices evenly spaced in wavelength, but its renderer
   *  picks the tile slice as floor(depth * (f - f_min) / (f_max - f_min)), evenly spaced in
   *  frequency, so slice 46 loaded tiles _15. Ask for the frequency in the middle of the
   *  wanted slice instead (checked against the tile URLs Aladin 3.8.2 requests). */
  private showSlice(layer: any, slice: number) {
    const c = 299792458, fmin = c / this.em[1], fmax = c / this.em[0];
    layer.setFrequency({ value: fmin + ((slice + 0.5) / this.waves!.length) * (fmax - fmin), unit: "Hz" });
  }

  /** Index of the non-blank cube slice nearest ``um`` (default: the wanted wavelength). */
  private slice(um = this.wantUm): number | null {
    if (!this.waves) return null;
    let best = -1;
    this.waves.forEach((w, i) => {
      if (this.blank.has(i)) return;
      if (best < 0 || Math.abs(w - um) < Math.abs(this.waves![best] - um)) best = i;
    });
    return best;
  }

  private note(): string {
    const i = this.slice();
    return i === null ? this.label : `${this.label}, λ ${this.waves![i].toFixed(2)} µm`;
  }

  /** Replace a catalog layer. Positions should already be propagated to the frame epoch. */
  async setCatalog(name: string, label: string, color: string, sources: { ra: number; dec: number; src: CatSource }[] | null) {
    await this.ready;
    if (!this.al) return;
    let cat = this.cats.get(name);
    if (!sources) { if (cat) cat.hide(); return; }
    if (!cat) {
      cat = A.catalog({ name: label, color, sourceSize: 10, shape: "circle", onClick: "showPopup" });
      this.al.addCatalog(cat);
      this.cats.set(name, cat);
    }
    cat.removeAll();
    cat.addSources(sources.map((s) => A.source(s.ra, s.dec, {
      id: s.src.id, mag: s.src.mag?.toFixed(2) ?? "", pmra: s.src.pmra?.toFixed(1) ?? "",
      pmdec: s.src.pmdec?.toFixed(1) ?? "" })));
    cat.show();
  }
}

/** Corners of a north-up square of half-size ``h`` degrees. */
function square(ra: number, dec: number, h: number): [number, number][] {
  const c = Math.cos((dec * Math.PI) / 180);
  return [[ra + h / c, dec - h], [ra - h / c, dec - h], [ra - h / c, dec + h], [ra + h / c, dec + h]];
}
