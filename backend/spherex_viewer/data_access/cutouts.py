"""Cutouts, fetched in parallel and cached on disk.

Source (``settings.cutout_source``): byte ranges from the public S3 copy (fast, see
s3cutouts.py), IRSA's IBE cutout service, or "auto" = S3 with IBE as the fallback for any
image S3 can't serve. Both produce identical cutouts (verified pixel by pixel).

Cache key: (obs_id, detector, center, size), as a file path. Cutouts are immutable
for a given product URL, so cached files never expire; the URL's version string
(e.g. ``l2b-v27-2026-197``) is hashed into the key so reprocessed data is refetched.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import httpx

from ..config import settings
from . import http
from .fitsmeta import slim_bytes
from .sia import Observation

log = logging.getLogger(__name__)

RETRY_STATUS = {429, 500, 502, 503, 504}


class CutoutError(RuntimeError):
    pass


class NoOverlap(CutoutError):
    """The requested center is not on this image (IBE returns an error)."""


class Paused(CutoutError):
    """The owning session no longer wants this cutout (nobody is watching it)."""


@dataclass(frozen=True)
class CutoutRequest:
    obs: Observation
    ra: float
    dec: float
    size_deg: float

    @property
    def url(self) -> str:
        return f"{self.obs.url}?center={self.ra:.6f},{self.dec:.6f}&size={self.size_deg:.5f}"

    @property
    def cache_path(self) -> Path:
        version = hashlib.sha1(self.obs.url.encode()).hexdigest()[:8]
        name = (f"{self.obs.obs_id}_D{self.obs.detector}_{self.ra:.5f}_{self.dec:+.5f}"
                f"_{self.size_deg:.4f}_{version}.fits")
        return settings.cache_dir / "cutouts" / self.obs.collection / name


def is_cached(req: CutoutRequest) -> bool:
    return req.cache_path.exists()


def _write_cache(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.{random.randrange(1 << 30)}.part")
    tmp.write_bytes(content)
    os.replace(tmp, path)  # atomic: never leave half-written cache entries


@dataclass
class Limits:
    """The concurrency limits that protect each service (shared by every session)."""
    ibe: asyncio.Semaphore        # IBE requests (IRSA throttles above ~8)
    s3: asyncio.Semaphore         # individual S3 range requests
    s3_files: asyncio.Semaphore   # files in flight on S3 (lets early files teach the layout)
    inflight: dict[Path, asyncio.Future]   # cutouts being downloaded right now


_limits: tuple[asyncio.AbstractEventLoop, Limits] | None = None
stats: dict = {}                             # how many cutouts came from where (see /api/health)


def limits() -> Limits:
    global _limits
    loop = asyncio.get_running_loop()
    if _limits is None or _limits[0] is not loop:
        _limits = (loop, Limits(ibe=asyncio.Semaphore(settings.fetch_concurrency),
                                s3=asyncio.Semaphore(settings.s3_concurrency),
                                s3_files=asyncio.Semaphore(max(4, settings.s3_concurrency // 3)),
                                inflight={}))
    return _limits[1]


async def fetch_cutout(req: CutoutRequest, active: Callable[[], bool] | None = None) -> Path:
    """The cached cutout for ``req``, downloading it only if needed.

    The disk cache is checked first, and a cutout that another session is already
    downloading is awaited instead of being requested again, so no cutout is ever fetched
    twice. ``active`` is checked before work starts and whenever a slot frees up: if it
    returns False the request is dropped (raises Paused) so abandoned searches don't hold
    slots.
    """
    path = req.cache_path
    if path.exists():
        return path
    inflight = limits().inflight
    while path in inflight:
        try:
            return await asyncio.shield(inflight[path])
        except Paused:                     # the other session gave up; fetch it ourselves
            if path.exists():
                return path
    fut: asyncio.Future = asyncio.get_running_loop().create_future()
    inflight[path] = fut
    try:
        await _download(req, active)
        fut.set_result(path)
        return path
    except BaseException as e:
        fut.set_exception(e)
        fut.exception()                    # mark retrieved: waiters re-raise it themselves
        raise
    finally:
        inflight.pop(path, None)


async def _download(req: CutoutRequest, active: Callable[[], bool] | None) -> None:
    lim, client, path = limits(), http.client(), req.cache_path
    if settings.cutout_source in ("s3", "auto"):
        from .s3cutouts import S3Error, fetch_s3_cutout
        try:
            async with lim.s3_files:
                if active is not None and not active():
                    raise Paused(req.obs.key)
                content = await fetch_s3_cutout(client, lim.s3, req.obs.url, req.ra, req.dec,
                                                req.size_deg)
            if content is None:
                raise NoOverlap("target not on this detector image")
            _write_cache(path, content)
            stats["s3"] = stats.get("s3", 0) + 1
            return
        except (S3Error, httpx.HTTPError, OSError, ValueError, KeyError) as e:
            if settings.cutout_source == "s3":
                raise CutoutError(f"S3: {e}") from e
            stats["ibe_fallback"] = stats.get("ibe_fallback", 0) + 1
            reason = f"{type(e).__name__}: {str(e)[:80]}"
            errs = stats.setdefault("s3_errors", {})
            errs[reason] = errs.get(reason, 0) + 1
            log.warning("S3 failed for %s (%s); using IBE", req.obs.key, reason)
    await _fetch_ibe(lim.ibe, client, req, active)


async def _fetch_ibe(sem: asyncio.Semaphore, client: httpx.AsyncClient, req: CutoutRequest,
                     active: Callable[[], bool] | None) -> None:
    path = req.cache_path
    last: str = ""
    for attempt in range(settings.fetch_retries + 1):
        try:
            async with sem:
                if active is not None and not active():
                    raise Paused(req.obs.key)
                r = await client.get(req.url, timeout=settings.fetch_timeout_s)
            if r.status_code == 200 and r.content[:6] == b"SIMPLE":
                # Drop the detector-wide PSF table (~95% of the bytes) before caching.
                content = await asyncio.to_thread(slim_bytes, r.content)
                _write_cache(path, content)
                stats["ibe"] = stats.get("ibe", 0) + 1
                return
            if r.status_code in RETRY_STATUS:
                last = f"HTTP {r.status_code}"
            else:
                text = r.text[:300]
                if "overlap" in text.lower() or "outside" in text.lower():
                    raise NoOverlap(text)
                raise CutoutError(f"HTTP {r.status_code}: {text}")
        except (httpx.TimeoutException, httpx.TransportError) as e:
            last = f"{type(e).__name__}: {e}"
        # Exponential backoff with jitter keeps us polite when IRSA is throttling.
        await asyncio.sleep(min(30.0, 1.5 * 2 ** attempt) * (0.5 + random.random()))
    raise CutoutError(f"gave up after {settings.fetch_retries + 1} attempts ({last})")
