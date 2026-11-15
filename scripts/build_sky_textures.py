"""Render the Sky Sphere textures once, as static assets (build step; not run by the page).

    .venv/bin/python scripts/build_sky_textures.py [--force] [layer ...]

Reads frontend/sky.config.json and writes frontend/assets/sky/<id>.jpg: an all-sky
equirectangular (CAR) image, RA 0 at the centre, RA increasing to the left, north up.

Per layer, in order:
  1. CDS hips2fits (one request, exactly the projection we want);
  2. the survey's own HiPS ``Norder3/Allsky`` mosaic (CDS or IRSA mirror), resampled from
     HEALPix to CAR here. For a HiPS cube (SPHEREx) the slice nearest ``cube_um`` is used.
Layers that no server can provide are skipped with a message; existing files are kept
unless --force is given. Needs the dev requirements (astropy-healpix comes with reproject).
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import sys
import time
from pathlib import Path

import httpx
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "frontend" / "sky.config.json"
OUT = ROOT / "frontend" / "assets" / "sky"
HIPS2FITS = "https://alasky.cds.unistra.fr/hips-image-services/hips2fits"
ALLSKY_ORDER = 3
CACHE = Path.home() / ".cache" / "spherex_viewer" / "skytex"
Image.MAX_IMAGE_PIXELS = None


def get(client: httpx.Client, url: str, tries: int = 4, **kw) -> httpx.Response:
    """GET with retries on transport errors and 5xx (IRSA drops connections now and then)."""
    for attempt in range(tries):
        try:
            r = client.get(url, **kw)
            if r.status_code < 500:
                r.raise_for_status()
                return r
            err: Exception = RuntimeError(f"HTTP {r.status_code}")
        except httpx.TransportError as e:
            err = e
        time.sleep(2.0 * (attempt + 1))
    raise err


def from_hips2fits(client: httpx.Client, hips_id: str, w: int, h: int) -> Image.Image:
    r = get(client, HIPS2FITS, tries=1, params={
        "hips": hips_id, "width": w, "height": h, "projection": "CAR", "fov": 360, "ra": 0, "dec": 0,
        "format": "jpg"})
    if not r.headers.get("content-type", "").startswith("image/"):
        raise RuntimeError("hips2fits did not return an image")
    return Image.open(io.BytesIO(r.content)).convert("RGB")


def prop(text: str, key: str) -> str | None:
    m = re.search(rf"^{key}\s*=\s*(.+)$", text, re.M)
    return m.group(1).strip() if m else None


def from_allsky(client: httpx.Client, base: str, w: int, h: int, cube_um: float | None) -> Image.Image:
    """Resample a HiPS Norder3/Allsky mosaic (768 tiles, 27 per row) onto the CAR grid."""
    from astropy import units as u
    from astropy.coordinates import SkyCoord
    from astropy_healpix import HEALPix

    props = get(client, f"{base}/properties")
    fmt = "jpg" if "jpeg" in (prop(props.text, "hips_tile_format") or "jpeg").split() else "png"
    suffix = ""
    if cube_um is not None:
        waves = [float(v) for v in (prop(props.text, "data_cube_crval3_arr") or "").split()]
        if not waves:
            raise RuntimeError("not a cube: no data_cube_crval3_arr")
        k = int(np.argmin(np.abs(np.array(waves) - cube_um)))
        suffix = f"_{k}"
        print(f"    cube slice {k} = {waves[k]:.3f} um")
    url = f"{base}/Norder{ALLSKY_ORDER}/Allsky{suffix}.{fmt}"
    cached = CACHE / (hashlib.sha1(url.encode()).hexdigest()[:16] + f".{fmt}")
    if not cached.exists():                        # the mosaics are 5-50 MB; fetch them once
        CACHE.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(get(client, url).content)
    mosaic = np.asarray(Image.open(cached).convert("RGB"))
    tile = mosaic.shape[1] // 27
    sub = int(np.log2(tile))                       # each tile holds 4^sub HEALPix pixels
    nside = 2 ** (ALLSKY_ORDER + sub)

    # CAR grid: column 0 = RA +180 (east is left), row 0 = Dec +90.
    ra = 180.0 - (np.arange(w) + 0.5) * 360.0 / w
    dec = 90.0 - (np.arange(h) + 0.5) * 180.0 / h
    ra2, dec2 = np.meshgrid(ra % 360.0, dec)
    sky = SkyCoord(ra2 * u.deg, dec2 * u.deg, frame="icrs")
    if (prop(props.text, "hips_frame") or "equatorial").startswith("gal"):
        g = sky.galactic
        lon, lat = g.l, g.b
    else:
        lon, lat = sky.ra, sky.dec
    ipix = HEALPix(nside=nside, order="nested").lonlat_to_healpix(lon, lat)
    npix_tile = ipix >> (2 * sub)
    inner = ipix & ((1 << (2 * sub)) - 1)
    # De-interleave the nested index: even bits -> x, odd bits -> y.
    ix = np.zeros_like(inner)
    iy = np.zeros_like(inner)
    for b in range(sub):
        ix |= ((inner >> (2 * b)) & 1) << b
        iy |= ((inner >> (2 * b + 1)) & 1) << b
    # Inside a HiPS tile the image column is the y index and the row is the x index
    # (found by testing all 8 orientations for the one with no seams between tiles).
    col = (npix_tile % 27) * tile + iy
    row = (npix_tile // 27) * tile + ix
    return Image.fromarray(mosaic[row, col])


def build(layer: dict, w: int, h: int, client: httpx.Client) -> Image.Image | None:
    if layer.get("hips2fits"):
        try:
            img = from_hips2fits(client, layer["hips2fits"], w, h)
            print("    source: CDS hips2fits")
            return img
        except Exception as e:  # noqa: BLE001 - try the next source
            print(f"    hips2fits unavailable ({type(e).__name__}: {str(e)[:80]})")
    for base in layer.get("hips", []):
        try:
            img = from_allsky(client, base, w, h, layer.get("cube_um"))
            print(f"    source: {base} (Norder{ALLSKY_ORDER} Allsky, resampled)")
            return img
        except Exception as e:  # noqa: BLE001
            print(f"    {base} unavailable ({type(e).__name__}: {str(e)[:80]})")
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("layers", nargs="*")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    cfg = json.loads(CONFIG.read_text())
    OUT.mkdir(parents=True, exist_ok=True)
    missing = 0
    with httpx.Client(timeout=180, follow_redirects=True) as client:
        for layer in cfg["layers"]:
            if args.layers and layer["id"] not in args.layers:
                continue
            path = OUT / f"{layer['id']}.jpg"
            if path.exists() and not args.force:
                print(f"{layer['id']}: kept {path.relative_to(ROOT)}")
                continue
            print(f"{layer['id']}:")
            img = build(layer, cfg["width"], cfg["height"], client)
            if img is None:
                print("    SKIPPED: no source reachable")
                missing += 1
                continue
            img.save(path, quality=88, optimize=True, progressive=True)
            print(f"    wrote {path.relative_to(ROOT)} ({path.stat().st_size / 1e6:.2f} MB)")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
