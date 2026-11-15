// Thin typed wrappers around the backend API.
import { ViewState, productParams } from "./state";

export const API = (window as unknown as { SPX_API?: string }).SPX_API ?? "";

export interface Grid { ra: number; dec: number; npix: number; scale_arcsec: number; center_pix: number }
export interface FlagBit { bit: number; name: string; description: string; default_bad: boolean }
export interface Progress {
  type: "progress"; state: string; total: number; done: number; loaded: number; failed: number;
  message: string;
}
export interface FrameRecord {
  key: string; obs_id: string; detector: number; collection: string; release: string; mjd: number;
  date: string; epoch: number; status: string; error?: string; lam_um?: number; bw_um?: number;
  target_flags?: number; target_flag_names?: string[]; target_bad?: boolean;
  header?: Record<string, unknown>; phot?: Record<string, unknown>; url?: string;
}
export interface Snapshot {
  id: string; params: Record<string, unknown>; target: Record<string, unknown>;
  center: [number, number]; grid: Grid | null; warnings: string[]; errors: string[];
  progress: Progress; records: FrameRecord[]; flag_bits: FlagBit[];
}
export interface ProductInfo {
  index: number; label: string; n: number; mjd: number; mjd_range: [number, number]; date: string;
  detectors: number[]; lam_um: number; lam_range_um: [number, number]; bw_um: number | null;
  obs_id: string | null; key: string | null; epoch_index: number | null;
  target_xy: [number, number]; target_flags: number; target_flag_names: string[];
  target_bad: boolean; n_members_flagged: number;
}
export interface ProductList {
  products: ProductInfo[]; limits: { vmin?: number; vmax?: number; channels?: [number, number][] };
  grid: Grid | null; progress: Progress; mode: string;
}
export interface PhotRow {
  key: string; obs_id: string; detector: number; mjd: number; date: string; epoch_index: number;
  lam_um: number; bw_um: number; flux_ujy: number | null; err_ujy: number | null; ok: boolean;
  saturated: boolean; n_bad_ap: number; frac_missing: number; ap_flag_names: string[];
  target_flag_names: string[]; note: string;
}
export interface Suggestion {
  label: string; main_id: string; ra: number; dec: number; pmra: number; pmdec: number;
  type: string; source: "index" | "simbad";
}
export interface CatSource {
  id: string; ra: number; dec: number; pmra: number | null; pmdec: number | null;
  epoch: number | null; mag: number | null; mag2?: number | null;
}

/** Fit to the WISE/NEOWISE epochs of one object (backend processing/astrometry.py). */
export interface WiseVisit {
  mjd: number; epoch: number; n: number; used: boolean;
  dxi_mas: number; deta_mas: number; sig_xi_mas: number; sig_eta_mas: number;   // minus straight-line motion
}
/** Predicted position at one date, with its 1-sigma error ellipse (PA east of north). */
export interface WisePrediction { mjd: number; ra: number; dec: number; a_mas: number; b_mas: number; pa_deg: number }
export interface WiseMotion {
  n_exposures: number; n_visits: number; n_visits_used: number; n_visits_available: number;
  first_mjd: number; last_mjd: number; span_yr: number; ref_epoch: number; ra: number; dec: number;
  pmra: number; pmdec: number; pmra_err: number; pmdec_err: number; pm: number;
  parallax: { used: boolean; mas: number | null; err_mas: number | null };
  chi2_red: number; rms_mas: number | null; k95: number; seed: string; warnings: string[];
  visits: WiseVisit[];
  curve: { mjd: number[]; xi_mas: number[]; eta_mas: number[]; sig_xi_mas: number[]; sig_eta_mas: number[] };
  predictions: WisePrediction[];
}
export interface MoverCandidate {
  id: string; ra: number; dec: number; epoch: number; prob: number;
  pmra: number; pmdec: number; pm: number; pm_err: number; pm_snr: number;
  w1: number | null; w2: number | null; flagged: boolean;
  gaia: { id: string; pmra: number | null; pmdec: number | null; pm: number | null; mag: number | null; sep_arcsec: number } | null;
}
export interface MoverModel {
  trained: string; n_fields: number; n_train: number; n_movers: number; mover_min_mas: number;
  min_pm_snr: number; min_abs_glat: number; threshold: number;
  cv: { roc_auc: number; average_precision: number; precision: number; recall: number };
  baseline: { roc_auc: number; average_precision: number; precision: number; recall: number };
  /** Confirmed SIMBAD brown dwarfs added as positives (null if the model was trained without). */
  brown_dwarfs: { n_objects: number; cv_recall: number; cv_recall_not_in_gaia: number | null;
    unlabelled_n: number; unlabelled_flagged: number } | null;
}
export interface MoverList { candidates: MoverCandidate[]; n_candidates: number; epoch: number; model: MoverModel }

