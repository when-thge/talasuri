// The atlas plate frame: a double neat-line around the flipbook image with RA/Dec ticks and
// labels along its edges, like the border of a printed star chart, plus the one authored
// moment of the interface: when a new target's first frame lands, a red ring closes onto it.
// Everything is drawn on an overlay canvas OUTSIDE the image area (the acquire ring passes
// over the image for under a second and is gone): the science pixels are never altered.
import type { Grid } from "./api";
import { skyToGrid } from "./player";

const INK = { line: "rgba(169,182,201,.55)", outer: "rgba(169,182,201,.28)", tick: "#8a98ae", label: "#a9b6c9", red: "#ff5a4e" };
const FONT = "10.5px 'JetBrains Mono', ui-monospace, monospace";
const GAP = 6;                      // image edge to inner neat-line
const DEC_STEPS = [5, 10, 15, 30, 60, 120, 300, 600, 900, 1800];       // arcsec
const RA_STEPS = [0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600];         // seconds of time

const pad = (n: number, w = 2) => String(Math.floor(n)).padStart(w, "0");

function decText(dec: number, withDeg: boolean): string {
  const s = Math.round(Math.abs(dec) * 3600);
  const d = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  const sign = dec < 0 ? "−" : "+";
  return withDeg ? `${sign}${d}°${pad(m)}′${sec ? `${pad(sec)}″` : ""}` : `${pad(m)}′${sec ? `${pad(sec)}″` : ""}`;
}

function raText(ra: number, withHours: boolean): string {
  let t = Math.round((((ra % 360) + 360) % 360) / 15 * 3600 * 2) / 2;   // half-seconds of time
  const h = Math.floor(t / 3600); t -= h * 3600;
  const m = Math.floor(t / 60); const s = t - m * 60;
  const ss = Number.isInteger(s) ? pad(s) : s.toFixed(1).padStart(4, "0");
  return withHours ? `${h}h${pad(m)}m${ss}s` : `${pad(m)}m${ss}s`;
}

export class PlateFrame {
  private ctx: CanvasRenderingContext2D;
  private acquireStart = 0;
  private acquireAt: [number, number] | null = null;
  private raf = 0;
  private last: { grid: Grid; zoom: number; target: [number, number] | null } | null = null;
  private readonly reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

  constructor(private overlay: HTMLCanvasElement, private image: HTMLCanvasElement, private stage: HTMLElement, private wrap: HTMLElement) {
    this.ctx = overlay.getContext("2d")!;
    new ResizeObserver(() => this.redraw()).observe(stage);
    wrap.addEventListener("scroll", () => this.redraw(), { passive: true });
  }

  /** Called on every frame drawn; cheap (a few dozen lines of canvas). */
  draw(grid: Grid | null, zoom: number, target: [number, number] | null) {
    this.last = grid ? { grid, zoom, target } : null;
    this.redraw();
  }

  /** Play the acquire moment at the target (grid pixel coordinates). */
  acquire(target: [number, number]) {
    if (this.reduceMotion.matches) return;
    this.acquireAt = target;
    this.acquireStart = performance.now();
    cancelAnimationFrame(this.raf);
    const tick = () => { this.redraw(); if (this.acquireAt) this.raf = requestAnimationFrame(tick); };
    this.raf = requestAnimationFrame(tick);
  }

