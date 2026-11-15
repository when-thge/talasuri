"""Data-release registry.

SPHEREx collections are discovered from IRSA's ObsCore table, so a new release
(e.g. ``spherex_qr4``) shows up without code changes. ``releases.toml`` can
relabel, hide or reprioritise collections.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
import tomllib
from dataclasses import dataclass, asdict

from ..config import settings
from . import http

log = logging.getLogger(__name__)

# North and south ecliptic poles (ICRS), sampled for collection discovery.
DISCOVERY_POINTS = [(270.0, 66.56), (90.0, -66.56)]

# Used until the first successful discovery, or if IRSA's TAP service is unreachable.
BOOTSTRAP_COLLECTIONS = ["spherex_dr1", "spherex_dr1_deep", "spherex_qr3", "spherex_qr3_deep"]

_NAME_RE = re.compile(r"^spherex_(?P<kind>dr|qr)(?P<num>\d*)(?:_(?P<variant>[a-z0-9]+))?$")


@dataclass
class Collection:
    name: str
    release: str          # e.g. "dr1", "qr3"
    variant: str          # "wide", "deep", ...
    label: str
    priority: int
    n_rows: int | None = None
    mjd_min: float | None = None
    mjd_max: float | None = None

    def to_json(self) -> dict:
        return asdict(self)


def parse_collection_name(name: str) -> tuple[str, str, int] | None:
    """Return (release, variant, default_priority) for a SPHEREx collection name."""
    m = _NAME_RE.match(name)
    if not m:
        return None
    kind, num, variant = m["kind"], m["num"] or "1", m["variant"] or "wide"
    # DR outranks QR; within a kind, higher numbers are newer.
    priority = (100 if kind == "dr" else 0) + int(num)
    return f"{kind}{m['num']}", variant, priority


def _load_overrides() -> dict:
    try:
        with open(settings.releases_file, "rb") as f:
            return tomllib.load(f)
    except FileNotFoundError:
        return {}


def build_collections(rows: list[dict]) -> list[Collection]:
    """rows: dicts with obs_collection, n, t0, t1 (from TAP or bootstrap)."""
    ov = _load_overrides()
    hidden = set(ov.get("hide", {}).get("collections", []))
    labels = ov.get("labels", {})
    prio = ov.get("priority", {})
    out = []
    for r in rows:
        name = r["obs_collection"]
        parsed = parse_collection_name(name)
        if parsed is None or name in hidden:
            continue
        release, variant, p = parsed
        if variant == "cal":
            continue
        out.append(Collection(
            name=name, release=release, variant=variant,
            label=labels.get(name, f"{release.upper()} ({variant})"),
            priority=int(prio.get(name, p)),
            n_rows=r.get("n"), mjd_min=r.get("t0"), mjd_max=r.get("t1"),
        ))
    out.sort(key=lambda c: (-c.priority, c.variant))
    return out


class ReleaseRegistry:
    def __init__(self) -> None:
        self.collections: list[Collection] = build_collections(
            [{"obs_collection": c} for c in BOOTSTRAP_COLLECTIONS])
        self.updated: float | None = None
        self.source = "bootstrap"

    async def refresh(self) -> None:
        """Discover collections from IRSA. A full ``GROUP BY obs_collection`` over
        spherex.obscore takes >5 min, so we sample the two ecliptic poles instead: SPHEREx
        observes them continuously (they are also the deep fields), so every wide and deep
        collection has data there. Two indexed cone queries take ~30 s."""
        results = await asyncio.gather(
            *[self._collections_near(ra, dec) for ra, dec in DISCOVERY_POINTS],
            return_exceptions=True)
        names: set[str] = set()
        for r in results:
            if isinstance(r, Exception):
                raise r  # partial knowledge could drop a live collection; keep the old list
            names |= r
        cols = build_collections([{"obs_collection": n} for n in sorted(names)])
        if cols:
            new = {c.name for c in cols} - {c.name for c in self.collections}
            if new:
                log.info("SPHEREx collections discovered: %s", sorted(new))
            self.collections, self.updated, self.source = cols, time.time(), "irsa"

    @staticmethod
    async def _collections_near(ra: float, dec: float) -> set[str]:
        query = ("SELECT DISTINCT obs_collection FROM spherex.obscore WHERE "
                 f"CONTAINS(POINT('ICRS',s_ra,s_dec),CIRCLE('ICRS',{ra},{dec},1.0))=1")
        r = await http.client().post(f"{settings.irsa_tap_url}/sync", timeout=300,
                                     data={"QUERY": query, "FORMAT": "csv", "LANG": "ADQL"})
        r.raise_for_status()
        lines = [ln.strip() for ln in r.text.strip().splitlines() if ln.strip()]
        if not lines or lines[0] != "obs_collection":
            raise RuntimeError(f"unexpected TAP response: {r.text[:200]}")
        return set(lines[1:])

    async def run_forever(self) -> None:
        while True:
            try:
                await self.refresh()
            except Exception as e:  # keep the previous registry on failure
                log.warning("release registry refresh failed: %s", e)
            await asyncio.sleep(settings.registry_refresh_s)

    def releases(self) -> list[str]:
        seen: list[str] = []
        for c in self.collections:
            if c.release not in seen:
                seen.append(c.release)
        return seen

    def select(self, release: str = "all", deep: bool = False) -> list[Collection]:
        """Collections to query. ``release='all'`` merges every release (deduped later
        by priority) because releases cover different time ranges."""
        cols = [c for c in self.collections if deep or c.variant == "wide"]
        if release != "all":
            cols = [c for c in cols if c.release == release]
        return cols

    def to_json(self) -> dict:
        return {"collections": [c.to_json() for c in self.collections],
                "releases": self.releases(), "default": "all",
                "updated": self.updated, "source": self.source}


registry = ReleaseRegistry()
