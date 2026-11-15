"""Find SPHEREx Spectral Images covering a position (IVOA SIA2 at IRSA)."""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import re
import time
from dataclasses import dataclass, asdict

import httpx
import numpy as np
from astropy.io.votable import parse_single_table

from ..config import settings
from . import http
from .releases import Collection

log = logging.getLogger(__name__)


@dataclass
class Observation:
    key: str              # unique per (obs_id, detector)
    obs_id: str
    detector: int
    collection: str
    release: str
    url: str              # IBE URL of the full MEF file
    mjd: float            # exposure midpoint (UTC MJD)
    t_exptime: float
    em_min_um: float
    em_max_um: float
    res_power: float | None

    def to_json(self) -> dict:
        return asdict(self)


def _cache_path(collection: str, ra: float, dec: float, radius: float):
    h = hashlib.sha1(f"{collection}|{ra:.5f}|{dec:.5f}|{radius:.5f}".encode()).hexdigest()[:16]
    return settings.cache_dir / "sia" / f"{collection}_{h}.json"


def _parse_votable(content: bytes, coll: Collection) -> list[Observation]:
    table = parse_single_table(io.BytesIO(content)).to_table(use_names_over_ids=True)
    out = []
    for row in table:
        band = str(row["energy_bandpassname"])
        m = re.search(r"D(\d)", band)
        if not m:
            continue
        det = int(m.group(1))
        obs_id = str(row["obs_id"])
        res = row["em_res_power"]
        out.append(Observation(
            key=f"{obs_id}_D{det}", obs_id=obs_id, detector=det,
            collection=coll.name, release=coll.release, url=str(row["access_url"]),
            mjd=float(0.5 * (row["t_min"] + row["t_max"])), t_exptime=float(row["t_exptime"]),
            em_min_um=float(row["em_min"]) * 1e6, em_max_um=float(row["em_max"]) * 1e6,
            res_power=None if np.ma.is_masked(res) else float(res),
        ))
    return out


async def query_collection(client: httpx.AsyncClient, coll: Collection, ra: float, dec: float,
                           radius: float = 0.001) -> list[Observation]:
    path = _cache_path(coll.name, ra, dec, radius)
    if path.exists() and time.time() - path.stat().st_mtime < settings.sia_cache_ttl_s:
        return [Observation(**d) for d in json.loads(path.read_text())]
    params = {"COLLECTION": coll.name, "POS": f"CIRCLE {ra} {dec} {radius}", "MAXREC": "100000"}
    last_err: Exception | None = None
    for attempt in range(3):
        try:
            r = await client.get(settings.irsa_sia_url, params=params, timeout=120)
            r.raise_for_status()
            obs = _parse_votable(r.content, coll)
            break
        except (httpx.HTTPError, ValueError) as e:
            last_err = e
            await asyncio.sleep(2 * 2 ** attempt)
    else:
        # IRSA unreachable: an expired cache entry beats no data at all.
        if path.exists():
            log.warning("SIA %s failed (%s); serving stale cache %s", coll.name, last_err, path.name)
            return [Observation(**d) for d in json.loads(path.read_text())]
        raise RuntimeError(f"SIA query failed for {coll.name}: {last_err}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([o.to_json() for o in obs]))
    return obs


def dedupe(obs_lists: list[tuple[Collection, list[Observation]]]) -> list[Observation]:
    """Keep one copy of each (obs_id, detector), preferring the highest-priority release."""
    best: dict[str, tuple[int, Observation]] = {}
    for coll, obs in obs_lists:
        for o in obs:
            if o.key not in best or coll.priority > best[o.key][0]:
                best[o.key] = (coll.priority, o)
    return sorted((o for _, o in best.values()), key=lambda o: (o.mjd, o.detector))


async def find_observations(collections: list[Collection], ra: float, dec: float
                            ) -> tuple[list[Observation], list[str]]:
    """Query all collections in parallel. Returns (observations, errors)."""
    results = await asyncio.gather(
        *[query_collection(http.client(), c, ra, dec) for c in collections], return_exceptions=True)
    ok, errors = [], []
    for c, res in zip(collections, results):
        if isinstance(res, Exception):
            errors.append(f"{c.name}: {res}")
            log.warning("SIA %s failed: %s", c.name, res)
        else:
            ok.append((c, res))
    return dedupe(ok), errors
