"""Talasuri API (FastAPI): JSON, WebP/PNG frames, FITS on request, SSE progress, and the
static frontend."""
from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import math
import re
import time
from collections import OrderedDict
from contextlib import asynccontextmanager

import numpy as np
from astropy.io import fits
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator

from .. import coords
from ..config import settings
from ..data_access import catalogs, cutouts, hips, names
from ..data_access.cutouts import CutoutRequest
from ..data_access.fitsmeta import DEFAULT_BAD_FLAGS, decode_flags, load_cutout, mask_for_names
from ..data_access.releases import registry
from ..data_access.resolver import ResolveError, Target, resolve
from ..processing import astrometry, movers, render
from ..processing.photometry import aperture_photometry
from ..processing.pipeline import DIFFS, MODES, Product, Selection, build_products, epoch_index
from .sessions import Session, SessionParams, executor, mjd_to_iso, store

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(registry.run_forever())
    await asyncio.to_thread(names.load_index)  # ~0.1 s; keeps the first keystroke fast
    yield
    task.cancel()


app = FastAPI(title="Talasuri", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"],
                   allow_headers=["*"])
# JSON (frame lists, photometry) compresses ~10x; PNG and SSE are excluded by Starlette.
app.add_middleware(GZipMiddleware, minimum_size=2048, compresslevel=5)


# ---------------------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------------------
@app.get("/api/releases")
def releases():
    return registry.to_json()


@app.get("/api/resolve")
async def resolve_endpoint(q: str):
    try:
        t = await resolve(q)
    except (ResolveError, coords.CoordinateError) as e:
        raise HTTPException(404, str(e))
    return {**t.to_json(), "sexagesimal": coords.format_sexagesimal(t.ra, t.dec)}


@app.get("/api/suggest")
async def suggest(q: str = Query("", max_length=100), live: bool = False, limit: int = Query(8, le=20)):
    """Name suggestions while typing. Local index first (instant); with live=1 also a
    SIMBAD prefix search for designations outside the index."""
    text = q.strip()
    try:
        if coords.parse_coordinates(text) is not None:
            return {"items": [], "note": "Coordinates: press Enter to go there."}
    except coords.CoordinateError:
        return {"items": [], "note": "Those coordinates are out of range."}
    items = names.suggest_local(text, limit)
    if live and len(items) < limit:
        seen = {i["main_id"] for i in items}
        try:
            extra = await names.suggest_live(text, limit)
        except Exception as e:  # suggestions are best-effort
            log.warning("live suggest failed: %s", e)
            extra = []
        items += [i for i in extra if i["main_id"] not in seen][: limit - len(items)]
    return {"items": items, "note": names.solar_system_note(text)}


class SessionRequest(BaseModel):
    ra: float
    dec: float
    fov: float = Field(5.0, gt=0)
    pmra: float = 0.0
    pmdec: float = 0.0
    epoch: float = 2000.0
    pm: bool = False
    release: str = "all"
    deep: bool = False
    name: str | None = None

    @model_validator(mode="after")
    def _on_the_sky(self):
        coords.check_range(self.ra, self.dec)   # the same rule the search box applies
        return self


@app.post("/api/sessions")
async def create_session(req: SessionRequest):
    if req.fov > settings.max_fov_arcmin:
        raise HTTPException(400, f"FOV is limited to {settings.max_fov_arcmin:g} arcmin")
    if req.release != "all" and req.release not in registry.releases():
        raise HTTPException(400, f"unknown release {req.release!r}; have {registry.releases()}")
    s = store.get_or_create(SessionParams(**req.model_dump()))
    return s.snapshot()


def _session(sid: str) -> Session:
    s = store.get(sid)
    if s is None:
        raise HTTPException(404, "session expired; re-run the search")
    return s


@app.get("/api/sessions/{sid}")
def get_session(sid: str):
    return _session(sid).snapshot()


@app.post("/api/sessions/{sid}/retry")
async def retry(sid: str):
    s = _session(sid)
    asyncio.create_task(s.retry_failed())
    return {"ok": True}


