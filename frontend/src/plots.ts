// Spectrum (flux vs wavelength, coloured by epoch) and light curve (flux vs time), drawn
// directly on a 2D canvas: points with error bars, a legend that toggles series, a hover
// tooltip and click-to-pick. (This replaced Chart.js, which was ~200 kB for two scatter plots.)
import { t } from "./i18n";
import type { PhotRow } from "./api";

// Epochs are ordered in time, so they get a one-hue ordinal ramp (darkest = earliest),
// not categorical hues.
const BLUE_RAMP = ["#3f69a8", "#4f79b8", "#6189c6", "#7499d3", "#8fb3e8", "#adc7ee", "#cbdbf3", "#e9eef5"];
const INK = { primary: "#e9eef5", secondary: "#a9b6c9", grid: "rgba(169,182,201,.12)", err: "#7d8ba1", bg: "#0a1220" };
const FONT = "11px 'JetBrains Mono', ui-monospace, monospace";
const LABEL_FONT = "12px 'Public Sans', system-ui, sans-serif";

export function epochColor(i: number, n: number): string {
  if (n <= 1) return BLUE_RAMP[3];
  return BLUE_RAMP[Math.round((i / (n - 1)) * (BLUE_RAMP.length - 1))];
}

interface Pt { x: number; y: number; err: number; row: PhotRow }
interface Series { label: string; color: string; points: Pt[]; line?: boolean }

/** Tick values at a "nice" step (1, 2 or 5 x 10^k) covering [lo, hi]. */
export function ticks(lo: number, hi: number, target: number): number[] {
  const raw = (hi - lo) / Math.max(target, 1);
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw;
  const out: number[] = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + step * 1e-9; v += step) out.push(Math.abs(v) < step * 1e-9 ? 0 : v);
  return out;
}
export const tickText = (v: number, step: number) =>
  Math.abs(v) >= 1e5 ? v.toExponential(1) : v.toFixed(Math.max(0, Math.min(4, -Math.floor(Math.log10(step) + 1e-9))));

class Scatter {
  series: Series[] = [];
  xTitle = "";
  private hidden = new Set<string>();
  private hover: Pt | null = null;
  private legendBoxes: { label: string; x: number; y: number; w: number }[] = [];
  private area = { l: 0, t: 0, w: 0, h: 0, x0: 0, x1: 1, y0: 0, y1: 1 };
  private ctx: CanvasRenderingContext2D;

  constructor(private canvas: HTMLCanvasElement, private title: string, private onPick: (row: PhotRow) => void) {
    this.ctx = canvas.getContext("2d")!;
    canvas.setAttribute("role", "img");
    new ResizeObserver(() => this.draw()).observe(canvas.parentElement ?? canvas);
    canvas.addEventListener("mousemove", (e) => {
      const hit = this.nearest(e);
      if (hit !== this.hover) { this.hover = hit; this.draw(); }
      canvas.style.cursor = hit || this.legendAt(e) ? "pointer" : "default";
    });
    canvas.addEventListener("mouseleave", () => { if (this.hover) { this.hover = null; this.draw(); } });
    canvas.addEventListener("click", (e) => {
      const legend = this.legendAt(e);
      if (legend) {
        if (!this.hidden.delete(legend)) this.hidden.add(legend);
        this.draw();
        return;
      }
      const hit = this.nearest(e);
      if (hit) this.onPick(hit.row);
    });
  }

