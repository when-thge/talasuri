"""Target input: coordinate parsing, CDS Sesame name resolution, proper motion."""
from __future__ import annotations

import hashlib
import json
import math
import re
import urllib.parse
from dataclasses import dataclass, asdict

import httpx

from ..config import settings
from ..coords import parse_coordinates
from . import http

J2000_MJD = 51544.5
DAYS_PER_YEAR = 365.25


class ResolveError(ValueError):
    """A name that no resolver knows (bad coordinates raise coords.CoordinateError)."""


@dataclass
class Target:
    ra: float                 # deg, ICRS, at ``epoch``
    dec: float
    pmra: float = 0.0         # mas/yr, includes cos(dec)
    pmdec: float = 0.0        # mas/yr
    epoch: float = 2000.0     # Julian year of (ra, dec)
    name: str | None = None
    source: str = "coords"

    def position_at(self, mjd: float) -> tuple[float, float]:
        """Linear (tangent-plane) proper-motion propagation; fine for decades at ~10"/yr."""
        if self.pmra == 0 and self.pmdec == 0:
            return self.ra, self.dec
        dt_yr = (mjd - epoch_to_mjd(self.epoch)) / DAYS_PER_YEAR
        dec = self.dec + self.pmdec * dt_yr / 3.6e6
        ra = self.ra + self.pmra * dt_yr / 3.6e6 / math.cos(math.radians(self.dec))
        return ra % 360.0, dec

    def to_json(self) -> dict:
        return asdict(self)


def epoch_to_mjd(jyear: float) -> float:
    return J2000_MJD + (jyear - 2000.0) * DAYS_PER_YEAR


def mjd_to_epoch(mjd: float) -> float:
    return 2000.0 + (mjd - J2000_MJD) / DAYS_PER_YEAR


def parse_sesame_xml(xml: str) -> dict | None:
    def tag(name: str) -> str | None:
        m = re.search(rf"<{name}>\s*([^<]+?)\s*</{name}>", xml)
        return m.group(1) if m else None

    ra, dec = tag("jradeg"), tag("jdedeg")
    if ra is None or dec is None:
        return None
    out = {"ra": float(ra), "dec": float(dec), "pmra": 0.0, "pmdec": 0.0}
    if (pmra := tag("pmRA")) and (pmdec := tag("pmDE")):
        out["pmra"], out["pmdec"] = float(pmra), float(pmdec)
    out["oname"] = tag("oname")
    return out


def _name_cache_path(name: str):
    key = hashlib.sha1(" ".join(name.lower().split()).encode()).hexdigest()[:16]
    return settings.cache_dir / "names" / f"{key}.json"


async def sesame_resolve(name: str, client: httpx.AsyncClient | None = None) -> Target:
    """Resolve via CDS Sesame, trying each mirror in turn; successful lookups are cached
    on disk (object positions don't change), so known names work even when CDS is down."""
    path = _name_cache_path(name)
    if path.exists():
        return Target(**json.loads(path.read_text()))
    client = client or http.client()
    errors: list[str] = []
    for base in settings.sesame_urls:
        try:
            r = await client.get(f"{base}?{urllib.parse.quote(name.strip())}", timeout=15,
                                 follow_redirects=True)
            r.raise_for_status()
        except httpx.HTTPError as e:
            errors.append(f"{urllib.parse.urlsplit(base).netloc}: {type(e).__name__}")
            continue
        d = parse_sesame_xml(r.text)
        if d is None:
            raise ResolveError(f"Sesame could not resolve {name!r}")
        # Sesame (SIMBAD) positions are ICRS at epoch J2000.
        t = Target(ra=d["ra"], dec=d["dec"], pmra=d["pmra"], pmdec=d["pmdec"], epoch=2000.0,
                   name=d.get("oname") or name, source="sesame")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(t.to_json()))
        return t
    raise ResolveError("Sesame lookup failed (" + "; ".join(errors) + ")")


async def resolve(text: str) -> Target:
    coords = parse_coordinates(text)
    if coords is not None:
        return Target(ra=coords[0], dec=coords[1], source="coords")
    return await sesame_resolve(text)
