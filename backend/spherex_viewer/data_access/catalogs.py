"""Catalog cone searches for overlays, proper-motion lookup, WISE single-exposure
astrometry and mover candidates (IRSA Gator).

Results include each source's reference epoch and proper motion so the frontend can
propagate positions to the epoch of the displayed frame.
"""
from __future__ import annotations

import hashlib
import json
import math

from ..config import settings
from . import http
from .resolver import Target, epoch_to_mjd, mjd_to_epoch

# CatWISE2020 pm-fit positions (ra_pm/dec_pm) are at MJD 57170.0; PM is in arcsec/yr.
CATWISE_EPOCH = mjd_to_epoch(57170.0)

# IRSA Gator cone search: ~2 s, whereas the same query through IRSA TAP took minutes.
GATOR_URL = "https://irsa.ipac.caltech.edu/cgi-bin/Gator/nph-query"

CATALOGS = {
    "gaia": {
        "label": "Gaia DR3", "table": "gaia_dr3_source",
        "cols": {"id": "source_id", "ra": "ra", "dec": "dec", "pmra": "pmra", "pmdec": "pmdec",
                 "epoch": "ref_epoch", "mag": "phot_g_mean_mag"},
        "maglim": 21, "pm_scale": 1.0, "epoch": None,
    },
    "catwise": {
        "label": "CatWISE2020", "table": "catwise_2020",
        "cols": {"id": "source_name", "ra": "ra_pm", "dec": "dec_pm", "pmra": "pmra",
                 "pmdec": "pmdec", "mag": "w1mpro_pm", "mag2": "w2mpro_pm"},
        "maglim": 18, "pm_scale": 1000.0, "epoch": CATWISE_EPOCH,
    },
}


def _f(v) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


async def _gator(table: str, cols: list[str], ra: float, dec: float, radius_arcsec: float,
                 constraints: str | None = None, timeout: float = 120) -> list[dict]:
    """Cone search of one IRSA table, cached on disk. ``constraints`` is an SQL WHERE
    fragment on the table's columns (evaluated by IRSA)."""
    params = {"catalog": table, "spatial": "cone", "objstr": f"{ra:.6f} {dec:+.6f}",
              "radius": f"{radius_arcsec:.1f}", "radunits": "arcsec", "outfmt": "1",
              "selcols": ",".join(cols)}
    if constraints:
        params["constraints"] = constraints
    key = hashlib.sha1(json.dumps(params, sort_keys=True).encode()).hexdigest()[:20]
    path = settings.cache_dir / "catalogs" / f"{key}.json"
    if path.exists():
        return json.loads(path.read_text())
    r = await http.client().get(GATOR_URL, params=params, timeout=timeout)
    r.raise_for_status()
    rows = parse_ipac_table(r.text)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows))
    return rows


def parse_ipac_table(text: str) -> list[dict]:
    """Minimal IPAC table reader (Gator outfmt=1): '|'-delimited header, fixed-width rows."""
    header: list[tuple[str, int, int]] | None = None
    rows = []
    for line in text.splitlines():
        if line.startswith("\\") or not line.strip():
            if "ERROR" in line.upper():
                raise RuntimeError(line)
            continue
        if line.startswith("|"):
            if header is None:
                bars = [i for i, ch in enumerate(line) if ch == "|"]
                header = [(line[a + 1:b].strip(), a, b) for a, b in zip(bars, bars[1:])]
            continue
        if header is None:
            if "ERROR" in line.upper():
                raise RuntimeError(line.strip())
            continue
        row = {}
        for name, a, b in header:
            v = line[a:b + 1].strip()
            row[name] = None if v in ("null", "") else v
        rows.append(row)
    if header is None:
        raise RuntimeError(f"unexpected catalog response: {text[:200]}")
    return rows


async def cone(name: str, ra: float, dec: float, radius_arcmin: float,
               maglim: float | None = None) -> dict:
    cfg = CATALOGS[name]
    cols = cfg["cols"]
    maglim = cfg["maglim"] if maglim is None else maglim
    rows = await _gator(cfg["table"], list(cols.values()), ra, dec, radius_arcmin * 60, timeout=300)
    out = []
    for r in rows:
        ra_, dec_ = _f(r.get(cols["ra"])), _f(r.get(cols["dec"]))
        mag = _f(r.get(cols["mag"]))
        if ra_ is None or dec_ is None or (mag is not None and mag > maglim):
            continue
        pmra, pmdec = _f(r.get(cols["pmra"])), _f(r.get(cols["pmdec"]))
        out.append({
            "id": r.get(cols["id"]), "ra": ra_, "dec": dec_,
            "pmra": pmra * cfg["pm_scale"] if pmra is not None else None,   # mas/yr
            "pmdec": pmdec * cfg["pm_scale"] if pmdec is not None else None,
            "epoch": _f(r.get(cols.get("epoch", ""))) or cfg["epoch"],
            "mag": mag, "mag2": _f(r.get(cols["mag2"])) if "mag2" in cols else None,
        })
    return {"catalog": name, "label": cfg["label"], "sources": out}