  private pos(e: MouseEvent): [number, number] {
    const r = this.canvas.getBoundingClientRect();
    return [e.clientX - r.left, e.clientY - r.top];
  }
  private px(p: Pt): [number, number] {
    const a = this.area;
    return [a.l + ((p.x - a.x0) / (a.x1 - a.x0)) * a.w, a.t + a.h - ((p.y - a.y0) / (a.y1 - a.y0)) * a.h];
  }
  private visible(): Series[] { return this.series.filter((s) => !this.hidden.has(s.label)); }
  private nearest(e: MouseEvent): Pt | null {
    const [mx, my] = this.pos(e);
    let best: Pt | null = null, bestD = 9;
    for (const s of this.visible()) for (const p of s.points) {
      const [x, y] = this.px(p);
      const d = Math.hypot(x - mx, y - my);
      if (d < bestD) { bestD = d; best = p; }
    }
    return best;
  }
  private legendAt(e: MouseEvent): string | null {
    const [mx, my] = this.pos(e);
    return this.legendBoxes.find((b) => mx >= b.x && mx <= b.x + b.w && my >= b.y - 8 && my <= b.y + 8)?.label ?? null;
  }

  draw() {
    const { canvas, ctx } = this;
    const box = canvas.parentElement ?? canvas;
    const w = box.clientWidth, h = box.clientHeight;
    if (!w || !h) return;
    const dpr = window.devicePixelRatio || 1;
    if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
      canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
      canvas.style.width = `${w}px`; canvas.style.height = `${h}px`;
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    const n = this.series.reduce((s, x) => s + (x.line ? 0 : x.points.length), 0);
    canvas.setAttribute("aria-label", t("{0}: {1} measurements in {2} epochs", t(this.title), n, this.series.filter((s) => !s.line).length));

    // Legend (wraps; click a name to hide or show that series).
    ctx.font = LABEL_FONT;
    ctx.textBaseline = "middle";
    this.legendBoxes = [];
    let lx = 8, ly = 12;
    for (const s of this.series) {
      const tw = ctx.measureText(s.label).width + 26;
      if (lx + tw > w - 4 && lx > 8) { lx = 8; ly += 17; }
      const off = this.hidden.has(s.label);
      ctx.globalAlpha = off ? 0.35 : 1;
      ctx.fillStyle = s.color;      // swatches are always filled (points may be hollow = flagged)
      ctx.beginPath();
      if (s.line) ctx.rect(lx + 1, ly - 4, 8, 8); else ctx.arc(lx + 5, ly, 4.5, 0, 2 * Math.PI);
      ctx.fill();
      ctx.fillStyle = INK.secondary;
      ctx.fillText(s.label, lx + 15, ly + 0.5);
      if (off) { ctx.strokeStyle = INK.secondary; ctx.beginPath(); ctx.moveTo(lx + 15, ly); ctx.lineTo(lx + tw - 11, ly); ctx.stroke(); }
      ctx.globalAlpha = 1;
      this.legendBoxes.push({ label: s.label, x: lx, y: ly, w: tw - 8 });
      lx += tw;
    }

    const a = this.area;
    a.l = 58; a.t = ly + 14; a.w = w - a.l - 12; a.h = h - a.t - 36;
    const pts = this.visible().flatMap((s) => s.points);
    if (a.w < 40 || a.h < 30) return;
    if (!pts.length) {
      ctx.fillStyle = INK.secondary; ctx.textAlign = "center";
      ctx.fillText(t(this.series.length ? "All series hidden" : "No measurements yet"), a.l + a.w / 2, a.t + a.h / 2);
      ctx.textAlign = "left";
      return;
    }
    const span = (lo: number, hi: number) => { const d = hi - lo || Math.abs(hi) || 1; return [lo - 0.05 * d, hi + 0.05 * d]; };
    [a.x0, a.x1] = span(Math.min(...pts.map((p) => p.x)), Math.max(...pts.map((p) => p.x)));
    const errOf = (p: Pt) => (Number.isFinite(p.err) ? p.err : 0);
    [a.y0, a.y1] = span(Math.min(...pts.map((p) => p.y - errOf(p))), Math.max(...pts.map((p) => p.y + errOf(p))));

    // Axes, grid and tick labels.
    ctx.font = FONT; ctx.lineWidth = 1;
    const xt = ticks(a.x0, a.x1, Math.max(2, Math.floor(a.w / 80))), yt = ticks(a.y0, a.y1, Math.max(3, Math.floor(a.h / 30)));
    const xs = xt.length > 1 ? xt[1] - xt[0] : 1, ys = yt.length > 1 ? yt[1] - yt[0] : 1;
    ctx.strokeStyle = INK.grid; ctx.fillStyle = INK.secondary;
    ctx.beginPath();
    ctx.textAlign = "center"; ctx.textBaseline = "top";
    for (const v of xt) {
      const x = Math.round(a.l + ((v - a.x0) / (a.x1 - a.x0)) * a.w) + 0.5;
      ctx.moveTo(x, a.t); ctx.lineTo(x, a.t + a.h);
      ctx.fillText(tickText(v, xs), x, a.t + a.h + 5);
    }
    ctx.textAlign = "right"; ctx.textBaseline = "middle";
    for (const v of yt) {
      const y = Math.round(a.t + a.h - ((v - a.y0) / (a.y1 - a.y0)) * a.h) + 0.5;
      ctx.moveTo(a.l, y); ctx.lineTo(a.l + a.w, y);
      ctx.fillText(tickText(v, ys), a.l - 6, y);
    }
    ctx.stroke();
    ctx.strokeStyle = "rgba(169,182,201,.4)";
    ctx.strokeRect(a.l + 0.5, a.t + 0.5, a.w, a.h);
    ctx.font = LABEL_FONT; ctx.textAlign = "center"; ctx.textBaseline = "alphabetic";
    ctx.fillText(t(this.xTitle), a.l + a.w / 2, h - 5);
    ctx.save(); ctx.translate(12, a.t + a.h / 2); ctx.rotate(-Math.PI / 2);
    ctx.fillText(t("Flux density (µJy)"), 0, 0); ctx.restore();
    ctx.textAlign = "left";

    ctx.save();
    ctx.beginPath(); ctx.rect(a.l, a.t, a.w, a.h); ctx.clip();
    // Error bars under the points.
    ctx.strokeStyle = INK.err; ctx.lineWidth = 1;
    ctx.beginPath();
    for (const s of this.visible()) for (const p of s.points) {
      if (!Number.isFinite(p.err)) continue;
      const [x] = this.px(p);
      ctx.moveTo(x, this.px({ ...p, y: p.y - p.err })[1]); ctx.lineTo(x, this.px({ ...p, y: p.y + p.err })[1]);
    }
    ctx.stroke();
    for (const s of this.visible()) {
      ctx.strokeStyle = s.color; ctx.fillStyle = s.color;
      if (s.line) {
        ctx.lineWidth = 2; ctx.beginPath();
        s.points.forEach((p, i) => { const [x, y] = this.px(p); if (i) ctx.lineTo(x, y); else ctx.moveTo(x, y); });
        ctx.stroke();
      }
      ctx.lineWidth = 1.5;
      for (const p of s.points) {
        const [x, y] = this.px(p), r = p === this.hover ? 6 : s.line ? 5 : 4;
        ctx.beginPath();
        if (s.line) { ctx.moveTo(x, y - r); ctx.lineTo(x + r, y); ctx.lineTo(x, y + r); ctx.lineTo(x - r, y); ctx.closePath(); }
        else ctx.arc(x, y, r, 0, 2 * Math.PI);
        // Flagged measurements are hollow, so flag status is not carried by colour alone.
        if (s.line || p.row.ok) ctx.fill(); else { ctx.fillStyle = INK.bg; ctx.fill(); ctx.fillStyle = s.color; }
        ctx.stroke();
      }
    }
    ctx.restore();

    if (this.hover) this.tooltip(this.hover, w);
  }

