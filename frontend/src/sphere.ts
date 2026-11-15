// Sky Sphere view (Three.js). Loaded on demand: this module and Three.js are a separate
// chunk that the browser fetches the first time the Sky Sphere tab opens.
//
// Three.js draws the textured sphere: a static all-sky image, plus the survey's own HiPS
// tiles on top once the view is zoomed in further than that image can show (healpix.ts). The camera pose, every overlay (grid, planes,
// reticle, markers, labels) and click picking come from sphere-math.ts, the unit-tested
// geometry, so what is drawn and what a click returns cannot disagree about handedness.
import { t } from "./i18n";
import {
  BackSide, BufferGeometry, DoubleSide, Float32BufferAttribute, FrontSide, Group, LinearFilter, Mesh,
  MeshBasicMaterial, PerspectiveCamera, RepeatWrapping, SRGBColorSpace, Scene, Texture, TextureLoader, WebGLRenderer,
} from "three";
import { FACE_DEG, orderFor, radecToPix, tilePath, tileToRadec, tileUv } from "./healpix";
import skyConfig from "../sky.config.json";
import { formatDecimal } from "./coords";
import {
  ECLIPTIC_POLE, GALACTIC_POLE, cameraPose, greatCircle, radecToScreen, radecToUv, radecToVec,
  screenToRadec, separation, slerpRadec, type Lens, type Pose, type RaDec,
} from "./sphere-math";

export interface SkyMarker { ra: number; dec: number; label: string; kind: "target" | "pick" | "preset"; id?: string }
export interface SphereOptions { grid: boolean; ecliptic: boolean; galactic: boolean }

const C = { grid: "rgba(169,182,201,.28)", equator: "rgba(233,238,245,.55)", ecl: "#f2b544", gal: "#b79cff",
  target: "#ff5a4e", pick: "#f2b544", preset: "#e9eef5", label: "#e9eef5" };
const MONO = "11px 'JetBrains Mono', ui-monospace, monospace";
const OUTSIDE_DISTANCE = 2.7, OUTSIDE_FOV = 42, FOV_MIN = 12, FOV_MAX = 110;
const TILE_PX = 512, MAX_TILES = 160, OVERZOOM = 2;

interface TileSource { url: string; format: string; maxOrder: number; sliced?: boolean }
interface SkyLayer { id: string; label: string; credit: string; cube_um?: number; tiles?: TileSource }
const LAYERS = skyConfig.layers as SkyLayer[];
interface Tile { mesh: Mesh<BufferGeometry, MeshBasicMaterial> | null; state: "loading" | "ready" | "missing"; used: number; img?: HTMLImageElement }

/** One HiPS tile as a patch of the unit sphere, wound so the outward side is the front. */
function tileGeometry(order: number, ipix: number): BufferGeometry {
  const n = Math.max(8, 32 >> order);
  const pos: number[] = [], uv: number[] = [], idx: number[] = [];
  for (let j = 0; j <= n; j++) for (let i = 0; i <= n; i++) {
    const fx = i / n, fy = j / n;
    pos.push(...radecToVec(...tileToRadec(order, ipix, fx, fy)));
    uv.push(...tileUv(fx, fy));
  }
  const at = (i: number, j: number) => j * (n + 1) + i;
  // HEALPix x and y both run north-east/north-west of the pixel's south corner; which of
  // the two windings faces outward is fixed by the frame, so test it once on this tile.
  const v = (k: number) => [pos[3 * k], pos[3 * k + 1], pos[3 * k + 2]];
  const a0 = v(at(0, 0)), b0 = v(at(1, 0)), c0 = v(at(0, 1));
  const e1 = [b0[0] - a0[0], b0[1] - a0[1], b0[2] - a0[2]], e2 = [c0[0] - a0[0], c0[1] - a0[1], c0[2] - a0[2]];
  const nrm = [e1[1] * e2[2] - e1[2] * e2[1], e1[2] * e2[0] - e1[0] * e2[2], e1[0] * e2[1] - e1[1] * e2[0]];
  const outward = nrm[0] * a0[0] + nrm[1] * a0[1] + nrm[2] * a0[2] > 0;
  for (let j = 0; j < n; j++) for (let i = 0; i < n; i++) {
    const a = at(i, j), b = at(i + 1, j), c = at(i, j + 1), d = at(i + 1, j + 1);
    if (outward) idx.push(a, b, c, b, d, c); else idx.push(a, c, b, b, c, d);
  }
  const g = new BufferGeometry();
  g.setAttribute("position", new Float32BufferAttribute(pos, 3));
  g.setAttribute("uv", new Float32BufferAttribute(uv, 2));
  g.setIndex(idx);
  return g;
}
const ease = (t: number) => t * t * (3 - 2 * t);
const reducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/** A lat/long sphere whose vertices and texture coordinates come from radecToVec and
 * radecToUv, wound so the outward side is the front face. */