function photParams(s: ViewState): URLSearchParams {
  const p = productParams(s);
  p.set("r_ap", String(s.ap)); p.set("r_in", String(Math.max(5, s.ap + 2))); p.set("r_out", String(Math.max(9, s.ap + 6)));
  return p;
}

async function json<T>(r: Response): Promise<T> {
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`;
    try { msg = (await r.json()).detail ?? msg; } catch { /* not JSON */ }
    throw new Error(msg);
  }
  return r.json() as Promise<T>;
}

export const api = {
  releases: () => fetch(`${API}/api/releases`).then((r) => json<{ releases: string[]; collections: { name: string; label: string; release: string; variant: string }[] }>(r)),
  resolve: (q: string) => fetch(`${API}/api/resolve?q=${encodeURIComponent(q)}`).then((r) =>
    json<{ ra: number; dec: number; pmra: number; pmdec: number; epoch: number; name: string; source: string; sexagesimal: string }>(r)),
  gaiaPm: (ra: number, dec: number, epoch: number) =>
    fetch(`${API}/api/gaia_pm?ra=${ra}&dec=${dec}&epoch=${epoch}`).then((r) => json<CatSource & { sep_arcsec: number }>(r)),
  createSession: (s: ViewState) => fetch(`${API}/api/sessions`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ra: s.ra, dec: s.dec, fov: s.fov, pm: s.pm, pmra: s.pmra, pmdec: s.pmdec,
      epoch: s.pmep, release: s.rel, deep: s.deep, name: s.name || null }),
  }).then((r) => json<Snapshot>(r)),
  snapshot: (sid: string) => fetch(`${API}/api/sessions/${sid}`).then((r) => json<Snapshot>(r)),
  retry: (sid: string) => fetch(`${API}/api/sessions/${sid}/retry`, { method: "POST" }).then((r) => json(r)),
  products: (sid: string, s: ViewState) =>
    fetch(`${API}/api/sessions/${sid}/products?${productParams(s)}`).then((r) => json<ProductList>(r)),
  photometry: (sid: string, s: ViewState) =>
    fetch(`${API}/api/sessions/${sid}/photometry?${photParams(s)}`).then((r) => json<{ rows: PhotRow[]; n_epochs: number }>(r)),
  photometryCsvUrl: (sid: string, s: ViewState) => `${API}/api/sessions/${sid}/photometry?${photParams(s)}&format=csv`,
  catalog: (name: string, ra: number, dec: number, radius: number) =>
    fetch(`${API}/api/catalog/${name}?ra=${ra}&dec=${dec}&radius=${radius}`).then((r) => json<{ sources: CatSource[]; label: string }>(r)),
  wiseMotion: (body: { ra: number; dec: number; epoch: number; pmra: number; pmdec: number; mjds: number[] }) =>
    fetch(`${API}/api/wise_motion`, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body) }).then((r) => json<WiseMotion>(r)),
  movers: (ra: number, dec: number, radius: number) =>
    fetch(`${API}/api/movers?ra=${ra}&dec=${dec}&radius=${radius}`).then((r) => json<MoverList>(r)),
  /** A frame, stack or difference image as lossless WebP (FITS is a separate, explicit download). */
  imageUrl: (sid: string, s: ViewState, pid: number | string, limits: { vmin: number; vmax: number }, nLoaded: number) => {
    const p = productParams(s);
    p.set("stretch", s.stretch);
    p.set("vmin", String(s.vmin ?? limits.vmin));
    p.set("vmax", String(s.vmax ?? limits.vmax));
    if (s.inv) p.set("invert", "true");
    if (s.flag !== "off") { p.set("flagmode", s.flag); p.set("flagbits", s.fbits.join(",")); }
    // Stacks/differences change as frames arrive; single frames do not.
    if (s.mode !== "frames" || s.diff !== "none") p.set("n", String(nLoaded));
    return `${API}/api/sessions/${sid}/products/${encodeURIComponent(String(pid))}.webp?${p}`;
  },
  fitsUrl: (sid: string, s: ViewState, pid: number | string) =>
    `${API}/api/sessions/${sid}/products/${encodeURIComponent(String(pid))}.fits?${productParams(s)}`,
  suggest: (q: string, live = false) =>
    fetch(`${API}/api/suggest?q=${encodeURIComponent(q)}${live ? "&live=1" : ""}`).then((r) => json<{ items: Suggestion[]; note: string | null }>(r)),
  events: (sid: string) => new EventSource(`${API}/api/sessions/${sid}/events`),
};
