"""Object-name suggestions for the search box.

Two sources:
1. A built-in index (``data/names.json.gz``) of ~35k well-known names from SIMBAD: proper
   names, Messier/NGC/IC objects, and much-studied stars and variables. Instant, works
   offline, case/punctuation-insensitive, and understands spelled-out Greek letters and
   constellation genitives ("epsilon indi" finds "eps Ind B"). Rebuild it with
   ``python -m spherex_viewer.build_names``.
2. A live SIMBAD prefix search (CfA mirror, then CDS) for designations outside the index
   (e.g. "HD 2091", "2MASS J0415").

Each suggestion carries ICRS J2000 coordinates and proper motion, so choosing one needs
no further name resolution.
"""
from __future__ import annotations

import asyncio
import csv
import gzip
import io
import json
import logging
import re
import time
from functools import lru_cache
from pathlib import Path

import httpx

from . import http

log = logging.getLogger(__name__)

INDEX_PATH = Path(__file__).resolve().parents[1] / "data" / "names.json.gz"
SIMBAD_TAP_URLS = (
    "https://simbad.cfa.harvard.edu/simbad/sim-tap/sync",
    "https://simbad.cds.unistra.fr/simbad/sim-tap/sync",
)

GREEK = {
    "alf": "alpha", "bet": "beta", "gam": "gamma", "del": "delta", "eps": "epsilon",
    "zet": "zeta", "eta": "eta", "tet": "theta", "iot": "iota", "kap": "kappa",
    "lam": "lambda", "mu": "mu", "nu": "nu", "ksi": "xi", "omi": "omicron", "pi": "pi",
    "rho": "rho", "sig": "sigma", "tau": "tau", "ups": "upsilon", "phi": "phi",
    "chi": "chi", "psi": "psi", "ome": "omega",
}
CONSTELLATIONS = {
    "and": "andromedae", "ant": "antliae", "aps": "apodis", "aqr": "aquarii",
    "aql": "aquilae", "ara": "arae", "ari": "arietis", "aur": "aurigae", "boo": "bootis",
    "cae": "caeli", "cam": "camelopardalis", "cnc": "cancri", "cvn": "canum venaticorum",
    "cma": "canis majoris", "cmi": "canis minoris", "cap": "capricorni", "car": "carinae",
    "cas": "cassiopeiae", "cen": "centauri", "cep": "cephei", "cet": "ceti",
    "cha": "chamaeleontis", "cir": "circini", "col": "columbae", "com": "comae berenices",
    "cra": "coronae australis", "crb": "coronae borealis", "crv": "corvi", "crt": "crateris",
    "cru": "crucis", "cyg": "cygni", "del": "delphini", "dor": "doradus", "dra": "draconis",
    "equ": "equulei", "eri": "eridani", "for": "fornacis", "gem": "geminorum", "gru": "gruis",
    "her": "herculis", "hor": "horologii", "hya": "hydrae", "hyi": "hydri", "ind": "indi",
    "lac": "lacertae", "leo": "leonis", "lmi": "leonis minoris", "lep": "leporis",
    "lib": "librae", "lup": "lupi", "lyn": "lyncis", "lyr": "lyrae", "men": "mensae",
    "mic": "microscopii", "mon": "monocerotis", "mus": "muscae", "nor": "normae",
    "oct": "octantis", "oph": "ophiuchi", "ori": "orionis", "pav": "pavonis", "peg": "pegasi",
    "per": "persei", "phe": "phoenicis", "pic": "pictoris", "psc": "piscium",
    "psa": "piscis austrini", "pup": "puppis", "pyx": "pyxidis", "ret": "reticuli",
    "sge": "sagittae", "sgr": "sagittarii", "sco": "scorpii", "scl": "sculptoris",
    "sct": "scuti", "ser": "serpentis", "sex": "sextantis", "tau": "tauri",
    "tel": "telescopii", "tri": "trianguli", "tra": "trianguli australis", "tuc": "tucanae",
    "uma": "ursae majoris", "umi": "ursae minoris", "vel": "velorum", "vir": "virginis",
    "vol": "volantis", "vul": "vulpeculae",
}
# Solar-system bodies: Sesame/SIMBAD can't resolve them, and they move far too fast for a
# fixed position or a linear proper motion, so the tool can't follow them.
SOLAR_SYSTEM = {
    "sun", "mercury", "venus", "earth", "moon", "mars", "jupiter", "saturn", "uranus",
    "neptune", "pluto", "ceres", "vesta", "pallas", "eris", "haumea", "makemake", "io",
    "europa", "ganymede", "callisto", "titan", "enceladus", "triton", "phobos", "deimos",
}
OTYPE_LABELS = {
    "*": "Star", "PM*": "High proper-motion star", "HPM*": "High proper-motion star",
    "BD*": "Brown dwarf", "BD?": "Brown dwarf candidate", "LM*": "Low-mass star",
    "V*": "Variable star", "Mi*": "Mira variable", "LP*": "Long-period variable",
    "Or*": "Young variable star", "TT*": "T Tauri star", "Y*O": "Young stellar object",
    "Ce*": "Cepheid", "RR*": "RR Lyrae star", "EB*": "Eclipsing binary", "SB*": "Spectroscopic binary",
    "**": "Double star", "WD*": "White dwarf", "C*": "Carbon star", "RG*": "Red giant",
    "s*r": "Red supergiant", "s*b": "Blue supergiant", "Be*": "Be star", "No*": "Nova",
    "SN*": "Supernova", "Pl": "Exoplanet", "G": "Galaxy", "GiG": "Galaxy in group",
    "GiC": "Galaxy in cluster", "Sy2": "Seyfert galaxy", "Sy1": "Seyfert galaxy",
    "SyG": "Seyfert galaxy", "AGN": "Active galaxy", "QSO": "Quasar", "BLL": "Blazar",
    "GlC": "Globular cluster", "OpC": "Open cluster", "Cl*": "Star cluster", "As*": "Stellar association",
    "PN": "Planetary nebula", "HII": "H II region", "SNR": "Supernova remnant",
    "RNe": "Reflection nebula", "DNe": "Dark nebula", "MoC": "Molecular cloud",
    "Cld": "Cloud", "ISM": "Interstellar matter", "GrG": "Group of galaxies",
    "ClG": "Galaxy cluster", "IG": "Interacting galaxies", "PaG": "Galaxy pair",
    "BY*": "Variable star (BY Dra type)", "dS*": "Delta Scuti variable", "Psr": "Pulsar",
    "EmG": "Emission-line galaxy", "LIN": "LINER galaxy", "SBG": "Starburst galaxy",
    "rG": "Radio galaxy", "H2G": "H II galaxy", "LSB": "Low-surface-brightness galaxy",
    "BiC": "Brightest galaxy in cluster", "SFR": "Star-forming region", "Rad": "Radio source",
    "ULX": "Ultraluminous X-ray source", "X": "X-ray source", "IR": "Infrared source",
    "gam": "Gamma-ray source", "EmO": "Emission object", "HH": "Herbig-Haro object",
    "Pl?": "Exoplanet candidate", "Sy*": "Symbiotic star", "Em*": "Emission-line star",
    "Ae*": "Herbig Ae/Be star", "WR*": "Wolf-Rayet star", "OH*": "OH/IR star", "S*": "S-type star",
    "pA*": "Post-AGB star", "AB*": "AGB star", "HB*": "Horizontal-branch star",
    "RS*": "RS CVn variable", "Ro*": "Rotating variable", "Pu*": "Pulsating variable",
    "El*": "Ellipsoidal variable", "Ir*": "Irregular variable", "CV*": "Cataclysmic variable",
    "XB*": "X-ray binary", "LXB": "Low-mass X-ray binary", "HXB": "High-mass X-ray binary",
    "MS*": "Main-sequence star", "SG*": "Supergiant", "sg*": "Supergiant", "Y*?": "Young star candidate",
    "PN?": "Planetary nebula candidate", "BH": "Black hole", "N*": "Neutron star",
    "a2*": "Alpha2 CVn variable", "gD*": "Gamma Dor variable", "bC*": "Beta Cep variable",
    "cC*": "Classical Cepheid", "WV*": "Type II Cepheid", "RV*": "RV Tauri variable",
    "Ev*": "Evolved star", "HS*": "Hot subdwarf", "BS*": "Blue straggler", "SX*": "SX Phe variable",
    "PM?": "High proper-motion star", "LM?": "Low-mass star candidate", "WD?": "White dwarf candidate",
    "Neb": "Nebula", "GNe": "Nebula", "bub": "Bubble", "Cl?": "Cluster candidate", "G?": "Galaxy candidate",
}