function skyGeometry(nRa = 96, nDec = 48): BufferGeometry {
  const pos: number[] = [], uv: number[] = [], idx: number[] = [];
  for (let j = 0; j <= nDec; j++) for (let i = 0; i <= nRa; i++) {
    const ra = (360 * i) / nRa, dec = -90 + (180 * j) / nDec;
    pos.push(...radecToVec(ra, dec));
    uv.push(...radecToUv(ra, dec));
  }
  const at = (i: number, j: number) => j * (nRa + 1) + i;
  // east x north points outward (see sphere-math tests), so a -> b (east) -> c (north) is
  // counter-clockwise when seen from outside: the outer side is the front face.
  for (let j = 0; j < nDec; j++) for (let i = 0; i < nRa; i++) {
    const a = at(i, j), b = at(i + 1, j), c = at(i, j + 1), d = at(i + 1, j + 1);
    idx.push(a, b, c, b, d, c);
  }
  const g = new BufferGeometry();
  g.setAttribute("position", new Float32BufferAttribute(pos, 3));
  g.setAttribute("uv", new Float32BufferAttribute(uv, 2));
  g.setIndex(idx);
  return g;
}

export class SkySphere {
  onPick: (ra: number, dec: number) => void = () => {};
  onPreset: (id: string) => void = () => {};
  onHover: (text: string) => void = () => {};
  onStatus: (text: string) => void = () => {};

  private renderer: WebGLRenderer;
  private scene = new Scene();
  private camera = new PerspectiveCamera(70, 1, 0.01, 20);
  private material = new MeshBasicMaterial({ color: 0xffffff, side: BackSide });
  private overlay: HTMLCanvasElement;
  private ctx: CanvasRenderingContext2D;
  private centre: RaDec = [83.82, -5.39];      // Orion, until a target is known
  private t = 0;                               // 0 = inside, 1 = outside (animated in between)
  private fov = 70;                            // inside view: vertical field, degrees
  private distance = OUTSIDE_DISTANCE;         // outside view: camera distance, sphere radii
  private options: SphereOptions = { grid: true, ecliptic: false, galactic: false };
  private markers: SkyMarker[] = [];
  private layer = "";
  private tileGroup = new Group();
  private tiles = new Map<string, Tile>();     // "order/ipix" -> tile of the current layer
  private tileBase: string | null = null;      // HiPS root of the current layer, once known
  private tileSrc: TileSource | null = null;
  private tick = 0;
  private settle = 0;                          // timer: tiles load once the view has held still
  private settled = false;
  private viewSig = "";
  private detail = "";                         // what the detail tiles are doing (status line)
  private note = "";
  private anim = 0;
  private frame = 0;
  private ecl = greatCircle(...ECLIPTIC_POLE, 240);
  private gal = greatCircle(...GALACTIC_POLE, 240);

