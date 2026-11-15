"""Cutouts read directly from the public SPHEREx copy on AWS S3 (s3://nasa-irsa-spherex,
no sign-in), using HTTP byte-range requests.

Why: IRSA's cutout service throttles (~0.4-0.75 cutouts/s) and every IBE cutout carries
a 3.8 MB PSF table. S3 has no such throttling, so reading just the needed rows of each
plane in parallel is several times faster for a first load.

How (per file):
1. Find each HDU's header and data offsets. Files of the same processing version and
   detector usually share a layout, so after the first file the offsets are *predicted*,
   all headers are read in parallel and each one is verified (EXTNAME, size, END card);
   on any mismatch the file is scanned header by header instead.
2. From the IMAGE header's WCS, work out which rows/columns cover the requested region.
3. Read those rows of IMAGE, FLAGS, VARIANCE and ZODI in parallel, plus the small WCS-WAVE
   table. IMAGE/VARIANCE/ZODI are stored plainly (one range each). FLAGS is RICE-compressed
   with one tile per row, so its row descriptors are read first, then just those tiles'
   bytes from the heap, which are decompressed locally.
4. Build a cutout with the same structure and WCS conventions as an IBE cutout
   (CRPIXn, CRPIXnA and CRPIXnW shifted by the cutout origin), so everything downstream
   and the disk cache treat both sources identically. The EPSF table is not copied.
"""
from __future__ import annotations

import asyncio
import io
import logging
import math
import re
import warnings
from dataclasses import dataclass

import httpx
import numpy as np
from astropy.io import fits

from ..config import settings

log = logging.getLogger(__name__)

BLOCK = 2880
NEEDED = ("IMAGE", "FLAGS", "VARIANCE", "ZODI", "WCS-WAVE")
PLANES = ("IMAGE", "FLAGS", "VARIANCE", "ZODI")
_VERSION_RE = re.compile(r"/(l2b-v\d+-\d{4}-\d+)/(\d)/")


class S3Error(RuntimeError):
    pass


def s3_url(ibe_url: str) -> str:
    """IBE product URL -> public S3 HTTPS URL (same path below /ibe/data/spherex/)."""
    marker = "/ibe/data/spherex/"
    if marker not in ibe_url:
        raise S3Error(f"not a SPHEREx IBE URL: {ibe_url}")
    key = ibe_url.split(marker, 1)[1].split("?", 1)[0]
    return f"{settings.s3_base_url.rstrip('/')}/{key}"


@dataclass(frozen=True)
class HduLoc:
    name: str
    header_offset: int
    header_len: int
    data_len: int       # padded to the 2880-byte block
    variable: bool = False  # size differs file to file (has a heap, e.g. compressed FLAGS)

    @property
    def data_offset(self) -> int:
        return self.header_offset + self.header_len


def _padded(n: int) -> int:
    return int(math.ceil(n / BLOCK) * BLOCK)


def _data_len(h: fits.Header) -> int:
    naxis = h.get("NAXIS", 0)
    if naxis == 0:
        return 0
    n = abs(h["BITPIX"]) // 8
    for i in range(1, naxis + 1):
        n *= h[f"NAXIS{i}"]
    n = (n + h.get("PCOUNT", 0)) * h.get("GCOUNT", 1)
    return _padded(n)


def _parse_header(buf: bytes) -> tuple[fits.Header, int] | None:
    """Header from the start of ``buf`` and its padded length; None if END not in buf."""
    for i in range(0, len(buf) - 79, 80):
        if buf[i:i + 8] == b"END     ":
            hlen = _padded(i + 80)
            return fits.Header.fromstring(buf[:hlen].decode("ascii", "replace")), hlen
    return None


class Layouts:
    """Predicted HDU layouts keyed by (processing version, detector)."""

    def __init__(self) -> None:
        self._known: dict[tuple[str, str], tuple[HduLoc, ...]] = {}

    @staticmethod
    def key(url: str) -> tuple[str, str] | None:
        m = _VERSION_RE.search(url)
        return (m.group(1), m.group(2)) if m else None

    def get(self, url: str):
        k = self.key(url)
        return self._known.get(k) if k else None

    def put(self, url: str, locs: tuple[HduLoc, ...]) -> None:
        if (k := self.key(url)):
            self._known[k] = locs


layouts = Layouts()