_NONWORD = re.compile(r"[^a-z0-9+\-.]+")


def normalize(s: str) -> str:
    """Lower-case, drop apostrophes, collapse everything else to single spaces."""
    s = s.lower().replace("'", "").replace("’", "")
    s = _NONWORD.sub(" ", s)
    return " ".join(w.strip(".") for w in s.split() if w.strip("."))


def expand(label: str) -> str:
    """Search key: the normalized label plus spelled-out Greek letters and constellation
    genitives, so "alpha centauri" / "eps indi" match "alf Cen" / "eps Ind B"."""
    words = normalize(label).split()
    extra = [GREEK.get(w) or CONSTELLATIONS.get(w) for w in words]
    alt = [e for e in extra if e]
    # catalogue + number typed without a space: "M31", "NGC224", "HD209100"
    if len(words) >= 2 and words[0].isalpha() and words[1][:1].isdigit():
        alt.append(words[0] + words[1])
    return " ".join(words + alt)


def display_label(ident: str) -> str:
    """SIMBAD identifier -> what people call it ("NAME Barnard's star" -> "Barnard's star")."""
    s = re.sub(r"^(NAME|\*\*|\*|V\*)\s+", "", ident.strip())
    return re.sub(r"\s+", " ", s)


def otype_label(code: str | None) -> str:
    if not code:
        return ""
    if code in OTYPE_LABELS:
        return OTYPE_LABELS[code]
    if code.endswith("?"):
        base = OTYPE_LABELS.get(code[:-1] + "*") or OTYPE_LABELS.get(code[:-1])
        return f"{base} candidate" if base else "Candidate object"
    return "Star" if code.endswith("*") else code