  constructor(private host: HTMLElement) {
    this.renderer = new WebGLRenderer({ antialias: true, alpha: false });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.setClearColor(0x000000, 1);
    const gl = this.renderer.domElement;
    gl.className = "sphere-gl";
    gl.setAttribute("aria-hidden", "true");
    this.overlay = document.createElement("canvas");
    this.overlay.className = "sphere-overlay";
    this.overlay.tabIndex = 0;
    this.overlay.setAttribute("role", "application");
    this.overlay.setAttribute("aria-label", "Sky sphere. Drag or use the arrow keys to look around, scroll or +/- to zoom, click to pick a position.");
    this.ctx = this.overlay.getContext("2d")!;
    host.append(gl, this.overlay);
    this.scene.add(new Mesh(skyGeometry(), this.material), this.tileGroup);
    new ResizeObserver(() => this.resize()).observe(host);
    this.bindInput();
    this.resize();
  }

  // ---- state from the app ------------------------------------------------------------
  setMode(mode: "inside" | "outside", animate = true) {
    const to = mode === "outside" ? 1 : 0;
    if (to === this.t && !this.anim) return;
    cancelAnimationFrame(this.anim);
    if (!animate || reducedMotion()) { this.t = to; this.anim = 0; this.requestRender(); return; }
    const from = this.t, t0 = performance.now(), ms = 900 * Math.abs(to - from);
    const step = (now: number) => {
      const k = Math.min(1, (now - t0) / ms);
      this.t = from + (to - from) * ease(k);
      this.render();
      this.anim = k < 1 ? requestAnimationFrame(step) : 0;
      if (!this.anim) this.render();
    };
    this.anim = requestAnimationFrame(step);
  }

  /** Rotate the view to a sky position along the great circle. */
  goTo(ra: number, dec: number, animate = true) {
    const from: RaDec = [...this.centre], to: RaDec = [ra, dec];
    const angle = separation(from, to);
    if (!animate || reducedMotion() || angle < 0.05) { this.centre = to; this.requestRender(); return; }
    cancelAnimationFrame(this.anim);
    const tEnd = this.t > 0.5 ? 1 : 0;
    const t0 = performance.now(), ms = 350 + Math.min(650, angle * 6);
    const step = (now: number) => {
      const k = Math.min(1, (now - t0) / ms);
      this.centre = slerpRadec(from, to, ease(k));
      this.t = tEnd;
      this.render();
      this.anim = k < 1 ? requestAnimationFrame(step) : 0;
    };
    this.anim = requestAnimationFrame(step);
  }

  setOptions(o: SphereOptions) { this.options = o; this.requestRender(); }
  setMarkers(m: SkyMarker[]) { this.markers = m; this.requestRender(); }

  /** Show one of the pre-rendered all-sky textures (static files; see sky.config.json). */
  setLayer(id: string) {
    if (id === this.layer) return;
    this.layer = id;
    const cfg = LAYERS.find((l) => l.id === id);
    this.onStatus(`Loading ${cfg?.label ?? id}…`);
    this.setTileSource(cfg);
    new TextureLoader().load(`assets/sky/${id}.jpg`, (tex) => {
      if (this.layer !== id) { tex.dispose(); return; }
      tex.colorSpace = SRGBColorSpace;
      tex.wrapS = RepeatWrapping;               // u runs continuously through RA 0..360
      tex.minFilter = LinearFilter;
      tex.generateMipmaps = false;
      tex.anisotropy = this.renderer.capabilities.getMaxAnisotropy();
      this.material.map?.dispose();
      this.material.map = tex;
      this.material.needsUpdate = true;
      this.note = cfg ? `${cfg.label} · ${cfg.credit}` : id;
      this.status();
      this.requestRender();
    }, undefined, () => this.onStatus(`Sky texture "${id}" is not available (run scripts/build_sky_textures.py).`));
  }

  private status() { if (this.note) this.onStatus(this.detail ? `${this.note} · ${this.detail}` : this.note); }