  private tooltip(p: Pt, w: number) {
    const { ctx } = this, r = p.row;
    const lines = [`${r.date}  D${r.detector}  λ=${r.lam_um.toFixed(3)} µm`,
      `${p.y.toFixed(1)} ± ${Number.isFinite(p.err) ? p.err.toFixed(1) : "?"} µJy`];
    if (!r.ok) lines.push(`⚠ ${r.note || r.target_flag_names.join(",")}`.slice(0, 60));
    ctx.font = FONT;
    const tw = Math.max(...lines.map((l) => ctx.measureText(l).width)) + 14, th = lines.length * 15 + 8;
    const [x, y] = this.px(p);
    const bx = Math.max(4, Math.min(w - tw - 4, x + 10)), by = Math.max(4, y - th - 8);
    ctx.fillStyle = "rgba(13,22,38,.96)"; ctx.strokeStyle = "#3a4b66"; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.rect(bx + 0.5, by + 0.5, tw, th); ctx.fill(); ctx.stroke();
    ctx.textBaseline = "top";
    lines.forEach((l, i) => { ctx.fillStyle = i === 2 ? "#f2b544" : INK.primary; ctx.fillText(l, bx + 7, by + 6 + i * 15); });
  }
}

function pointsByEpoch(rows: PhotRow[], x: (r: PhotRow) => number, showFlagged: boolean): Series[] {
  const nEp = Math.max(0, ...rows.map((r) => r.epoch_index ?? 0)) + 1;
  const out: Series[] = [];
  for (let e = 0; e < nEp; e++) {
    const rs = rows.filter((r) => (r.epoch_index ?? 0) === e && r.flux_ujy !== null && (showFlagged || r.ok));
    if (!rs.length) continue;
    out.push({ label: t("Epoch {0} ({1})", e + 1, rs[0].date.slice(0, 10)), color: epochColor(e, nEp),
      points: rs.map((r) => ({ x: x(r), y: r.flux_ujy!, err: r.err_ujy ?? NaN, row: r })) });
  }
  return out;
}