@lru_cache(maxsize=1)
def load_index() -> list[dict]:
    if not INDEX_PATH.exists():
        log.warning("name index %s missing; run python -m spherex_viewer.build_names", INDEX_PATH)
        return []
    with gzip.open(INDEX_PATH, "rt", encoding="utf-8") as f:
        items = json.load(f)["items"]
    for it in items:
        it["_k"] = expand(it["label"])
        it["_kw"] = it["_k"].split()
        it["_l"] = normalize(it["label"])
        it["_c"] = it["_l"].replace(" ", "")  # compact: "m 31" -> "m31"
    return items


def _score(item: dict, q: str, qwords: list[str]) -> float | None:
    """None = no match. Higher = better. Every query word must be a prefix of some word."""
    kw = item["_kw"]
    for w in qwords:
        if not any(k.startswith(w) for k in kw):
            return None
    label, compact, qc = item["_l"], item["_c"], q.replace(" ", "")
    if label == q or compact == qc:
        rank = 4
    elif label.startswith(q) or compact.startswith(qc):
        rank = 3
    elif item["_k"].startswith(q) or all(a == b for a, b in zip(qwords, label.split())):
        rank = 2
    else:
        rank = 1
    # Popularity (literature references) breaks ties within a rank.
    return rank * 1e6 + min(item.get("n") or 0, 999_999)