  // ---- detail tiles (HiPS) -------------------------------------------------------------
  private setTileSource(cfg: SkyLayer | undefined) {
    for (const t of this.tiles.values()) {
      if (t.img) { t.img.onload = t.img.onerror = null; t.img.src = ""; }
      this.dropTile(t);
    }
    this.tiles.clear();
    this.tileBase = null;
    this.detail = "";
    this.tileSrc = cfg?.tiles ?? null;
    const src = this.tileSrc;
    if (!src) return;
    const root = new URL(src.url, document.baseURI).href.replace(/\/$/, "");
    if (!src.sliced) { this.tileBase = root; return; }
    // A HiPS cube served one slice at a time: use the slice nearest the layer's wavelength.
    fetch(`${root}/properties`).then((r) => (r.ok ? r.text() : Promise.reject(new Error(String(r.status))))).then((text) => {
      if (this.tileSrc !== src) return;
      const waves = (/^data_cube_crval3_arr\s*=\s*(.+)$/m.exec(text)?.[1] ?? "").trim().split(/\s+/).map(Number);
      if (!waves.length || waves.some(Number.isNaN)) throw new Error("no wavelength list");
      const want = cfg?.cube_um ?? waves[0];
      const k = waves.reduce((best, w, i) => (Math.abs(w - want) < Math.abs(waves[best] - want) ? i : best), 0);
      this.tileBase = `${root}/${k}`;
      this.requestRender();
    }).catch(() => { if (this.tileSrc === src) { this.detail = "detail tiles unavailable"; this.status(); } });
  }

  private dropTile(t: Tile) {
    if (!t.mesh) return;
    this.tileGroup.remove(t.mesh);
    t.mesh.geometry.dispose();
    t.mesh.material.map?.dispose();
    t.mesh.material.dispose();
    t.mesh = null;
  }

  /** Degrees of sky per CSS pixel at the view centre. */
  private degPerPx(): number {
    const h = Math.max(1, this.host.clientHeight);
    return this.t > 0.5
      ? (2 * Math.atan(Math.tan((OUTSIDE_FOV * Math.PI) / 360) * (this.distance - 1)) * 180) / Math.PI / h
      : this.fov / h;
  }

  /** The narrowest inside field: the sharpest tiles enlarged OVERZOOM times. */
  private fovMin(): number {
    if (!this.tileSrc) return FOV_MIN;
    return Math.min(FOV_MIN, (FACE_DEG / 2 ** this.tileSrc.maxOrder / TILE_PX / OVERZOOM) * Math.max(1, this.host.clientHeight));
  }

