// Canvas flipbook: preloads PNG frames, plays them in order, draws crosshair + catalog marks.
import type { Grid, ProductInfo } from "./api";

/** A mark on the image: a ring of radius ``r`` image pixels or, with ``ellipse``, an
 * uncertainty ellipse drawn to scale (semi-axes in arcsec, PA east of north) with four
 * diagonal ticks around it so that it can be found when it is smaller than a pixel. */
export interface Marker {
  ra: number; dec: number; color: string; r: number; label?: string; width?: number;
  ellipse?: { a: number; b: number; pa: number };
}

const DEG = Math.PI / 180;

/** Gnomonic projection onto the north-up grid (0-based pixels, FITS orientation: +y = north). */
export function skyToGrid(g: Grid, ra: number, dec: number): [number, number] {
  const a = ra * DEG, d = dec * DEG, a0 = g.ra * DEG, d0 = g.dec * DEG;
  const cosc = Math.sin(d0) * Math.sin(d) + Math.cos(d0) * Math.cos(d) * Math.cos(a - a0);
  const xi = (Math.cos(d) * Math.sin(a - a0)) / cosc;
  const eta = (Math.cos(d0) * Math.sin(d) - Math.sin(d0) * Math.cos(d) * Math.cos(a - a0)) / cosc;
  const s = (g.scale_arcsec / 3600) * DEG;
  return [g.center_pix - xi / s, g.center_pix + eta / s];
}

export function gridToSky(g: Grid, x: number, y: number): [number, number] {
  const s = (g.scale_arcsec / 3600) * DEG;
  const xi = -(x - g.center_pix) * s, eta = (y - g.center_pix) * s;
  const a0 = g.ra * DEG, d0 = g.dec * DEG;
  const rho = Math.hypot(xi, eta);
  if (rho === 0) return [g.ra, g.dec];
  const c = Math.atan(rho);
  const dec = Math.asin(Math.cos(c) * Math.sin(d0) + (eta * Math.sin(c) * Math.cos(d0)) / rho);
  const ra = a0 + Math.atan2(xi * Math.sin(c), rho * Math.cos(d0) * Math.cos(c) - eta * Math.sin(d0) * Math.sin(c));
  return [((ra / DEG) % 360 + 360) % 360, dec / DEG];
}

export class Player {
  canvas: HTMLCanvasElement;
  ctx: CanvasRenderingContext2D;
  grid: Grid | null = null;
  products: ProductInfo[] = [];
  urls: string[] = [];
  images = new Map<string, HTMLImageElement>();
  index = 0;
  playing = false;
  speed = 500;
  zoom = 4;            // effective screen pixels per image pixel (derived, see resize)
  userZoom = 1;        // magnification relative to "fit the box"
  crosshair = true;
  lightSky = false;    // image shown dark-on-white: draw the crosshair in darker colours
  markers: (p: ProductInfo) => Marker[] = () => [];
  onFrame: (i: number, p: ProductInfo | undefined) => void = () => {};
  onHover: (ra: number, dec: number, x: number, y: number) => void = () => {};
  private timer: number | undefined;
  private box: HTMLElement | null = null;