def suggest_local(text: str, limit: int = 8) -> list[dict]:
    q = normalize(text)
    if len(q) < 2:
        return []
    qwords = q.split()
    qc = q.replace(" ", "")
    best: dict[str, tuple[float, dict]] = {}
    for it in load_index():
        sc = _score(it, q, qwords)
        if sc is None and it["_c"].startswith(qc):
            sc = 3e6 + min(it.get("n") or 0, 999_999)
        if sc is None:
            continue
        key = it["main_id"]
        if key not in best or sc > best[key][0]:
            best[key] = (sc, it)
    ranked = sorted(best.values(), key=lambda t: -t[0])[:limit]
    return [public(it, "index") for _, it in ranked]


def public(it: dict, source: str) -> dict:
    return {"label": it["label"], "main_id": it["main_id"], "ra": it["ra"], "dec": it["dec"],
            "pmra": it.get("pmra") or 0.0, "pmdec": it.get("pmdec") or 0.0,
            "type": otype_label(it.get("otype")), "source": source}


def solar_system_note(text: str) -> str | None:
    q = normalize(text)
    if q in SOLAR_SYSTEM:
        return (f"{text.strip().title()} is a Solar-System body. It moves too fast across the sky "
                "to be followed with a fixed position, so this tool can't track it.")
    return None


# ---- live SIMBAD fallback --------------------------------------------------------------
_live_cache: dict[str, tuple[float, list[dict]]] = {}
LIVE_TTL_S = 3600


def _adql_prefix(s: str) -> str:
    return s.replace("'", "''").replace("%", "").replace("_", "\\_") + "%"


async def suggest_live(text: str, limit: int = 8, timeout: float = 5.0) -> list[dict]:
    """Prefix search on SIMBAD identifiers (case-sensitive there, so the text is tried as
    typed and upper-cased). Results are cached for an hour."""
    raw = " ".join(text.split())
    if len(raw) < 3:
        return []
    hit = _live_cache.get(raw)
    if hit and time.time() - hit[0] < LIVE_TTL_S:
        return hit[1]
    variants = list(dict.fromkeys([raw, raw.upper()]))

    def adql(v: str) -> str:
        # No ORDER BY / extra filters: they stop SIMBAD using its identifier index (a plain
        # prefix match takes ~1 s, the sorted one >20 s). Popularity sorting happens here.
        return ("SELECT TOP 40 i.id, b.main_id, b.ra, b.dec, b.pmra, b.pmdec, b.otype, b.nbref AS nb "
                "FROM ident AS i JOIN basic AS b ON i.oidref = b.oid "
                f"WHERE i.id LIKE '{_adql_prefix(v)}'")

    rows: list[dict] = []
    client = http.client()
    for url in SIMBAD_TAP_URLS:
        try:
            rs = await asyncio.gather(*[client.post(url, timeout=timeout, data={
                "REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "csv", "QUERY": adql(v)})
                for v in variants])
            if any(r.status_code != 200 or not r.text.startswith("id,") for r in rs):
                continue
            for r in rs:
                rows += list(csv.DictReader(io.StringIO(r.text)))
            break
        except httpx.HTTPError:
            continue
    out, seen = [], set()
    for r in sorted(rows, key=lambda r: -int(r.get("nb") or 0)):
        if r["main_id"] in seen:
            continue
        seen.add(r["main_id"])
        if not r.get("ra"):
            continue
        try:
            out.append(public({"label": display_label(r["id"]), "main_id": r["main_id"],
                               "ra": float(r["ra"]), "dec": float(r["dec"]),
                               "pmra": float(r["pmra"]) if r.get("pmra") else 0.0,
                               "pmdec": float(r["pmdec"]) if r.get("pmdec") else 0.0,
                               "otype": r.get("otype")}, "simbad"))
        except (TypeError, ValueError):
            continue
        if len(out) >= limit:
            break
    _live_cache[raw] = (time.time(), out)
    return out