export class Plots {
  private spectrum: Scatter;
  private lightcurve: Scatter;
  onPick: (row: PhotRow) => void = () => {};

  constructor(specCanvas: HTMLCanvasElement, lcCanvas: HTMLCanvasElement) {
    const pick = (r: PhotRow) => this.onPick(r);
    this.spectrum = new Scatter(specCanvas, "Spectrum", pick);
    this.spectrum.xTitle = "Wavelength (µm)";
    this.lightcurve = new Scatter(lcCanvas, "Light curve", pick);
  }

  update(rows: PhotRow[], lcRange: [number | null, number | null], showFlagged: boolean) {
    this.spectrum.series = pointsByEpoch(rows, (r) => r.lam_um, showFlagged);
    this.spectrum.draw();

    const [lo, hi] = lcRange;
    const lc = rows.filter((r) => (lo === null || r.lam_um >= lo) && (hi === null || r.lam_um <= hi));
    const ds = pointsByEpoch(lc, (r) => r.mjd, showFlagged);
    // Inverse-variance weighted mean per epoch, as a line over the individual points.
    const means: Pt[] = [];
    for (const d of ds) {
      const pts = d.points.filter((p) => p.row.ok && p.err > 0);
      if (!pts.length) continue;
      const wts = pts.map((p) => 1 / p.err ** 2);
      const sw = wts.reduce((a, b) => a + b, 0);
      means.push({ x: pts.reduce((a, p, i) => a + p.x * wts[i], 0) / sw,
        y: pts.reduce((a, p, i) => a + p.y * wts[i], 0) / sw, err: Math.sqrt(1 / sw), row: pts[0].row });
    }
    this.lightcurve.series = means.length ? [...ds, { label: t("Epoch mean"), color: INK.primary, points: means, line: true }] : ds;
    this.lightcurve.xTitle = lo === null && hi === null ? "MJD (all wavelengths)" : `MJD (λ ${lo ?? "…"}–${hi ?? "…"} µm)`;
    this.lightcurve.draw();
  }
}