  /** Choose, load and show the tiles for this view. Coarser tiles that are already loaded
   * stay underneath until the sharper ones arrive, so the sky never goes blank. */
  private updateTiles(pose: Pose, lens: Lens) {
    for (const t of this.tiles.values()) if (t.mesh) t.mesh.visible = false;
    const src = this.tileSrc;
    if (!src || !this.tileBase || (this.t !== 0 && this.t !== 1)) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const order = Math.min(src.maxOrder, orderFor(this.degPerPx() / dpr, TILE_PX));
    if (order < 1) { if (this.detail) { this.detail = ""; this.status(); } return; }   // the all-sky image is enough
    // Tiles under a grid of screen points (the view is at most a few tiles across).
    const want = new Set<number>(), n = 14;
    for (let j = 0; j <= n; j++) for (let i = 0; i <= n; i++) {
      const p = screenToRadec(pose, (2 * i) / n - 1, (2 * j) / n - 1, lens);
      if (p) want.add(radecToPix(order, p[0], p[1]));
    }
    this.tick++;
    // New tiles are requested only after the view has been still for a moment, so zooming
    // or slewing through many orders does not ask the archive for tiles nobody will see.
    // Redraws that leave the view where it was (markers, a loaded tile) do not restart the wait.
    const sig = [this.layer, this.t, this.centre[0], this.centre[1], this.fov, this.distance, lens.aspect].join(",");
    if (sig !== this.viewSig) {
      this.viewSig = sig;
      this.settled = false;
      clearTimeout(this.settle);
      this.settle = window.setTimeout(() => { this.settled = true; this.requestRender(); }, 140);
    }
    const side = this.t === 0 ? BackSide : FrontSide;
    let pending = 0, missing = 0, waiting = 0;
    for (let o = order, set = want; o >= 0; o--, set = new Set([...set].map((p) => Math.floor(p / 4)))) {
      for (const ipix of set) {
        const key = `${o}/${ipix}`;
        let t = this.tiles.get(key);
        if (!t && o === order) {
          if (this.settled) t = this.loadTile(o, ipix, key); else waiting++;
        }
        if (!t) continue;
        t.used = this.tick;
        if (o === order) { if (t.state === "loading") pending++; else if (t.state === "missing") missing++; }
        if (t.mesh) { t.mesh.visible = true; t.mesh.material.side = side; }
      }
    }
    pending += waiting;
    // Requests for tiles the view has moved away from are dropped, so the archive (about
    // a third of a second per tile) works on what is on screen now.
    for (const [key, t] of this.tiles) {
      if (t.state !== "loading" || t.used === this.tick || !t.img) continue;
      t.img.onload = t.img.onerror = null;
      t.img.src = "";
      this.tiles.delete(key);
    }
    if (this.tiles.size > MAX_TILES) {
      const old = [...this.tiles].filter(([, t]) => t.used !== this.tick && t.state !== "loading").sort((a, b) => a[1].used - b[1].used);
      for (const [key, t] of old.slice(0, this.tiles.size - MAX_TILES)) { this.dropTile(t); this.tiles.delete(key); }
    }
    const arcsec = (FACE_DEG / 2 ** order / TILE_PX) * 3600;
    const scale = arcsec >= 60 ? `${(arcsec / 60).toFixed(1)}′` : `${arcsec.toFixed(arcsec < 10 ? 1 : 0)}″`;
    const detail = pending ? `loading detail (HiPS order ${order})…`
      : missing === want.size ? `no detail tiles here (HiPS order ${order})`
      : `HiPS order ${order}${order === src.maxOrder ? " (survey limit)" : ""}, ${scale}/px`;
    if (detail !== this.detail) { this.detail = detail; this.status(); }
  }

  private loadTile(order: number, ipix: number, key: string): Tile {
    const tile: Tile = { mesh: null, state: "loading", used: this.tick };
    this.tiles.set(key, tile);
    const src = this.tileSrc!, layer = this.layer;
    const img = new Image();
    tile.img = img;
    img.crossOrigin = "anonymous";
    img.onload = () => {
      if (this.layer !== layer || this.tiles.get(key) !== tile) return;
      const tex = new Texture(img);
      tex.colorSpace = SRGBColorSpace;
      tex.anisotropy = this.renderer.capabilities.getMaxAnisotropy();
      tex.needsUpdate = true;
      // Drawn after the all-sky sphere, sharper orders last; PNG tiles may have empty areas.
      const mat = new MeshBasicMaterial({ map: tex, depthTest: false, depthWrite: false, transparent: src.format === "png" });
      tile.mesh = new Mesh(tileGeometry(order, ipix), mat);
      tile.mesh.renderOrder = order + 1;
      tile.mesh.visible = false;
      this.tileGroup.add(tile.mesh);
      tile.state = "ready";
      tile.img = undefined;
      this.requestRender();
    };
    img.onerror = () => { tile.state = "missing"; this.requestRender(); };
    img.src = `${this.tileBase}/${tilePath(order, ipix)}.${src.format}`;
    return tile;
  }

  // ---- camera ------------------------------------------------------------------------
  private lens(): Lens {
    const fov = this.fov + (OUTSIDE_FOV - this.fov) * this.t;
    return { tanHalfFov: Math.tan((fov * Math.PI) / 360), aspect: this.host.clientWidth / Math.max(1, this.host.clientHeight) };
  }
  private pose(): Pose { return cameraPose(this.t, this.centre[0], this.centre[1], this.distance); }