  constructor(canvas: HTMLCanvasElement) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d")!;
    canvas.addEventListener("mousemove", (e) => {
      if (!this.grid) return;
      const r = canvas.getBoundingClientRect();
      const x = (e.clientX - r.left) / this.zoom - 0.5;
      const y = this.grid.npix - 1 - ((e.clientY - r.top) / this.zoom - 0.5);
      const [ra, dec] = gridToSky(this.grid, x, y);
      this.onHover(ra, dec, x, y);
    });
  }

  setProducts(grid: Grid, products: ProductInfo[], urls: string[], keepIndex = true) {
    this.grid = grid;
    this.products = products;
    this.urls = urls;
    for (const u of urls) this.load(u);
    // Keep showing images whose URL is still in use; drop the rest to bound memory.
    const keep = new Set(urls);
    for (const u of this.images.keys()) if (!keep.has(u)) this.images.delete(u);
    if (!keepIndex || this.index >= products.length) this.index = Math.max(0, Math.min(this.index, products.length - 1));
    this.resize();
    this.draw();
  }

  private load(url: string) {
    if (this.images.has(url)) return;
    const img = new Image();
    img.decoding = "async";
    img.onload = () => { if (this.urls[this.index] === url) this.draw(); };
    img.src = url;
    this.images.set(url, img);
  }

  loadedCount(): number {
    return this.urls.filter((u) => this.images.get(u)?.complete).length;
  }

  /** Scale the image to fill ``box`` (re-fitting whenever the box changes size). */
  fitInside(box: HTMLElement) {
    this.box = box;
    new ResizeObserver(() => { if (this.resize()) this.draw(); }).observe(box);
  }

  /** Recompute the on-screen scale; returns true if the canvas size changed. */
  resize(): boolean {
    const n = this.grid?.npix ?? 0;
    if (!n) return false;
    let base = 4;
    if (this.box && this.box.clientWidth > 0 && this.box.clientHeight > 0)
      base = Math.min(this.box.clientWidth, this.box.clientHeight) / n;
    const z = base * this.userZoom;
    // Whole-number scales keep image pixels equally sized (crisp) once they are >= 2 px.
    this.zoom = z >= 2 ? Math.floor(z) : z;
    const size = Math.max(1, Math.round(n * this.zoom));
    if (this.canvas.width === size) return false;
    this.canvas.width = size;
    this.canvas.height = size;
    return true;
  }

  setZoom(z: number) {
    this.userZoom = Math.max(1, z);
    this.resize();
    this.draw();
    // When magnified, start centred on the target.
    if (this.box) {
      this.box.scrollLeft = (this.canvas.width - this.box.clientWidth) / 2;
      this.box.scrollTop = (this.canvas.height - this.box.clientHeight) / 2;
    }
  }

  go(i: number) {
    if (!this.products.length) return;
    const n = this.products.length;
    this.index = ((i % n) + n) % n;
    this.draw();
  }

  step(d: number) { this.go(this.index + d); }

  play() {
    if (this.playing) return;
    this.playing = true;
    const tick = () => {
      if (!this.playing) return;
      // Don't race ahead of downloads: wait on the next frame if it isn't decoded yet.
      const next = (this.index + 1) % Math.max(this.products.length, 1);
      const img = this.images.get(this.urls[next]);
      if (!img || img.complete) this.step(1);
      this.timer = window.setTimeout(tick, this.speed);
    };
    this.timer = window.setTimeout(tick, this.speed);
  }

  pause() { this.playing = false; window.clearTimeout(this.timer); }

  draw() {
    const { ctx, canvas } = this;
    const p = this.products[this.index];
    ctx.imageSmoothingEnabled = false;
    ctx.fillStyle = "#000";   // --stage
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    if (!p || !this.grid) { this.onFrame(this.index, undefined); return; }
    const img = this.images.get(this.urls[this.index]);
    if (img?.complete && img.naturalWidth) ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
    const n = this.grid.npix, z = this.zoom;
    const toCanvas = (x: number, y: number): [number, number] => [(x + 0.5) * z, (n - 1 - y + 0.5) * z];
    for (const m of this.markers(p)) {
      const [gx, gy] = skyToGrid(this.grid, m.ra, m.dec);
      if (gx < -2 || gy < -2 || gx > n + 1 || gy > n + 1) continue;
      const [cx, cy] = toCanvas(gx, gy);
      ctx.strokeStyle = m.color;
      ctx.lineWidth = m.width ?? 1.5;
      ctx.beginPath();
      if (m.ellipse) {
        // North is up and east is left, so a position angle (east of north) turns anticlockwise.
        const s = z / this.grid.scale_arcsec, pa = m.ellipse.pa * DEG;
        const a = Math.max(m.ellipse.a * s, 0.5), b = Math.max(m.ellipse.b * s, 0.5);
        ctx.ellipse(cx, cy, a, b, Math.atan2(-Math.cos(pa), -Math.sin(pa)), 0, 2 * Math.PI);
        const r0 = Math.max(a + 3, 0.9 * z), r1 = r0 + Math.max(6, 1.2 * z);
        for (const [dx, dy] of [[1, 1], [1, -1], [-1, 1], [-1, -1]]) {
          ctx.moveTo(cx + dx * r0 * Math.SQRT1_2, cy + dy * r0 * Math.SQRT1_2);
          ctx.lineTo(cx + dx * r1 * Math.SQRT1_2, cy + dy * r1 * Math.SQRT1_2);
        }
      } else ctx.arc(cx, cy, m.r * z, 0, 2 * Math.PI);
      ctx.stroke();
      if (m.label) {
        ctx.font = "11px 'JetBrains Mono', ui-monospace, monospace";
        ctx.fillStyle = m.color;
        ctx.fillText(m.label, cx + m.r * z + 4, cy - m.r * z - 2);
      }
    }
    if (this.crosshair) {
      const [cx, cy] = toCanvas(p.target_xy[0], p.target_xy[1]);
      const gap = 2.2 * z, len = 3.5 * z;  // leave the target itself uncovered
      const ring = Math.max(6, 1.6 * z);   // the atlas ring, the same mark the sky maps use
      // The target mark is the one red on the page (night-vision red on a dark sky, a deeper red on a white one).
      ctx.strokeStyle = this.lightSky ? (p.target_bad ? "#b25e00" : "#d92d20") : p.target_bad ? "#f2b544" : "#ff5a4e";
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.arc(cx, cy, ring, 0, 2 * Math.PI);
      for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
        ctx.moveTo(cx + dx * gap, cy + dy * gap);
        ctx.lineTo(cx + dx * (gap + len), cy + dy * (gap + len));
      }
      ctx.stroke();
    }
    this.onFrame(this.index, p);
  }
}