async def gaia_best_match(ra: float, dec: float, epoch: float, radius_arcsec: float | None = None,
                          match_arcsec: float = 3.0) -> dict | None:
    """Gaia DR3 counterpart of (ra, dec) given at ``epoch``.

    Every candidate is propagated from its Gaia epoch (2016.0) back to ``epoch``. The cone
    is wide enough for proper motions up to ~12"/yr (Barnard's Star moved ~160" between
    2000 and 2016). Among candidates landing within ``match_arcsec``, the brightest wins.
    Returns None when nothing matches (e.g. WISE 0855-0714 is too faint for Gaia).
    """
    if radius_arcsec is None:
        radius_arcsec = min(600.0, 30.0 + 12.0 * abs(2016.0 - epoch))
    res = await cone("gaia", ra, dec, radius_arcsec / 60.0)
    cands = []
    for s in res["sources"]:
        if s["pmra"] is None:
            continue
        t = Target(s["ra"], s["dec"], s["pmra"], s["pmdec"], s["epoch"] or 2016.0)
        pra, pdec = t.position_at(epoch_to_mjd(epoch))
        d = math.hypot((pra - ra) * math.cos(math.radians(dec)), pdec - dec) * 3600
        cands.append({**s, "sep_arcsec": d})
    close = [c for c in cands if c["sep_arcsec"] <= match_arcsec]
    if not close:
        return None
    return min(close, key=lambda c: c["mag"] if c["mag"] is not None else 99)


async def mover_candidates(ra: float, dec: float, radius_arcmin: float) -> list[dict]:
    """Raw CatWISE2020 rows (the columns processing/movers.py reads) of every source in
    the cone whose fitted motion is significant; IRSA applies the cut."""
    from ..processing import movers
    return await _gator(CATALOGS["catwise"]["table"], movers.CATWISE_COLS, ra, dec,
                        radius_arcmin * 60, constraints=movers.CANDIDATE_SQL, timeout=300)


# WISE single-exposure source tables: every detection in every exposure, 2010 to 2024.
# (The cryogenic, 3-band and post-cryogenic phases, then the NEOWISE reactivation.)
WISE_EXPOSURE_TABLES = ("allsky_4band_p1bs_psd", "allsky_3band_p1bs_psd", "allsky_2band_p1bs_psd",
                        "neowiser_p1bs_psd")
WISE_FIRST_MJD, WISE_LAST_MJD = 55203.0, 60523.0      # 2010-01-07 .. 2024-08-01
_WISE_COLS = ["ra", "dec", "sigra", "sigdec", "mjd", "w1snr", "w2snr", "qual_frame"]


async def wise_exposures(ra: float, dec: float, radius_arcsec: float) -> tuple[dict, list[str]]:
    """Single-exposure detections of everything in the cone, as arrays (mjd, ra, dec,
    sig_ra, sig_dec; errors in arcsec), plus warnings for tables that could not be read.
    Detections from frames of zero quality score, or with no position error, are left out."""
    import asyncio
    res = await asyncio.gather(*(_gator(t, _WISE_COLS, ra, dec, radius_arcsec, timeout=300)
                                 for t in WISE_EXPOSURE_TABLES), return_exceptions=True)
    out: dict[str, list[float]] = {k: [] for k in ("mjd", "ra", "dec", "sig_ra", "sig_dec")}
    warnings, counts = [], {}
    for table, rows in zip(WISE_EXPOSURE_TABLES, res):
        if isinstance(rows, BaseException):
            if table == WISE_EXPOSURE_TABLES[-1]:
                raise rows                    # NEOWISE is most of the data: no fit without it
            warnings.append(f"{table} unavailable ({type(rows).__name__})")
            continue
        n = 0
        for r in rows:
            v = [_f(r.get(k)) for k in ("mjd", "ra", "dec", "sigra", "sigdec")]
            if None in v or v[3] <= 0 or v[4] <= 0 or v[3] > 2 or v[4] > 2 or _f(r.get("qual_frame")) == 0:
                continue
            for k, x in zip(out, v):
                out[k].append(x)
            n += 1
        counts[table] = n
    return {**out, "counts": counts}, warnings


async def upload_match(table: str, cols: list[str], positions: list[tuple[float, float]],
                       radius_arcsec: float, constraints: str | None = None) -> list[dict]:
    """Rows of an IRSA table within ``radius_arcsec`` of each of many positions, in one
    request (Gator table upload). Each row carries ``cntr_01``, the 1-based index of the
    position it belongs to. Cached on disk."""
    body = "|%14s|%14s|\n|%14s|%14s|\n" % ("ra", "dec", "double", "double")
    body += "".join(" %14.7f %14.7f \n" % p for p in positions)
    data = {"catalog": table, "spatial": "Upload", "uradius": f"{radius_arcsec:g}",
            "uradunits": "arcsec", "outfmt": "1", "selcols": ",".join(cols)}
    if constraints:
        data["constraints"] = constraints
    key = hashlib.sha1((json.dumps(data, sort_keys=True) + body).encode()).hexdigest()[:20]
    path = settings.cache_dir / "catalogs" / f"upload_{key}.json"
    if path.exists():
        return json.loads(path.read_text())
    r = await http.client().post(GATOR_URL, data=data, files={"filename": ("positions.tbl", body)},
                                 timeout=600)
    r.raise_for_status()
    rows = parse_ipac_table(r.text)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows))
    return rows