class S3Reader:
    def __init__(self, client: httpx.AsyncClient, sem: asyncio.Semaphore, url: str):
        self.client, self.sem, self.url = client, sem, url

    async def read(self, start: int, length: int) -> bytes:
        last = ""
        for attempt in range(4):
            try:
                async with self.sem:
                    r = await self.client.get(self.url, timeout=settings.fetch_timeout_s,
                                              headers={"Range": f"bytes={start}-{start + length - 1}"})
                if r.status_code == 206:
                    return r.content
                if r.status_code == 200:  # server ignored Range: slice it ourselves
                    return r.content[start:start + length]
                if 400 <= r.status_code < 500 and r.status_code != 429:
                    raise S3Error(f"HTTP {r.status_code} for {self.url}")  # not worth retrying
                last = f"HTTP {r.status_code}"
            except httpx.TransportError as e:
                last = f"{type(e).__name__}"
            await asyncio.sleep(0.5 * 2 ** attempt)
        raise S3Error(f"range read failed ({last})")

    async def scan(self) -> tuple[list[HduLoc], dict[str, fits.Header]]:
        """Walk the file header by header (one round trip per HDU)."""
        locs, headers, offset = [], {}, 0
        while not all(n in headers for n in NEEDED):
            chunk = 16 * BLOCK
            while True:
                buf = await self.read(offset, chunk)
                parsed = _parse_header(buf)
                if parsed or len(buf) < chunk:
                    break
                chunk *= 4
            if not parsed:
                raise S3Error(f"no FITS header at offset {offset}")
            h, hlen = parsed
            name = str(h.get("EXTNAME", "PRIMARY")).strip()
            loc = HduLoc(name, offset, hlen, _data_len(h), variable=bool(h.get("PCOUNT", 0)))
            locs.append(loc)
            headers[name] = h
            offset = loc.data_offset + loc.data_len
        return locs, headers

    async def headers_from(self, template: tuple[HduLoc, ...]
                           ) -> tuple[list[HduLoc], dict[str, fits.Header]] | None:
        """Read headers at offsets predicted from a previous file's layout.

        Headers are requested in parallel in waves. A wave runs up to and including the next
        HDU whose size varies from file to file (the compressed FLAGS plane); offsets after
        it are only known once its real size is read, so they go in the next wave. That is
        two round trips for SPHEREx files instead of one per HDU, and nothing is ever read
        speculatively past a variable-size HDU (which could point beyond the end of a
        smaller file). Returns None if anything doesn't match; the caller then scans."""
        chain = [l for l in template if l.name != "PRIMARY"]
        last_needed = max(i for i, l in enumerate(chain) if l.name in NEEDED)
        chain = chain[:last_needed + 1]
        locs: list[HduLoc] = [l for l in template if l.name == "PRIMARY"]
        headers: dict[str, fits.Header] = {}
        delta, i = 0, 0
        while i < len(chain):
            k = next((j for j in range(i, len(chain)) if chain[j].variable), len(chain) - 1)
            pending = chain[i:k + 1]
            try:
                bufs = await asyncio.gather(*[self.read(l.header_offset + delta, l.header_len) for l in pending])
            except S3Error:
                return None
            for loc, buf in zip(pending, bufs):
                parsed = _parse_header(buf)
                if not parsed:
                    return None
                h, hlen = parsed
                if str(h.get("EXTNAME", "")).strip() != loc.name or hlen != loc.header_len:
                    return None
                actual = HduLoc(loc.name, loc.header_offset + delta, hlen, _data_len(h), loc.variable)
                locs.append(actual)
                headers[loc.name] = h
                i += 1
                if actual.data_len != loc.data_len:
                    delta += actual.data_len - loc.data_len
                    break  # later offsets were wrong; re-request them
        return locs, headers


def _image_header(table_header: fits.Header) -> fits.Header:
    """Image header equivalent of a tile-compressed (ZIMAGE) table header."""
    from astropy.io.fits.hdu.compressed.header import _bintable_header_to_image_header
    h = _bintable_header_to_image_header(table_header)
    return fits.Header(h.cards) if not isinstance(h, fits.Header) else h


async def _compressed_rows(reader: S3Reader, h: fits.Header, loc: HduLoc, y0: int, y1: int
                           ) -> np.ndarray:
    """Rows [y0, y1) of a RICE_1 tile-compressed image whose tiles are single rows."""
    try:
        from astropy.io.fits.hdu.compressed._codecs import Rice1
    except ImportError as e:  # astropy internals moved: let the caller fall back to IBE
        raise S3Error(f"no RICE decoder available: {e}") from e
    width = h["ZNAXIS1"]
    zvals = {h.get(f"ZNAME{i}", "").strip().upper(): h.get(f"ZVAL{i}") for i in range(1, 10)}
    if (h.get("ZCMPTYPE", "").strip() != "RICE_1" or h.get("ZTILE1") != width or h.get("ZTILE2", 1) != 1
            or h.get("TFIELDS") != 1 or h["ZBITPIX"] not in (8, 16, 32)):
        raise S3Error("unsupported compressed layout")
    row_bytes = h["NAXIS1"]                     # one heap descriptor per table row
    desc_fmt = {8: ">i4", 16: ">i8"}.get(row_bytes)
    if desc_fmt is None:
        raise S3Error(f"unexpected descriptor size {row_bytes}")
    raw = await reader.read(loc.data_offset + y0 * row_bytes, (y1 - y0) * row_bytes)
    desc = np.frombuffer(raw, dtype=desc_fmt).reshape(-1, 2)      # (nbytes, heap offset)
    heap0 = loc.data_offset + h.get("THEAP", row_bytes * h["NAXIS2"])
    lo, hi = int(desc[:, 1].min()), int((desc[:, 1] + desc[:, 0]).max())
    heap = await reader.read(heap0 + lo, hi - lo)
    bytepix = h["ZBITPIX"] // 8
    codec = Rice1(blocksize=int(zvals.get("BLOCKSIZE") or 32),
                  bytepix=int(zvals.get("BYTEPIX") or bytepix), tilesize=width)
    out = np.empty((y1 - y0, width), dtype=f">i{bytepix}")
    for i, (n, off) in enumerate(desc):
        chunk = np.frombuffer(heap, dtype=np.uint8, count=int(n), offset=int(off - lo))
        tile = np.asarray(codec.decode(chunk)).view(f"i{bytepix}")
        out[i] = tile[:width]
    if "BZERO" in h or "BSCALE" in h:  # integer planes are stored unscaled in SPHEREx files
        raise S3Error("scaled compressed data not supported")
    return out