  private resize() {
    const w = this.host.clientWidth, h = this.host.clientHeight;
    if (!w || !h) return;
    this.renderer.setSize(w, h, false);
    const dpr = window.devicePixelRatio || 1;
    this.overlay.width = Math.round(w * dpr);
    this.overlay.height = Math.round(h * dpr);
    this.render();
  }

  requestRender() {
    if (this.frame || this.anim) return;
    this.frame = requestAnimationFrame(() => { this.frame = 0; this.render(); });
  }

  private render() {
    const w = this.host.clientWidth, h = this.host.clientHeight;
    if (!w || !h) return;
    const pose = this.pose(), lens = this.lens();
    const cam = this.camera;
    cam.fov = (Math.atan(lens.tanHalfFov) * 360) / Math.PI;
    cam.aspect = lens.aspect;
    cam.position.set(...pose.pos);
    cam.up.set(...pose.up);
    cam.lookAt(pose.pos[0] + pose.forward[0], pose.pos[1] + pose.forward[1], pose.pos[2] + pose.forward[2]);
    cam.updateProjectionMatrix();
    // Inner faces from inside, outer faces from outside; both while the camera moves between.
    this.material.side = this.t === 0 ? BackSide : this.t === 1 ? FrontSide : DoubleSide;
    this.updateTiles(pose, lens);
    this.renderer.render(this.scene, cam);
    this.drawOverlay(pose, lens, w, h);
  }