@app.get("/api/sessions/{sid}/events")
async def events(sid: str, request: Request):
    """Server-sent events: progress, per-frame metadata as each cutout lands, done."""
    s = _session(sid)
    q: asyncio.Queue = asyncio.Queue()
    s.subscribers.append(q)
    s.last_watched = time.time()
    if s.state == "paused":
        asyncio.create_task(s.resume())

    async def gen():
        try:
            yield f"data: {json.dumps(s.progress())}\n\n"
            if s.state in ("done", "error"):
                yield f"data: {json.dumps({'type': 'done'})}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    ev = await asyncio.wait_for(q.get(), 15)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                yield f"data: {json.dumps(ev, default=float)}\n\n"
        finally:
            if q in s.subscribers:
                s.subscribers.remove(q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------------------------------------------------------------------------------------
# Products (frames, stacks, differences)
# ---------------------------------------------------------------------------------------
class ProductQuery:
    """Every parameter that determines the list of displayed products, read from the
    request's query string (the same names for /products, images, FITS and /photometry)."""
    FLOATS = ("window", "lam_min", "lam_max", "mjd_min", "mjd_max")

    def __init__(self, request: Request):
        q = {k: v for k, v in request.query_params.items() if v != ""}
        num = {k: float(q[k]) for k in self.FLOATS if k in q}
        self.mode, self.diff = q.get("mode", "frames"), q.get("diff", "none")
        if self.mode not in MODES:
            raise HTTPException(400, f"bad mode {self.mode!r}")
        if self.diff not in DIFFS:
            raise HTTPException(400, f"bad diff {self.diff!r}")
        self.window, self.ref = max(num.get("window", 14.0), 0.01), int(q.get("ref", 0))
        try:
            self.dets = tuple(sorted(int(d) for d in q.get("dets", "").split(",") if d.strip()))
            self.rgb = tuple(int(d) for d in q.get("rgb", "6,4,2").split(","))[:3]
        except ValueError:
            raise HTTPException(400, "detector lists must be comma-separated integers")
        self.sel = Selection(num.get("mjd_min"), num.get("mjd_max"), self.dets or None,
                             num.get("lam_min"), num.get("lam_max"))
        self.bad_names = tuple(n for n in q["bad"].split(",") if n) if q.get("bad") else DEFAULT_BAD_FLAGS

    def cache_key(self, n_frames: int) -> str:
        return repr((self.mode, self.window, self.dets, self.sel, self.diff, self.ref,
                     self.bad_names, self.rgb, n_frames))


def _products(s: Session, pq: ProductQuery) -> tuple[list[Product], dict]:
    """The pipeline's products for a query, with their shared display limits. Frames were
    reprojected once when they arrived; stacks are computed once per selection and reused
    by every difference mode (session.stack_cache)."""
    key = pq.cache_key(len(s.frames))
    hit = s.product_cache.get(key)
    if hit is not None:
        s.product_cache.move_to_end(key)
        return hit
    if not s.frames:
        return [], {"vmin": 0, "vmax": 1}
    try:
        prods = build_products(list(s.frames.values()), pq.mode, pq.sel,
                               mask_for_names(s.flag_bits, pq.bad_names), pq.window, pq.rgb,
                               pq.diff, pq.ref, cache=s.stack_cache)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not prods:
        limits = {"vmin": 0, "vmax": 1}
    elif pq.mode == "rgb":
        limits = {"channels": [render.limits([p.sci]) for p in prods]}
    else:
        lo, hi = render.limits([p.sci for p in prods], symmetric=pq.diff != "none")
        limits = {"vmin": lo, "vmax": hi}
    s.product_cache[key] = (prods, limits)
    while len(s.product_cache) > 12:
        s.product_cache.popitem(last=False)
    return prods, limits


def _product_json(s: Session, i: int, p: Product, epochs: dict[str, int]) -> dict:
    c = s.grid.center_pix
    # crosshair: the target at the product's mean epoch (PM-tracked if enabled)
    ra_t, dec_t = s.position_at(p.mjd)
    gx, gy = s.grid.sky_to_pix(ra_t, dec_t)
    t0, t1 = p.mjd_range
    lam0, lam1 = p.lam_range
    flags = p.target_flags
    bad_mask = mask_for_names(s.flag_bits, DEFAULT_BAD_FLAGS)
    n_bad = sum(bool(m.target_flags & bad_mask) for m in p.members)
    # A single frame warns if its target pixel is bad; a stack only if most members are.
    bad = n_bad > len(p.members) / 2 if len(p.members) > 1 else n_bad == 1
    m0 = p.members[0]
    return {
        "index": i, "label": p.label, "n": len(p.members), "mjd": p.mjd,
        "mjd_range": [t0, t1], "date": mjd_to_iso(p.mjd), "detectors": p.detectors,
        "lam_um": float(np.mean([m.lam_um for m in p.members])), "lam_range_um": [lam0, lam1],
        "bw_um": m0.bw_um if len(p.members) == 1 else None,
        "obs_id": m0.obs_id if len(p.members) == 1 else None,
        "key": m0.key if len(p.members) == 1 else None,
        "epoch_index": epochs.get(m0.key),
        "target_xy": [float(gx), float(gy)],
        "target_flags": flags, "target_flag_names": decode_flags(flags, s.flag_bits),
        "target_bad": bool(bad), "n_members_flagged": n_bad,
        "center_pix": c,
    }


@app.get("/api/sessions/{sid}/products")
async def list_products(sid: str, request: Request):
    s = _session(sid)
    pq = ProductQuery(request)
    loop = asyncio.get_running_loop()
    prods, limits = await loop.run_in_executor(executor, _products, s, pq)
    epochs = epoch_index(list(s.frames.values()), pq.window) if s.frames else {}
    return {"products": [_product_json(s, i, p, epochs) for i, p in enumerate(prods)],
            "limits": limits, "grid": s.grid.to_json() if s.grid else None,
            "progress": s.progress(), "mode": pq.mode}


def _resolve_pid(prods: list[Product], pid: str) -> int:
    """A product id is its index, or (single frames) the frame key, which is stable while
    frames are still arriving."""
    if pid.isdigit():
        idx = int(pid)
    else:
        idx = next((i for i, p in enumerate(prods)
                    if len(p.members) == 1 and p.members[0].key == pid), -1)
    if not 0 <= idx < len(prods):
        raise HTTPException(404, "no such product")
    return idx


def _fits_bytes(s: Session, pq: ProductQuery, pid: str) -> tuple[bytes, int]:
    prods, _ = _products(s, pq)
    idx = _resolve_pid(prods, pid)
    p = prods[idx]
    hdr = s.grid.wcs.to_header()
    hdr["BUNIT"] = "MJy/sr"
    hdr["MJD-AVG"] = p.mjd
    hdr["NCOMBINE"] = len(p.members)
    hdr["SPXMODE"] = pq.mode
    hdr["SPXDIFF"] = pq.diff
    hdr["LAMMIN"], hdr["LAMMAX"] = p.lam_range
    hdr["COMMENT"] = "IMAGE - ZODI, inverse-variance co-add on a common TAN grid."
    hdr["COMMENT"] = "Source: SPHEREx Spectral Images via NASA/IPAC IRSA."
    hdul = fits.HDUList([fits.PrimaryHDU(),
                         fits.ImageHDU(p.sci, hdr, name="IMAGE"),
                         fits.ImageHDU(p.var, hdr, name="VARIANCE"),
                         fits.ImageHDU(p.flags.astype(np.int32), hdr, name="FLAGS"),
                         fits.ImageHDU(p.n_used, hdr, name="NUSED")])
    buf = io.BytesIO()
    hdul.writeto(buf)
    return buf.getvalue(), idx


@app.get("/api/sessions/{sid}/products/{pid}.fits")
async def product_fits(sid: str, pid: str, request: Request):
    """The science arrays of one product. FITS is only ever built for this explicit download."""
    s = _session(sid)
    pq = ProductQuery(request)
    data, idx = await asyncio.get_running_loop().run_in_executor(executor, _fits_bytes, s, pq, pid)
    name = f"spherex_{s.id}_{pq.mode}_{idx}.fits"
    return Response(data, media_type="application/fits",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.get("/api/sessions/{sid}/products/{pid}.{fmt}")
async def product_image(sid: str, pid: str, fmt: str, request: Request, stretch: str = "asinh",
                        vmin: float | None = None, vmax: float | None = None, invert: bool = False,
                        flagmode: str = "off", flagbits: str = ""):
    """One product as a compact lossless image (``.webp`` or ``.png``): a single frame, a
    stack, a difference image or the colour composite, all through render.render()."""
    if fmt not in render.FORMATS:
        raise HTTPException(404, f"format must be one of {sorted(render.FORMATS)} (or fits)")
    if stretch not in render.STRETCHES:
        raise HTTPException(400, f"stretch must be one of {render.STRETCHES}")
    s = _session(sid)
    pq = ProductQuery(request)

    def work():
        prods, limits = _products(s, pq)
        if pq.mode == "rgb":
            if len(prods) < 3:
                raise HTTPException(404, "RGB needs stacks from three detectors")
            return render.render([p.sci for p in prods], limits["channels"], stretch, fmt=fmt)
        p = prods[_resolve_pid(prods, pid)]
        lo = limits["vmin"] if vmin is None else vmin
        hi = limits["vmax"] if vmax is None else vmax
        fmask = mask_for_names(s.flag_bits, flagbits.split(",")) if flagbits else 0
        return render.render([p.sci], [(lo, hi)], stretch, invert, p.flags, fmask, flagmode, fmt,
                             bipolar=pq.diff != "none")

    data = await asyncio.get_running_loop().run_in_executor(executor, work)
    return Response(data, media_type=render.FORMATS[fmt], headers={"Cache-Control": "max-age=600"})


# ---------------------------------------------------------------------------------------
# Photometry (spectrum / light curve)
# ---------------------------------------------------------------------------------------
PHOT_COLUMNS = ("key", "obs_id", "detector", "mjd", "date", "epoch_index", "lam_um", "bw_um",
                "flux_ujy", "err_ujy", "bkg_mjysr", "zodi_mjysr", "ok", "saturated", "n_bad_ap",
                "frac_missing", "ap_flag_names", "target_flag_names", "note", "target_ra",
                "target_dec")


@app.get("/api/sessions/{sid}/photometry")
async def photometry(sid: str, request: Request, r_ap: float = 2.0, r_in: float = 5.0,
                     r_out: float = 9.0, format: str = "json"):
    s = _session(sid)
    pq = ProductQuery(request)
    if not (0 < r_ap < r_in < r_out):
        raise HTTPException(400, "need 0 < r_ap < r_in < r_out")
    default = (r_ap, r_in, r_out) == (2.0, 5.0, 9.0) and pq.bad_names == DEFAULT_BAD_FLAGS
    frames = [f for f in s.frames.values() if pq.sel.accepts(f)]
    epochs = epoch_index(frames, pq.window) if frames else {}

    def remeasure(key: str) -> dict:
        """Non-default radii/flags: re-read the cached native cutout and re-measure."""
        obs = next(o for o in s.observations if o.key == key)
        nf = load_cutout(CutoutRequest(obs, *s.center, s.cutout_size).cache_path)
        try:
            ra_t, dec_t = s.position_at(nf.mjd)
            return aperture_photometry(nf, ra_t, dec_t, mask_for_names(nf.flag_bits, pq.bad_names),
                                       r_ap, r_in, r_out).to_json()
        finally:
            nf.hdul.close()

    loop = asyncio.get_running_loop()
    rows = []
    for f in sorted(frames, key=lambda f: f.mjd):
        rec = s.records[f.key]
        ph = rec["phot"] if default else await loop.run_in_executor(executor, remeasure, f.key)
        rows.append({"key": f.key, "obs_id": f.obs_id, "detector": f.detector, "mjd": f.mjd,
                     "date": rec["date"], "epoch_index": epochs.get(f.key),
                     "target_ra": rec.get("target_ra"), "target_dec": rec.get("target_dec"),
                     **{k: ph.get(k) for k in ("lam_um", "bw_um", "flux_ujy", "err_ujy",
                                               "bkg_mjysr", "zodi_mjysr", "ok", "saturated",
                                               "n_bad_ap", "frac_missing", "ap_flag_names",
                                               "target_flag_names", "note")}})
    if format == "csv":
        buf = io.StringIO()
        buf.write("# SPHEREx forced aperture photometry (IMAGE - ZODI - local background)\n")
        buf.write(f"# target ra={s.params.ra} dec={s.params.dec} pm={s.params.pm} "
                  f"pmra={s.params.pmra} pmdec={s.params.pmdec} epoch={s.params.epoch}\n")
        buf.write(f"# r_ap={r_ap} r_in={r_in} r_out={r_out} native pixels (6.15 arcsec); "
                  "no aperture correction; flux in microJansky\n")
        w = csv.DictWriter(buf, fieldnames=PHOT_COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow({**r, "target_flag_names": "|".join(r["target_flag_names"]),
                        "ap_flag_names": "|".join(r["ap_flag_names"] or [])})
        return Response(buf.getvalue(), media_type="text/csv", headers={
            "Content-Disposition": f'attachment; filename="spherex_phot_{s.id}.csv"'})
    return {"rows": rows, "aperture": {"r_ap": r_ap, "r_in": r_in, "r_out": r_out,
                                       "unit": "native pixel (6.15 arcsec)"},
            "n_epochs": (max(epochs.values()) + 1) if epochs else 0}


@app.get("/api/sessions/{sid}/frames/{key}")
def frame_detail(sid: str, key: str):
    s = _session(sid)
    rec = s.records.get(key)
    if rec is None:
        raise HTTPException(404, "no such frame")
    return rec


# ---------------------------------------------------------------------------------------
# Catalogs for overlays
# ---------------------------------------------------------------------------------------
@app.get("/api/catalog/{name}")
async def catalog(name: str, ra: float, dec: float, radius: float = Query(3.0, le=30)):
    """radius in arcmin. Returns positions at the catalog epoch, with proper motions."""
    try:
        return await catalogs.cone(name, ra, dec, radius)
    except KeyError:
        raise HTTPException(404, f"unknown catalog {name!r}")
    except Exception as e:
        raise HTTPException(502, f"catalog query failed: {e}")


@app.get("/api/gaia_pm")
async def gaia_pm(ra: float, dec: float, epoch: float = 2000.0):
    """Gaia DR3 counterpart (for its proper motion): candidates are propagated back to the
    input epoch and must land within 3 arcsec."""
    try:
        m = await catalogs.gaia_best_match(ra, dec, epoch)
    except Exception as e:
        raise HTTPException(502, f"Gaia query failed: {e}")
    if m is None:
        raise HTTPException(404, "no Gaia DR3 counterpart within 3 arcsec at that epoch")
    return m


# ---------------------------------------------------------------------------------------
# Motion prediction from WISE epochs; mover candidates
# ---------------------------------------------------------------------------------------
class WiseMotionRequest(BaseModel):
    ra: float
    dec: float
    epoch: float = 2000.0          # Julian year of (ra, dec)
    pmra: float = 0.0              # mas/yr, a starting guess (0 = unknown)
    pmdec: float = 0.0
    mjds: list[float] = Field(default_factory=list, max_length=5000)   # dates to predict for

    @model_validator(mode="after")
    def _on_the_sky(self):
        coords.check_range(self.ra, self.dec)
        return self


_fits: OrderedDict[tuple, tuple[astrometry.Fit, dict]] = OrderedDict()


async def _wise_fit(req: WiseMotionRequest) -> tuple[astrometry.Fit, dict]:
    key = (round(req.ra, 6), round(req.dec, 6), req.epoch, req.pmra, req.pmdec)
    if key in _fits:
        _fits.move_to_end(key)
        return _fits[key]
    seed = Target(req.ra, req.dec, req.pmra, req.pmdec, req.epoch)
    info = {"seed": "the motion given", "warnings": []}
    if not (req.pmra or req.pmdec):
        info["seed"] = "no motion"
        # No motion known: start from the CatWISE2020 motion of the source at this position.
        try:
            near = (await catalogs.cone("catwise", req.ra, req.dec, 4.0 / 60))["sources"]
        except Exception:
            near = []
        near = [s for s in near if s["pmra"] is not None and s["pmdec"] is not None]
        if near:
            c = min(near, key=lambda s: math.hypot((s["ra"] - req.ra) * math.cos(math.radians(req.dec)),
                                                   s["dec"] - req.dec))
            if math.hypot(c["pmra"], c["pmdec"]) >= 100:
                seed = Target(c["ra"], c["dec"], c["pmra"], c["pmdec"], c["epoch"])
                info["seed"] = f"CatWISE2020 {c['id']}"
    # One cone that covers the whole 2010-2024 track.
    a = seed.position_at(catalogs.WISE_FIRST_MJD)
    b = seed.position_at(catalogs.WISE_LAST_MJD)
    mid = seed.position_at((catalogs.WISE_FIRST_MJD + catalogs.WISE_LAST_MJD) / 2)
    half = math.hypot((a[0] - b[0]) * math.cos(math.radians(mid[1])), a[1] - b[1]) * 3600 / 2
    radius = half + 15.0
    if radius > 300:
        radius = 300.0
        info["warnings"].append("the track is longer than the 300 arcsec search radius; early and late epochs are missing")
    try:
        rows, warn = await catalogs.wise_exposures(mid[0], mid[1], radius)
    except Exception as e:
        raise HTTPException(502, f"WISE query failed: {e}")
    info["warnings"] += warn
    info["tables"] = rows["counts"]
    det = astrometry.Detections(*(np.array(rows[k], dtype=float) for k in ("mjd", "ra", "dec", "sig_ra", "sig_dec")))
    try:
        fit = await asyncio.get_running_loop().run_in_executor(
            executor, lambda: astrometry.match_and_fit(det, seed.ra, seed.dec, seed.pmra, seed.pmdec, seed.epoch))
    except astrometry.FitError as e:
        raise HTTPException(422, str(e))
    _fits[key] = (fit, info)
    while len(_fits) > 32:
        _fits.popitem(last=False)
    return fit, info


@app.post("/api/wise_motion")
async def wise_motion(req: WiseMotionRequest):
    """Position, proper motion and (if detected) parallax fitted to the WISE/NEOWISE
    single-exposure detections of the object at (ra, dec), and the predicted position with
    its 1-sigma error ellipse at each requested MJD."""
    fit, info = await _wise_fit(req)
    until = max([*req.mjds, time.time() / 86400 + 40587.0]) + 180
    out = astrometry.summary(fit, until)
    out["warnings"] = info["warnings"] + out["warnings"]
    out["seed"], out["tables"] = info["seed"], info["tables"]
    out["predictions"] = fit.predict(req.mjds)
    return out


@app.get("/api/movers")
async def movers_endpoint(ra: float, dec: float, radius: float = Query(3.0, gt=0, le=30)):
    """CatWISE2020 sources in the cone (radius in arcmin) whose fitted motion is
    significant, ranked by the classifier's probability that they really move."""
    try:
        coords.check_range(ra, dec)
    except coords.CoordinateError as e:
        raise HTTPException(400, str(e))
    model = movers.load_model()
    if model is None:
        raise HTTPException(503, "the mover model has not been trained on this server")
    try:
        cw, gaia = await asyncio.gather(catalogs.mover_candidates(ra, dec, radius),
                                        catalogs.cone("gaia", ra, dec, radius + 0.2, maglim=99))
    except Exception as e:
        raise HTTPException(502, f"catalog query failed: {e}")
    cands = await asyncio.get_running_loop().run_in_executor(
        executor, lambda: movers.rank(cw, gaia["sources"], catalogs.CATWISE_EPOCH))
    return {"candidates": cands, "n_candidates": len(cw), "epoch": catalogs.CATWISE_EPOCH,
            "model": model.meta}


_TILE = re.compile(r"(Norder\d+/Dir\d+/Npix\d+|Norder3/Allsky)\.(png|jpg)|Moc\.fits")
_MEDIA = {"png": "image/png", "jpg": "image/jpeg", "fits": "application/fits"}
_IMMUTABLE = {"Cache-Control": "public, max-age=31536000, immutable", "Access-Control-Allow-Origin": "*"}


@app.get("/api/hips/spherex/properties")
async def hips_cube_properties():
    """The SPHEREx all-sky cube's properties (the frontend reads its wavelength list)."""
    try:
        text = await hips.cube_properties()
    except Exception as e:
        raise HTTPException(502, f"IRSA HiPS unavailable: {e}")
    return Response(text, media_type="text/plain", headers={"Cache-Control": "max-age=3600"})


@app.get("/api/hips/spherex/{k}/properties")
async def hips_slice_properties(k: int):
    if not 0 <= k < hips.N_SLICES:
        raise HTTPException(404, "no such slice")
    try:
        text = await hips.slice_properties(k)
    except Exception as e:
        raise HTTPException(502, f"IRSA HiPS unavailable: {e}")
    return Response(text, media_type="text/plain", headers={"Cache-Control": "max-age=3600"})


@app.get("/api/hips/spherex/{k}/{rel:path}")
async def hips_tile(k: int, rel: str):
    """One tile of slice ``k`` as a plain image HiPS (see data_access/hips.py)."""
    if not 0 <= k < hips.N_SLICES or not _TILE.fullmatch(rel):
        raise HTTPException(404, "no such tile")
    try:
        data = await hips.tile(k, rel)
    except Exception as e:
        raise HTTPException(502, f"IRSA tile fetch failed: {e}")
    if data is None:
        raise HTTPException(404, "no such tile")
    return Response(data, media_type=_MEDIA[rel.rsplit(".", 1)[1]],
                    headers=_IMMUTABLE)


@app.get("/api/health")
def health():
    return {"ok": True, "registry": registry.source, "sessions": len(store._sessions),
            "cutout_source": settings.cutout_source, "fetched": dict(cutouts.stats)}


# Static frontend (built into frontend/dist).
if settings.frontend_dir.exists():
    app.mount("/assets", StaticFiles(directory=settings.frontend_dir / "assets", check_dir=False),
              name="assets")

    @app.get("/")
    def index():
        # Always revalidate the page; its asset URLs carry content hashes (?v=...).
        return FileResponse(settings.frontend_dir / "index.html",
                            headers={"Cache-Control": "no-cache"})