/** One colour per detector, ordered by wavelength (D1 shortest). Used for interface marks
 * only (timeline ticks, legend), never applied to the science images. */
export const DETECTOR_COLORS: Record<number, string> = {
  1: "#a78bfa", 2: "#60a5fa", 3: "#4de3ff", 4: "#5eead4", 5: "#ffb547", 6: "#ff7a59",
};
const MIXED = "#9fb0d0";

/** The strip above the scrubber: one tick per frame, coloured by detector; the current
 * frame is marked, and frames whose target pixel is flagged carry an amber cap. */
export class Timeline {
  private ctx: CanvasRenderingContext2D;
  private products: ProductInfo[] = [];
  private index = 0;

  constructor(private canvas: HTMLCanvasElement, onSeek: (i: number) => void) {
    this.ctx = canvas.getContext("2d")!;
    new ResizeObserver(() => this.draw()).observe(canvas);
    // The tick strip is the scrubber: press and drag across it to move between frames.
    const seek = (e: PointerEvent) => {
      const r = canvas.getBoundingClientRect(), n = this.products.length;
      if (!n) return;
      const i = Math.max(0, Math.min(n - 1, Math.floor(((e.clientX - r.left) / r.width) * n)));
      if (i !== this.index) onSeek(i);
    };
    canvas.addEventListener("pointerdown", (e) => { canvas.setPointerCapture(e.pointerId); seek(e); });
    canvas.addEventListener("pointermove", (e) => { if (canvas.hasPointerCapture(e.pointerId)) seek(e); });
  }

  set(products: ProductInfo[], index: number) {
    this.products = products;
    this.index = index;
    this.draw();
  }

  private draw() {
    const { canvas, ctx } = this;
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth, h = canvas.clientHeight;
    if (!w || !h) return;
    if (canvas.width !== Math.round(w * dpr)) { canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr); }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    const n = this.products.length;
    if (!n) return;
    const step = w / n, tick = Math.max(1, Math.min(6, step - 1));
    this.products.forEach((p, i) => {
      const x = i * step + (step - tick) / 2;
      ctx.fillStyle = p.detectors.length === 1 ? DETECTOR_COLORS[p.detectors[0]] ?? MIXED : MIXED;
      ctx.globalAlpha = i === this.index ? 1 : 0.75;
      ctx.fillRect(x, 5, tick, h - 5);
      if (p.target_bad) { ctx.fillStyle = "#f2b544"; ctx.globalAlpha = 1; ctx.fillRect(x, 0, tick, 3); }
    });
    ctx.globalAlpha = 1;
    ctx.strokeStyle = "#ffffff";
    ctx.lineWidth = 1.5;
    ctx.strokeRect(this.index * step + (step - tick) / 2 - 1.5, 0.75, tick + 3, h - 1.5);
  }
}