  private redraw() {
    const { ctx, overlay, stage } = this;
    const dpr = window.devicePixelRatio || 1;
    const W = stage.clientWidth, H = stage.clientHeight;
    if (overlay.width !== Math.round(W * dpr) || overlay.height !== Math.round(H * dpr)) {
      overlay.width = Math.round(W * dpr); overlay.height = Math.round(H * dpr);
      overlay.style.width = `${W}px`; overlay.style.height = `${H}px`;
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    if (!this.last || !this.image.width) return;
    const { grid, zoom, target } = this.last;

    // The visible part of the image, in stage coordinates.
    const sr = stage.getBoundingClientRect(), ir = this.image.getBoundingClientRect(), wr = this.wrap.getBoundingClientRect();
    const l = Math.max(ir.left, wr.left) - sr.left, r = Math.min(ir.right, wr.right) - sr.left;
    const t = Math.max(ir.top, wr.top) - sr.top, b = Math.min(ir.bottom, wr.bottom) - sr.top;
    if (r - l < 40 || b - t < 40) return;
    const n = grid.npix;
    const toX = (gx: number) => ir.left - sr.left + (gx + 0.5) * zoom;
    const toY = (gy: number) => ir.top - sr.top + (n - 1 - gy + 0.5) * zoom;

    // Double neat-line: a firm inner rule and a fainter outer one.
    const x0 = Math.round(l - GAP) + 0.5, y0 = Math.round(t - GAP) + 0.5;
    const x1 = Math.round(r + GAP) - 0.5, y1 = Math.round(b + GAP) - 0.5;
    ctx.lineWidth = 1;
    ctx.strokeStyle = INK.line; ctx.strokeRect(x0, y0, x1 - x0, y1 - y0);
    ctx.strokeStyle = INK.outer; ctx.strokeRect(x0 - 4, y0 - 4, x1 - x0 + 8, y1 - y0 + 8);

    // Tick spacing: about one labelled tick per 90 screen pixels.
    const pxPerArcsec = zoom / grid.scale_arcsec;
    const decStep = DEC_STEPS.find((s) => s * pxPerArcsec >= 70) ?? DEC_STEPS[DEC_STEPS.length - 1];
    const cosd = Math.max(Math.cos((grid.dec * Math.PI) / 180), 1e-3);
    const raStep = RA_STEPS.find((s) => s * 15 * cosd * pxPerArcsec >= 90) ?? RA_STEPS[RA_STEPS.length - 1];
    const halfDeg = (n * grid.scale_arcsec) / 3600 / 2 * 1.5;

    ctx.font = FONT; ctx.fillStyle = INK.label; ctx.strokeStyle = INK.tick;
    ctx.beginPath();
    // Declination: ticks on the left and right edges, labels up the left edge.
    let first = true;
    const decStepDeg = decStep / 3600;
    for (let d = Math.ceil((grid.dec - halfDeg) / decStepDeg) * decStepDeg; d <= grid.dec + halfDeg; d += decStepDeg) {
      const y = toY(skyToGrid(grid, grid.ra, d)[1]);
      if (y < t || y > b) continue;
      const yy = Math.round(y) + 0.5;
      ctx.moveTo(x0 - 4, yy); ctx.lineTo(x0 + 4, yy);
      ctx.moveTo(x1 - 4, yy); ctx.lineTo(x1 + 4, yy);
      ctx.save(); ctx.translate(x0 - 9, yy); ctx.rotate(-Math.PI / 2);
      ctx.textAlign = "center"; ctx.textBaseline = "bottom";
      ctx.fillText(decText(d, first), 0, 0);
      ctx.restore();
      first = false;
    }
    // Right ascension: ticks on the top and bottom edges, labels along the top. East is left.
    first = true;
    const raStepDeg = (raStep * 15) / 3600;
    const raSpan = halfDeg / cosd;
    const ras: number[] = [];
    for (let a = Math.ceil((grid.ra - raSpan) / raStepDeg) * raStepDeg; a <= grid.ra + raSpan; a += raStepDeg) ras.push(a);
    for (const a of ras.reverse()) {                     // left to right on screen = decreasing RA
      const x = toX(skyToGrid(grid, a, grid.dec)[0]);
      if (x < l || x > r) continue;
      const xx = Math.round(x) + 0.5;
      ctx.moveTo(xx, y0 - 4); ctx.lineTo(xx, y0 + 4);
      ctx.moveTo(xx, y1 - 4); ctx.lineTo(xx, y1 + 4);
      ctx.textAlign = "center"; ctx.textBaseline = "bottom";
      ctx.fillText(raText(a, first), xx, y0 - 8);
      first = false;
    }
    ctx.stroke();

    // The acquire moment: a red ring closes from wide onto the target, then fades.
    if (this.acquireAt) {
      const k = (performance.now() - this.acquireStart) / 900;
      if (k >= 1 || !target) { this.acquireAt = null; return; }
      const e = 1 - Math.pow(1 - Math.min(k / 0.7, 1), 4);     // exponential-ish ease-out
      const [cx, cy] = [toX(this.acquireAt[0]), toY(this.acquireAt[1])];
      const rEnd = Math.max(6, 1.6 * zoom), rStart = Math.min(r - l, b - t) * 0.42;
      ctx.globalAlpha = k < 0.7 ? 0.35 + 0.65 * e : 1 - (k - 0.7) / 0.3;
      ctx.strokeStyle = INK.red; ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.arc(cx, cy, rStart + (rEnd - rStart) * e, 0, 2 * Math.PI); ctx.stroke();
      ctx.globalAlpha = 1;
    }
  }
}
