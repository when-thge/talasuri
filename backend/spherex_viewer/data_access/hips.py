"""SPHEREx all-sky HiPS, re-served one wavelength slice at a time, with a disk cache.

IRSA publishes the SPHEREx DR1 all-sky map as a HiPS *cube* (102 slices). Aladin Lite 3.8
draws a cube with no lower-resolution fallback: on every zoom step the map goes blank until
the new tiles arrive, and IRSA takes ~1 s per tile. Served as an ordinary single-image HiPS,
the same tiles get Aladin's usual behaviour (the coarser tiles stay on screen while sharper
ones load). Tiles are cached on disk and sent as immutable, so revisits cost nothing.

    {base}/properties                       the cube's properties (for its wavelength list)
    {base}/{slice}/properties               slice ``slice`` described as a plain image HiPS
    {base}/{slice}/Norder{o}/Dir{d}/Npix{n}.png  -> upstream Npix{n}_{slice}.png
    {base}/{slice}/Moc.fits                 the cube's coverage map (same for every slice)
"""
from __future__ import annotations

import asyncio
import re
import time
from pathlib import Path

from ..config import settings
from . import http

N_SLICES = 102
_PROPS_TTL_S = 6 * 3600
# Keys that make Aladin treat the survey as a cube, or move it to another server
# (``hips_service_url*`` lists mirrors, which would bypass this proxy).
_DROP = re.compile(r"^(hips_cube_\w+|data_cube_\w+|dataproduct_type|hips_service_url\w*|"
                   r"custom_tile_format\w*|hips_progenitor_url)\s*=")

_sem = asyncio.Semaphore(16)
_inflight: dict[str, asyncio.Future] = {}
_missing: dict[str, float] = {}           # tile path -> time of the upstream 404
_props: tuple[float, str] | None = None


async def cube_properties() -> str:
    """Upstream properties, without its mirror list (cached for a few hours)."""
    global _props
    if _props and time.time() - _props[0] < _PROPS_TTL_S:
        return _props[1]
    r = await http.client().get(f"{settings.spherex_hips_url}/properties")
    r.raise_for_status()
    text = "\n".join(l for l in r.text.splitlines() if not re.match(r"^hips_service_url\w*\s*=", l))
    _props = (time.time(), text)
    return text


def wavelengths(props: str) -> list[float]:
    m = re.search(r"^data_cube_crval3_arr\s*=\s*(.+)$", props, re.M)
    return [float(v) for v in m.group(1).split()] if m else []


async def slice_properties(k: int) -> str:
    """The cube's properties rewritten to describe slice ``k`` as a plain image HiPS."""
    props = await cube_properties()
    waves = wavelengths(props)
    um = f"{waves[k]:.3f} um" if k < len(waves) else f"slice {k}"
    lines = []
    for l in props.splitlines():
        if _DROP.match(l):
            continue
        if re.match(r"^creator_did\s*=", l):
            l = f"{l.rstrip()}/slice{k}"
        elif re.match(r"^obs_title\s*=", l):
            l = f"{l.rstrip()} ({um})"
        lines.append(l)
    lines.append("dataproduct_type     = image")
    return "\n".join(lines) + "\n"


def _cache_path(k: int, rel: str) -> Path:
    return settings.cache_dir / "hips" / "spherex" / f"s{k}" / rel


async def tile(k: int, rel: str) -> bytes | None:
    """Tile ``rel`` (e.g. ``Norder3/Dir0/Npix300.png`` or ``Norder3/Allsky.png``) of slice
    ``k``, from the disk cache or IRSA. None if IRSA has no such tile."""
    path, key = _cache_path(k, rel), f"{k}/{rel}"
    if rel == "Moc.fits":                  # one coverage map for the whole cube
        path, key = settings.cache_dir / "hips" / "spherex" / "Moc.fits", rel
    if path.exists():
        return path.read_bytes()
    if time.time() - _missing.get(key, 0) < _PROPS_TTL_S:
        return None
    if key in _inflight:                   # Aladin often asks for a tile twice
        return await asyncio.shield(_inflight[key])
    fut: asyncio.Future = asyncio.get_running_loop().create_future()
    _inflight[key] = fut
    try:
        stem, ext = rel.rsplit(".", 1)
        url = f"{settings.spherex_hips_url}/{rel if rel == 'Moc.fits' else f'{stem}_{k}.{ext}'}"
        async with _sem:
            r = await http.client().get(url)
        if r.status_code == 404:
            _missing[key] = time.time()
            data = None
        else:
            r.raise_for_status()
            data = r.content
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".part")
            tmp.write_bytes(data)
            tmp.replace(path)
        fut.set_result(data)
        return data
    except BaseException as e:
        fut.set_exception(e)
        fut.exception()                    # mark retrieved: waiters re-raise it themselves
        raise
    finally:
        _inflight.pop(key, None)