def _region(header: fits.Header, ra: float, dec: float, size_deg: float
            ) -> tuple[int, int, int, int] | None:
    """[x0, x1) x [y0, y1) (0-based) covering a size_deg square around (ra, dec), clipped to
    the detector; None if the position is off the image."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        from .fitsmeta import celestial_wcs
        w = celestial_wcs(header)
        cx, cy = w.world_to_pixel_values(ra, dec)
    nx, ny = header["NAXIS1"], header["NAXIS2"]
    if not (np.isfinite(cx) and np.isfinite(cy)) or not (-0.5 <= cx < nx - 0.5 and -0.5 <= cy < ny - 0.5):
        return None
    scale = 6.15  # arcsec/px; the margin below absorbs the small variation across the array
    half = size_deg * 3600 / scale / 2
    x0, x1 = max(0, int(math.floor(cx - half))), min(nx, int(math.ceil(cx + half)) + 1)
    y0, y1 = max(0, int(math.floor(cy - half))), min(ny, int(math.ceil(cy + half)) + 1)
    return x0, x1, y0, y1


def _shift_wcs(h: fits.Header, x0: int, y0: int) -> fits.Header:
    """Header for a cutout starting at 0-based (x0, y0): the primary, 'A' (detector pixel)
    and 'W' (wavelength lookup) reference pixels all move with the origin, as IBE does."""
    h = h.copy()
    for suffix in ("", "A", "W"):
        for axis, off in (("1", x0), ("2", y0)):
            k = f"CRPIX{axis}{suffix}"
            if k in h:
                h[k] = h[k] - off
    return h


async def fetch_s3_cutout(client: httpx.AsyncClient, sem: asyncio.Semaphore, ibe_url: str,
                          ra: float, dec: float, size_deg: float) -> bytes | None:
    """FITS bytes of the cutout, or None if (ra, dec) is not on this detector image."""
    reader = S3Reader(client, sem, s3_url(ibe_url))
    found = None
    template = layouts.get(ibe_url)
    if template:
        found = await reader.headers_from(template)
    if found is None:
        found = await reader.scan()
        layouts.put(ibe_url, tuple(found[0]))
    locs, headers = found
    by_name = {l.name: l for l in locs}

    img_h = headers["IMAGE"]
    region = _region(img_h, ra, dec, size_deg)
    if region is None:
        return None
    x0, x1, y0, y1 = region
    nx = img_h["NAXIS1"]

    async def plane(name: str) -> np.ndarray:
        h, loc = headers[name], by_name[name]
        if h.get("ZIMAGE"):
            return (await _compressed_rows(reader, h, loc, y0, y1))[:, x0:x1]
        bpp = abs(h["BITPIX"]) // 8
        raw = await reader.read(loc.data_offset + y0 * nx * bpp, (y1 - y0) * nx * bpp)
        dtype = {-32: ">f4", -64: ">f8", 32: ">i4", 16: ">i2", 64: ">i8"}[h["BITPIX"]]
        return np.frombuffer(raw, dtype=dtype).reshape(y1 - y0, nx)[:, x0:x1]

    wave = by_name["WCS-WAVE"]
    *arrays, wave_raw = await asyncio.gather(
        *[plane(n) for n in PLANES],
        reader.read(wave.header_offset, wave.header_len + wave.data_len))

    hdus = [fits.PrimaryHDU()]
    for name, arr in zip(PLANES, arrays):
        h = headers[name]
        if h.get("ZIMAGE"):
            h = _image_header(h)
        h = _shift_wcs(h, x0, y0)
        hdu = fits.ImageHDU(data=np.ascontiguousarray(arr), header=h, name=name)
        hdus.append(hdu)
    hdus.append(fits.BinTableHDU.fromstring(wave_raw))
    hdus[0].header["ORIGIN"] = "spherex_viewer S3 range cutout"
    hdus[0].header["CUTX0"], hdus[0].header["CUTY0"] = x0, y0
    buf = io.BytesIO()
    fits.HDUList(hdus).writeto(buf)
    return buf.getvalue()
