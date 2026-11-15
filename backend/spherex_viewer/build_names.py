"""Build the object-name index used for search suggestions.

    python -m spherex_viewer.build_names [--out PATH]

Queries SIMBAD (CfA mirror first, then CDS) for well-known names and writes a gzipped
JSON index (default: spherex_viewer/data/names.json.gz). Re-run to refresh it.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import re
import sys
import time

import httpx

from .data_access.names import INDEX_PATH, SIMBAD_TAP_URLS, display_label

COLS = "i.id, b.main_id, b.ra, b.dec, b.pmra, b.pmdec, b.otype, b.nbref"
JOIN = "FROM ident AS i JOIN basic AS b ON i.oidref = b.oid"
QUERIES = {
    # Proper names: "Barnard's star", "Sirius", "Orion Nebula", ...
    "names": f"SELECT {COLS} {JOIN} WHERE i.id LIKE 'NAME %' AND b.ra IS NOT NULL",
    # Bayer/Flamsteed designations of well-studied stars: "alf Cen", "eps Ind B", "61 Cyg"
    "stars": f"SELECT {COLS} {JOIN} WHERE i.id LIKE '* %' AND b.nbref >= 100 AND b.ra IS NOT NULL",
    # Variable-star names: "R Dra", "RW Aur", "Mira"
    "variables": f"SELECT {COLS} {JOIN} WHERE i.id LIKE 'V* %' AND b.nbref >= 50 AND b.ra IS NOT NULL",
    "messier": f"SELECT {COLS} {JOIN} WHERE i.id LIKE 'M %' AND b.ra IS NOT NULL",
    "ngc": f"SELECT {COLS} {JOIN} WHERE i.id LIKE 'NGC %' AND b.ra IS NOT NULL",
    "ic": f"SELECT {COLS} {JOIN} WHERE i.id LIKE 'IC %' AND b.ra IS NOT NULL",
}
# Keep only plain catalogue numbers ("M 31", "NGC 224A"), not sub-designations.
CATALOG_RE = re.compile(r"^(M|NGC|IC)\s+\d+[A-Z]?$")

# Famous objects whose SIMBAD identifiers are not friendly: alias -> SIMBAD main_id.
ALIASES = {
    "WISE 0855-0714": "WISEA J085510.74-071442.5",
    "Proxima Centauri": "NAME Proxima Centauri",
    "Andromeda Galaxy": "M  31",
    "Galactic Centre": "NAME Galactic Center",
}


def tap(query: str) -> list[dict]:
    last = ""
    for url in SIMBAD_TAP_URLS:
        try:
            r = httpx.post(url, data={"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "csv",
                                      "MAXREC": "500000", "QUERY": query}, timeout=300)
            if r.status_code == 200 and r.text.startswith("id,"):
                return list(csv.DictReader(io.StringIO(r.text)))
            last = f"{url}: HTTP {r.status_code} {r.text[:120]!r}"
        except httpx.HTTPError as e:
            last = f"{url}: {e}"
    raise RuntimeError(f"SIMBAD query failed ({last})")


def to_item(row: dict, label: str | None = None) -> dict | None:
    try:
        ra, dec = float(row["ra"]), float(row["dec"])
    except (TypeError, ValueError):
        return None

    def f(v):
        try:
            return round(float(v), 3)
        except (TypeError, ValueError):
            return None

    return {"label": label or display_label(row["id"]), "main_id": row["main_id"],
            "ra": round(ra, 7), "dec": round(dec, 7), "pmra": f(row.get("pmra")),
            "pmdec": f(row.get("pmdec")), "otype": row.get("otype") or None,
            "n": int(row.get("nbref") or 0)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(INDEX_PATH))
    args = ap.parse_args()
    items: dict[tuple[str, str], dict] = {}
    for name, q in QUERIES.items():
        t = time.time()
        rows = tap(q)
        kept = 0
        for r in rows:
            if name in ("messier", "ngc", "ic") and not CATALOG_RE.match(r["id"].strip()):
                continue
            it = to_item(r)
            if it:
                items[(it["label"], it["main_id"])] = it
                kept += 1
        print(f"{name:10s} {len(rows):6d} rows, kept {kept:6d}  ({time.time() - t:.1f}s)", file=sys.stderr)
    ids = ",".join("'" + m.replace("'", "''") + "'" for m in ALIASES.values())
    rows = tap(f"SELECT {COLS} {JOIN} WHERE b.main_id IN ({ids}) AND i.id = b.main_id")
    by_main = {r["main_id"]: r for r in rows}
    for alias, main_id in ALIASES.items():
        if main_id in by_main and (it := to_item(by_main[main_id], label=alias)):
            items[(alias, main_id)] = it
        else:
            print(f"alias {alias!r}: {main_id!r} not found", file=sys.stderr)
    out = sorted(items.values(), key=lambda it: -it["n"])
    with gzip.open(args.out, "wt", encoding="utf-8") as f:
        json.dump({"built": time.strftime("%Y-%m-%d"), "source": "SIMBAD", "items": out}, f,
                  separators=(",", ":"))
    print(f"wrote {len(out)} names to {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