  // ---- overlays (2D canvas; text is never mirrored) --------------------------------------
  private drawOverlay(pose: Pose, lens: Lens, w: number, h: number) {
    const ctx = this.ctx, dpr = window.devicePixelRatio || 1;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    const xy = (ra: number, dec: number): [number, number] | null => {
      const s = radecToScreen(pose, ra, dec, lens);
      return s ? [(s[0] + 1) * 0.5 * w, (1 - s[1]) * 0.5 * h] : null;
    };
    const line = (pts: RaDec[], color: string, width: number, dash: number[] = []) => {
      ctx.strokeStyle = color; ctx.lineWidth = width; ctx.setLineDash(dash);
      ctx.beginPath();
      let prev: [number, number] | null = null;
      for (const p of pts) {
        const s = xy(p[0], p[1]);
        // break the line where it leaves the visible hemisphere or jumps across the view
        if (s && prev && Math.hypot(s[0] - prev[0], s[1] - prev[1]) < Math.max(w, h) * 0.5) ctx.lineTo(s[0], s[1]);
        else if (s) ctx.moveTo(s[0], s[1]);
        prev = s;
      }
      ctx.stroke(); ctx.setLineDash([]);
    };
    const text = (s: string, x: number, y: number, color: string, align: CanvasTextAlign = "left") => {
      ctx.font = MONO; ctx.textAlign = align; ctx.textBaseline = "middle";
      ctx.lineWidth = 3; ctx.strokeStyle = "rgba(13,22,38,.85)"; ctx.strokeText(s, x, y);
      ctx.fillStyle = color; ctx.fillText(s, x, y);
    };
    const onScreen = (s: [number, number] | null): s is [number, number] => !!s && s[0] > 8 && s[0] < w - 8 && s[1] > 8 && s[1] < h - 8;

    if (this.options.grid) {
      const steps = Array.from({ length: 91 }, (_, i) => i * 2);
      for (let ra = 0; ra < 360; ra += 30) line(steps.map((s) => [ra, -90 + s] as RaDec), C.grid, 1);
      // Parallels are not great circles, so when zoomed in they are sampled finely around
      // the view centre (a 2 degree chord would sit visibly off the true circle).
      const span = Math.min(180, (this.degPerPx() * Math.max(w, h) * 2) / Math.max(0.05, Math.cos((this.centre[1] * Math.PI) / 180)));
      for (let dec = -60; dec <= 60; dec += 30)
        line(Array.from({ length: 181 }, (_, i) => [this.centre[0] - span + (i * span) / 90, dec] as RaDec), dec === 0 ? C.equator : C.grid, dec === 0 ? 1.4 : 1);
      // Labels: RA (hours) along the parallel nearest the view centre, Dec along the nearest meridian.
      const decRow = Math.max(-60, Math.min(60, Math.round(this.centre[1] / 30) * 30));
      for (let ra = 0; ra < 360; ra += 30) {
        const s = xy(ra, decRow);
        if (onScreen(s)) text(`${ra / 15}h`, s[0] + 4, s[1] - 8, C.label);
      }
      const raCol = (Math.round(this.centre[0] / 30) * 30) % 360;
      for (let dec = -60; dec <= 60; dec += 30) {
        const s = xy(raCol, dec);
        if (onScreen(s) && dec !== decRow) text(`${dec > 0 ? "+" : ""}${dec}°`, s[0] + 4, s[1] - 8, C.label);
      }
      for (const [name, dec] of [["NCP", 90], ["SCP", -90]] as const) {
        const s = xy(0, dec);
        if (onScreen(s)) text(name, s[0] + 6, s[1], C.label);
      }
    }
    const plane = (pts: RaDec[], color: string, name: string) => {
      line(pts, color, 1.6, [7, 5]);
      const best = pts.map((p) => xy(p[0], p[1])).filter(onScreen)
        .sort((a, b) => Math.hypot(a[0] - w / 2, a[1] - h / 2) - Math.hypot(b[0] - w / 2, b[1] - h / 2))[0];
      if (best) text(name, best[0] + 6, best[1] + 12, color);
    };
    if (this.options.ecliptic) plane(this.ecl, C.ecl, t("Ecliptic"));
    if (this.options.galactic) plane(this.gal, C.gal, t("Galactic plane"));

    for (const m of this.markers) {
      const s = xy(m.ra, m.dec);
      if (!s) continue;
      const color = C[m.kind];
      ctx.strokeStyle = color; ctx.lineWidth = m.kind === "preset" ? 1.4 : 2;
      ctx.beginPath();
      if (m.kind === "preset") {
        ctx.moveTo(s[0], s[1] - 6); ctx.lineTo(s[0] + 6, s[1]); ctx.lineTo(s[0], s[1] + 6); ctx.lineTo(s[0] - 6, s[1]); ctx.closePath();
      } else {
        ctx.arc(s[0], s[1], 11, 0, 2 * Math.PI);
        for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) { ctx.moveTo(s[0] + dx * 15, s[1] + dy * 15); ctx.lineTo(s[0] + dx * 24, s[1] + dy * 24); }
      }
      ctx.stroke();
      if (onScreen(s)) text(m.label, s[0] + (m.kind === "preset" ? 10 : 28), s[1], color);
    }
    // Compass at the view centre's edge: the direction of east depends on the mode.
    text(this.t > 0.5 ? "N ↑   E →" : "N ↑   E ←", w - 12, h - 14, C.label, "right");
  }

  // ---- input -------------------------------------------------------------------------
  private ndc(e: { clientX: number; clientY: number }): [number, number] {
    const r = this.overlay.getBoundingClientRect();
    return [((e.clientX - r.left) / r.width) * 2 - 1, 1 - ((e.clientY - r.top) / r.height) * 2];
  }

  private pan(dxPx: number, dyPx: number) {
    // Degrees of sky per pixel at the view centre.
    const perPx = this.degPerPx();
    const dec = Math.max(-90, Math.min(90, this.centre[1] + dyPx * perPx));
    const cosd = Math.max(0.05, Math.cos((dec * Math.PI) / 180));
    // The sky follows the pointer. East is left from inside and right from outside, so the
    // same drag changes RA in opposite senses in the two modes.
    const sign = this.t > 0.5 ? -1 : 1;
    this.centre = [(((this.centre[0] + (sign * dxPx * perPx) / cosd) % 360) + 360) % 360, dec];
    this.requestRender();
  }

  private zoom(factor: number) {
    if (this.t > 0.5) this.distance = Math.max(1.02, Math.min(6, 1 + (this.distance - 1) * factor));
    else this.fov = Math.max(this.fovMin(), Math.min(FOV_MAX, this.fov * factor));
    this.requestRender();
  }

  private bindInput() {
    const el = this.overlay;
    let down: { x: number; y: number; moved: number } | null = null;
    const pinch = new Map<number, { x: number; y: number }>();
    let pinchDist = 0;
    el.addEventListener("pointerdown", (e) => {
      el.setPointerCapture(e.pointerId);
      pinch.set(e.pointerId, { x: e.clientX, y: e.clientY });
      down = { x: e.clientX, y: e.clientY, moved: 0 };
      pinchDist = 0;
    });
    el.addEventListener("pointermove", (e) => {
      if (pinch.has(e.pointerId)) pinch.set(e.pointerId, { x: e.clientX, y: e.clientY });
      if (pinch.size === 2) {
        const [a, b] = [...pinch.values()];
        const d = Math.hypot(a.x - b.x, a.y - b.y);
        if (pinchDist) this.zoom(pinchDist / d);
        pinchDist = d;
        if (down) down.moved = 99;
      } else if (down) {
        const dx = e.clientX - down.x, dy = e.clientY - down.y;
        down.moved += Math.abs(dx) + Math.abs(dy);
        down.x = e.clientX; down.y = e.clientY;
        if (down.moved > 4) { cancelAnimationFrame(this.anim); this.anim = 0; this.t = Math.round(this.t); this.pan(dx, dy); }
      }
      const p = screenToRadec(this.pose(), ...this.ndc(e), this.lens());
      this.onHover(p ? formatDecimal(p[0], p[1], 4) : "");
    });
    const up = (e: PointerEvent) => {
      pinch.delete(e.pointerId);
      if (!down) return;
      const wasClick = down.moved <= 4;
      down = null;
      if (!wasClick || e.type === "pointercancel") return;
      // A click: a preset marker under the pointer, otherwise the sky position there.
      const r = el.getBoundingClientRect(), pose = this.pose(), lens = this.lens();
      for (const m of this.markers) {
        if (m.kind !== "preset" || !m.id) continue;
        const s = radecToScreen(pose, m.ra, m.dec, lens);
        if (s && Math.hypot((s[0] + 1) * 0.5 * r.width - (e.clientX - r.left), (1 - s[1]) * 0.5 * r.height - (e.clientY - r.top)) < 12) {
          this.onPreset(m.id);
          return;
        }
      }
      const p = screenToRadec(pose, ...this.ndc(e), lens);
      if (p) this.onPick(p[0], p[1]);
    };
    el.addEventListener("pointerup", up);
    el.addEventListener("pointercancel", up);
    el.addEventListener("pointerleave", () => this.onHover(""));
    el.addEventListener("wheel", (e) => { e.preventDefault(); this.zoom(Math.exp(e.deltaY * 0.0012)); }, { passive: false });
    el.addEventListener("keydown", (e) => {
      const step = 24;
      const moves: Record<string, () => void> = {
        ArrowLeft: () => this.pan(step, 0), ArrowRight: () => this.pan(-step, 0),
        ArrowUp: () => this.pan(0, step), ArrowDown: () => this.pan(0, -step),
        "+": () => this.zoom(0.85), "=": () => this.zoom(0.85), "-": () => this.zoom(1 / 0.85),
        Enter: () => this.onPick(this.centre[0], this.centre[1]),
      };
      const fn = moves[e.key];
      if (fn) { e.preventDefault(); e.stopPropagation(); fn(); }
    });
  }
}
