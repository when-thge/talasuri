"""A session = one (target, FOV, release) search. It owns the observation list, the
background fetch/reprojection pipeline, per-frame metadata and the product cache,
and broadcasts progress events to SSE subscribers."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, asdict

import numpy as np
from astropy.time import Time

from ..config import settings
from ..data_access.cutouts import (CutoutError, CutoutRequest, NoOverlap, Paused, fetch_cutout,
                                   is_cached)
from ..data_access.fitsmeta import (DEFAULT_BAD_FLAGS, FlagBit, header_summary, load_cutout,
                                    mask_for_names)
from ..data_access.releases import registry
from ..data_access.resolver import Target, epoch_to_mjd, mjd_to_epoch
from ..data_access.sia import Observation, find_observations
from ..processing.grid import Grid, cutout_size_deg, make_grid
from ..processing.photometry import aperture_photometry
from ..processing.pipeline import GridFrame, reproject_frame

log = logging.getLogger(__name__)

# A search with no browser watching it for this long stops downloading (and resumes when
# a browser reconnects), so abandoned searches don't block the shared download slots.
IDLE_GRACE_S = 20.0

executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="spx-proc")


@dataclass
class SessionParams:
    ra: float
    dec: float
    fov: float = 5.0             # arcmin
    pmra: float = 0.0            # mas/yr (with cos dec)
    pmdec: float = 0.0
    epoch: float = 2000.0        # Julian year of ra/dec
    pm: bool = False             # track proper motion (moves cutout centre + aperture)
    release: str = "all"
    deep: bool = False
    name: str | None = None

    def key(self) -> str:
        pm = (round(self.pmra, 2), round(self.pmdec, 2), round(self.epoch, 3)) if self.pm else None
        s = f"{self.ra:.6f}|{self.dec:.6f}|{self.fov:.3f}|{pm}|{self.release}|{self.deep}"
        return hashlib.sha1(s.encode()).hexdigest()[:12]

    @property
    def target(self) -> Target:
        return Target(self.ra, self.dec, self.pmra if self.pm else 0.0,
                      self.pmdec if self.pm else 0.0, self.epoch, self.name)


def mjd_to_iso(mjd: float) -> str:
    return Time(mjd, format="mjd", scale="utc").isot[:19]


class Session:
    def __init__(self, params: SessionParams):
        self.params = params
        self.id = params.key()
        self.target = params.target
        self.created = time.time()
        self.state = "querying"          # querying | fetching | done | error
        self.message = ""
        self.warnings: list[str] = []
        self.errors: list[str] = []
        self.observations: list[Observation] = []
        self.records: dict[str, dict] = {}      # per-frame metadata (JSON-able)
        self.frames: dict[str, GridFrame] = {}  # successfully processed frames
        self.flag_bits: dict[int, FlagBit] = {}
        self.grid: Grid | None = None
        self.cutout_size = cutout_size_deg(params.fov, settings.pixel_scale_arcsec)
        self.center: tuple[float, float] = (params.ra, params.dec)
        self.subscribers: list[asyncio.Queue] = []
        self.stack_cache: dict = {}             # pipeline stacks, emptied when frames change
        self.product_cache: OrderedDict = OrderedDict()
        self.task: asyncio.Task | None = None
        self.last_watched = time.time()
        self._fetching = False
        if params.fov > settings.warn_fov_arcmin:
            self.warnings.append(
                f"Large field ({params.fov:g}′): each cutout is bigger and processing is slower.")

    # ---- events --------------------------------------------------------------------
    def publish(self, event: dict) -> None:
        for q in list(self.subscribers):
            q.put_nowait(event)

    def progress(self) -> dict:
        n = len(self.observations)
        done = sum(r["status"] != "pending" for r in self.records.values())
        failed = sum(r["status"] == "error" for r in self.records.values())
        return {"type": "progress", "state": self.state, "total": n, "done": done,
                "loaded": len(self.frames), "failed": failed, "message": self.message}

    def watched(self) -> bool:
        if self.subscribers:
            self.last_watched = time.time()
            return True
        return time.time() - self.last_watched < IDLE_GRACE_S

    # ---- pipeline ------------------------------------------------------------------
    def position_at(self, mjd: float) -> tuple[float, float]:
        return self.target.position_at(mjd)

    @property
    def bad_mask(self) -> int:
        return mask_for_names(self.flag_bits, DEFAULT_BAD_FLAGS) if self.flag_bits else 0

    async def run(self) -> None:
        try:
            # With PM tracking, query at the position during the SPHEREx survey era.
            q_ra, q_dec = self.position_at(epoch_to_mjd(2026.0))
            cols = registry.select(self.params.release, self.params.deep)
            if not cols:
                raise RuntimeError(f"no collections for release {self.params.release!r}")
            self.message = f"Querying {', '.join(c.name for c in cols)}"
            self.publish(self.progress())
            obs, errs = await find_observations(cols, q_ra, q_dec)
            self.errors += errs
            if errs and not obs:
                if any(re.search(r"Server error '50[234]", e) for e in errs):
                    raise RuntimeError("The IRSA archive is not responding right now (server error at IRSA, "
                                       "not in this app). Try again in a few minutes. Details: " + "; ".join(errs))
                raise RuntimeError("IRSA query failed: " + "; ".join(errs))
            self.observations = obs
            if not obs:
                self.state, self.message = "done", "No SPHEREx coverage at this position."
                self.publish(self.progress())
                self.publish({"type": "done"})
                return
            if self.target.pmra or self.target.pmdec:
                # Centre the grid on the target at the median epoch of the data, unless
                # that is within half a pixel of the input position (avoids refetching).
                c = self.position_at(float(np.median([o.mjd for o in obs])))
                shift = np.hypot((c[0] - self.params.ra) * np.cos(np.radians(c[1])),
                                 c[1] - self.params.dec) * 3600
                if shift > 0.5 * settings.pixel_scale_arcsec:
                    self.center = c
            self.grid = make_grid(*self.center, self.params.fov, settings.pixel_scale_arcsec)
            for o in obs:
                self.records[o.key] = {
                    "key": o.key, "obs_id": o.obs_id, "detector": o.detector,
                    "collection": o.collection, "release": o.release, "mjd": o.mjd,
                    "date": mjd_to_iso(o.mjd), "epoch": round(mjd_to_epoch(o.mjd), 4),
                    "status": "pending", "url": o.url,
                }
            self.state = "fetching"
            self.message = f"Fetching {len(obs)} cutouts"
            self.publish({"type": "observations", "records": list(self.records.values()),
                          "grid": self.grid.to_json(), "center": self.center})
            self.publish(self.progress())
            await self._fetch_all(obs)
        except Exception as e:  # surfaced to the UI, never crash the server
            log.exception("session %s failed", self.id)
            self.state, self.message = "error", str(e)
            self.errors.append(str(e))
            self.publish(self.progress())
            self.publish({"type": "done"})
            return
        self._finish()

    def _finish(self) -> None:
        """Set the final state after a fetch pass: done, or paused if it was abandoned."""
        n_obs = len(self.observations)
        pending = sum(r["status"] == "pending" for r in self.records.values())
        if pending:
            self.state = "paused"
            self.message = f"Paused (no one watching): {pending} cutouts left"
            self.publish(self.progress())
            return
        self.state = "done"
        n_ok = len(self.frames)
        self.message = (f"Loaded {n_ok}/{n_obs} frames"
                        + (f"; {self.progress()['failed']} failed" if n_ok < n_obs else ""))
        self.publish(self.progress())
        self.publish({"type": "done"})

    async def resume(self) -> None:
        """Continue a paused search (a browser reconnected)."""
        if self.state != "paused" or self._fetching:
            return
        self.last_watched = time.time()
        self.state = "fetching"
        self.message = "Resuming"
        self.publish(self.progress())
        await self._fetch_all([o for o in self.observations
                               if self.records[o.key]["status"] == "pending"])
        self._finish()

    async def _fetch_all(self, obs: list[Observation]) -> None:
        # Cached frames first so the player fills instantly, then time order.
        reqs = [CutoutRequest(o, *self.center, self.cutout_size) for o in obs]
        reqs.sort(key=lambda r: (not is_cached(r), r.obs.mjd))
        self._fetching = True
        try:
            await asyncio.gather(*[self._one(r) for r in reqs])
        finally:
            self._fetching = False

    async def retry_failed(self) -> None:
        failed = [o for o in self.observations if self.records[o.key]["status"] == "error"]
        if not failed:
            return
        for o in failed:
            self.records[o.key]["status"] = "pending"
        self.state = "fetching"
        self.last_watched = time.time()
        self.publish(self.progress())
        await self._fetch_all(failed)
        self._finish()

    async def _one(self, req: CutoutRequest) -> None:
        rec = self.records[req.obs.key]
        try:
            path = await fetch_cutout(req, active=self.watched)
            loop = asyncio.get_running_loop()
            frame, update = await loop.run_in_executor(executor, self._process, req.obs, path)
            rec.update(update)
            if frame is not None:
                self.frames[frame.key] = frame
                self.stack_cache.clear()
                self.product_cache.clear()
        except Paused:
            return  # stays "pending"; resumed if someone comes back
        except NoOverlap as e:
            rec.update(status="nooverlap", error=str(e)[:200])
        except (CutoutError, OSError, ValueError, KeyError) as e:
            rec.update(status="error", error=str(e)[:300])
            log.warning("frame %s failed: %s", req.obs.key, e)
        self.publish({"type": "frame", "record": rec})
        self.publish(self.progress())

    def _process(self, obs: Observation, path) -> tuple[GridFrame | None, dict]:
        nf = load_cutout(path)
        try:
            if not self.flag_bits:
                self.flag_bits = nf.flag_bits
            ra_t, dec_t = self.position_at(nf.mjd)
            phot = aperture_photometry(nf, ra_t, dec_t, mask_for_names(nf.flag_bits, DEFAULT_BAD_FLAGS))
            sci, var, flags = reproject_frame(nf, self.grid)
            gx, gy = self.grid.sky_to_pix(ra_t, dec_t)
            update = {
                "status": "ok" if nf.contains(phot.x, phot.y) else "offtarget",
                "mjd": nf.mjd, "date": mjd_to_iso(nf.mjd), "epoch": round(mjd_to_epoch(nf.mjd), 4),
                "lam_um": phot.lam_um, "bw_um": phot.bw_um,
                "target_ra": ra_t, "target_dec": dec_t,
                "target_grid_xy": [float(gx), float(gy)],
                "target_flags": phot.target_flags, "target_flag_names": phot.target_flag_names,
                "target_bad": bool(phot.target_flags & self.bad_mask),
                "phot": phot.to_json(),
                "header": header_summary(nf.header),
            }
            frame = GridFrame(key=obs.key, obs_id=obs.obs_id, detector=obs.detector, mjd=nf.mjd,
                              lam_um=phot.lam_um, bw_um=phot.bw_um, sci=sci, var=var, flags=flags,
                              target_flags=phot.target_flags,
                              meta={"target_grid_xy": update["target_grid_xy"]})
            return frame, update
        finally:
            nf.hdul.close()

    # ---- JSON ----------------------------------------------------------------------
    def snapshot(self) -> dict:
        return {
            "id": self.id, "params": asdict(self.params), "target": self.target.to_json(),
            "center": self.center, "grid": self.grid.to_json() if self.grid else None,
            "cutout_size_deg": self.cutout_size, "warnings": self.warnings, "errors": self.errors,
            "progress": self.progress(),
            "records": sorted(self.records.values(), key=lambda r: (r["mjd"], r["detector"])),
            "flag_bits": [{"bit": b.bit, "name": b.name, "description": b.description,
                           "default_bad": b.name in DEFAULT_BAD_FLAGS}
                          for b in self.flag_bits.values()],
        }


class SessionStore:
    def __init__(self) -> None:
        self._sessions: OrderedDict[str, Session] = OrderedDict()

    def get(self, sid: str) -> Session | None:
        s = self._sessions.get(sid)
        if s:
            self._sessions.move_to_end(sid)
        return s

    def get_or_create(self, params: SessionParams) -> Session:
        sid = params.key()
        s = self.get(sid)
        if s and s.state != "error":
            return s
        s = Session(params)
        self._sessions[sid] = s
        while len(self._sessions) > settings.max_sessions:
            _, old = self._sessions.popitem(last=False)
            if old.task and not old.task.done():
                old.task.cancel()
        s.task = asyncio.create_task(s.run())
        return s


store = SessionStore()
