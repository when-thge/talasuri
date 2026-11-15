// The motion-fit plot: what the WISE visits measured and how well the fit predicts later
// dates. Two stacked panels (east and north), each showing position minus the fitted
// straight-line motion against time: the visits with their errors, the fitted parallax
// wobble (flat when no parallax was detected) and the ±1σ band of the predicted position,
// which widens after the last WISE visit. The SPHEREx images' dates are shaded.
import type { WiseMotion } from "./api";
import { ticks, tickText } from "./plots";

const INK = { text: "#a9b6c9", grid: "rgba(169,182,201,.12)", point: "#e9eef5", unused: "#f2b544",
  model: "#8fb3e8", band: "rgba(79,121,184,.32)", frames: "rgba(233,238,245,.08)", now: "#ff5a4e" };
const FONT = "11px 'JetBrains Mono', ui-monospace, monospace";
const mjdToYear = (mjd: number) => 2000 + (mjd - 51544.5) / 365.25;

export class MotionPlot {
  private ctx: CanvasRenderingContext2D;
  private fit: WiseMotion | null = null;
  private frames: [number, number] | null = null;   // MJD range of the images shown
  private current: number | null = null;            // MJD of the image on screen

  constructor(private canvas: HTMLCanvasElement) {
    this.ctx = canvas.getContext("2d")!;
    canvas.setAttribute("role", "img");
    new ResizeObserver(() => this.draw()).observe(canvas.parentElement ?? canvas);
  }

  set(fit: WiseMotion | null, frames: [number, number] | null, current: number | null) {
    this.fit = fit; this.frames = frames; this.current = current;
    this.draw();
  }

  draw() {
    const { canvas, ctx, fit } = this;
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
    canvas.setAttribute("aria-label", fit
      ? `Motion fit: ${fit.n_visits_used} WISE visits, position minus straight-line motion, with the prediction's uncertainty band`
      : "Motion fit (no fit yet)");
    if (!fit) return;
    const c = fit.curve;
    const x0 = mjdToYear(c.mjd[0]), x1 = mjdToYear(c.mjd[c.mjd.length - 1]);
    const L = 46, R = 8, T = 6, B = 22, gap = 8;
    const ph = (h - T - B - gap) / 2;
    const X = (yr: number) => L + ((yr - x0) / (x1 - x0)) * (w - L - R);
    const xt = ticks(x0, x1, Math.max(2, Math.floor((w - L - R) / 60)));
    const panels = [
      { name: "Δα·cosδ", top: T, model: c.xi_mas, sig: c.sig_xi_mas, val: (v: WiseMotion["visits"][0]) => v.dxi_mas, err: (v: WiseMotion["visits"][0]) => v.sig_xi_mas },
      { name: "Δδ", top: T + ph + gap, model: c.eta_mas, sig: c.sig_eta_mas, val: (v: WiseMotion["visits"][0]) => v.deta_mas, err: (v: WiseMotion["visits"][0]) => v.sig_eta_mas },
    ];
    ctx.font = FONT;
    for (const p of panels) {
      // Range: the band and the visits used in the fit (a rejected visit may fall outside).
      let lo = Infinity, hi = -Infinity;
      p.model.forEach((m, i) => { lo = Math.min(lo, m - p.sig[i]); hi = Math.max(hi, m + p.sig[i]); });
      for (const v of fit.visits) if (v.used) { lo = Math.min(lo, p.val(v) - p.err(v)); hi = Math.max(hi, p.val(v) + p.err(v)); }
      const pad = (hi - lo) * 0.06 || 1;
      lo -= pad; hi += pad;
      const Y = (mas: number) => p.top + ph - ((mas - lo) / (hi - lo)) * ph;
      ctx.save();
      ctx.beginPath(); ctx.rect(L, p.top, w - L - R, ph); ctx.clip();
      if (this.frames) {
        const a = X(mjdToYear(this.frames[0])), b = X(mjdToYear(this.frames[1]));
        ctx.fillStyle = INK.frames;
        ctx.fillRect(a - 1, p.top, Math.max(b - a, 0) + 2, ph);
      }
      ctx.strokeStyle = INK.grid; ctx.lineWidth = 1;
      const yt = ticks(lo, hi, 3);
      for (const t of yt) { ctx.beginPath(); ctx.moveTo(L, Y(t)); ctx.lineTo(w - R, Y(t)); ctx.stroke(); }
      for (const t of xt) { ctx.beginPath(); ctx.moveTo(X(t), p.top); ctx.lineTo(X(t), p.top + ph); ctx.stroke(); }
      // ±1σ band of the predicted position, then the model itself
      ctx.beginPath();
      c.mjd.forEach((m, i) => { const x = X(mjdToYear(m)), y = Y(p.model[i] + p.sig[i]); if (i) ctx.lineTo(x, y); else ctx.moveTo(x, y); });
      for (let i = c.mjd.length - 1; i >= 0; i--) ctx.lineTo(X(mjdToYear(c.mjd[i])), Y(p.model[i] - p.sig[i]));
      ctx.closePath(); ctx.fillStyle = INK.band; ctx.fill();
      ctx.beginPath();
      c.mjd.forEach((m, i) => { const x = X(mjdToYear(m)), y = Y(p.model[i]); if (i) ctx.lineTo(x, y); else ctx.moveTo(x, y); });
      ctx.strokeStyle = INK.model; ctx.lineWidth = 1.25; ctx.stroke();
      for (const v of fit.visits) {
        const x = X(v.epoch), y = Y(p.val(v));
        ctx.strokeStyle = ctx.fillStyle = v.used ? INK.point : INK.unused;
        ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(x, Y(p.val(v) - p.err(v))); ctx.lineTo(x, Y(p.val(v) + p.err(v))); ctx.stroke();
        ctx.beginPath(); ctx.arc(x, y, 2.2, 0, 2 * Math.PI);
        if (v.used) ctx.fill(); else ctx.stroke();
      }
      if (this.current !== null) {
        ctx.strokeStyle = INK.now; ctx.lineWidth = 1; ctx.setLineDash([3, 3]);
        const x = X(mjdToYear(this.current));
        ctx.beginPath(); ctx.moveTo(x, p.top); ctx.lineTo(x, p.top + ph); ctx.stroke();
        ctx.setLineDash([]);
      }
      ctx.restore();
      ctx.strokeStyle = INK.grid; ctx.strokeRect(L + 0.5, p.top + 0.5, w - L - R - 1, ph - 1);
      ctx.fillStyle = INK.text; ctx.textBaseline = "middle"; ctx.textAlign = "right";
      const step = yt.length > 1 ? yt[1] - yt[0] : 1;
      for (const t of yt) if (Y(t) > p.top + 5 && Y(t) < p.top + ph - 5) ctx.fillText(tickText(t, step), L - 4, Y(t));
      ctx.textAlign = "left"; ctx.textBaseline = "top";
      const label = `${p.name} (mas)`;
      ctx.fillStyle = "rgba(10,18,32,.85)";          // keep the label readable over the points
      ctx.fillRect(L + 2, p.top + 2, ctx.measureText(label).width + 6, 15);
      ctx.fillStyle = INK.text;
      ctx.fillText(label, L + 5, p.top + 4);
    }
    ctx.fillStyle = INK.text; ctx.textAlign = "center"; ctx.textBaseline = "top";
    for (const t of xt) ctx.fillText(String(Math.round(t)), X(t), h - B + 5);
  }
}
