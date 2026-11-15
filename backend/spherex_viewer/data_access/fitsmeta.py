"""Reading SPHEREx Spectral Image MEF cutouts: pixels, WCS, wavelength, flag bits.

HDUs (verified against DR1/QR3 files): PRIMARY, IMAGE, FLAGS, VARIANCE, ZODI,
EPSF (binary table of PSFs), WCS-WAVE (spectral lookup table).
"""
from __future__ import annotations

import re
import warnings
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from astropy import log as astropy_log
from astropy.io import fits
from astropy.wcs import WCS, FITSFixedWarning

# astropy logs an INFO about SIP keywords for the spectral (key='W') WCS; that WCS
# deliberately ignores SIP (see spectral_wcs), so the message is noise.
astropy_log.setLevel("WARNING")

# Flags to treat as bad pixels by default (names, resolved to bits per file from the
# MSKNnnnn/MSKMnnnn header keywords). SOURCE (pixel overlaps a known source, ~40% of
# pixels) and FULLSAMPLE (informational) are deliberately not included.
DEFAULT_BAD_FLAGS = ("TRANSIENT", "OVERFLOW", "SUR_ERROR", "NONFUNC", "MISSING_DATA", "HOT",
                     "COLD", "NONLINEAR", "PERSIST", "OUTLIER")

HEADER_SUMMARY_KEYS = ("OBSID", "DETECTOR", "DATE-AVG", "MJD-AVG", "EXPIDN", "BUNIT",
                       "PSF_FWHM", "OMEGA_MEDIAN", "L1DQAFLG", "FINAST", "SPS_TARGET",
                       "NON_SURVEY", "PXSRCMSK", "MATCH_NSTARS")

_MSK_RE = re.compile(r"^MSK([NMD])(\d{4})$")


@dataclass
class FlagBit:
    bit: int
    name: str
    description: str

    @property
    def mask(self) -> int:
        return 1 << self.bit


def parse_flag_bits(header: fits.Header) -> dict[int, FlagBit]:
    """Bit definitions from the FLAGS header (MSKN=name, MSKM=mask, MSKD=description)."""
    raw: dict[int, dict[str, str]] = {}
    for key in header.keys():
        m = _MSK_RE.match(key)
        if m:
            raw.setdefault(int(m.group(2)), {})[m.group(1)] = header[key]
    out = {}
    for n, d in sorted(raw.items()):
        if "M" in d and int(d["M"]) != 1 << n:
            raise ValueError(f"FLAGS plane {n} has mask {d['M']}, expected {1 << n}")
        out[n] = FlagBit(n, str(d.get("N", f"BIT{n}")).strip(), str(d.get("D", "")).strip())
    return out


def mask_for_names(bits: dict[int, FlagBit], names) -> int:
    wanted = {n.upper() for n in names}
    return int(sum(b.mask for b in bits.values() if b.name.upper() in wanted))


def decode_flags(value: int, bits: dict[int, FlagBit]) -> list[str]:
    return [b.name for b in bits.values() if value & b.mask]


def _quiet_wcs(*args, **kwargs) -> WCS:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FITSFixedWarning)
        warnings.simplefilter("ignore", UserWarning)
        return WCS(*args, **kwargs)


# Building a WCS from the full ~275-card IMAGE header spends most of its time
# re-serialising and verifying unrelated cards, so each WCS gets only its own keywords.
_CEL_KEY = re.compile(r"^(NAXIS\d?|WCSAXES|CTYPE\d|CUNIT\d|CRPIX\d|CRVAL\d|CDELT\d|PC\d_\d|CD\d_\d"
                      r"|LONPOLE|LATPOLE|RADESYS|EQUINOX|MJDREF|DATE-OBS|MJD-OBS|A_ORDER|B_ORDER"
                      r"|AP_ORDER|BP_ORDER|A_\d+_\d+|B_\d+_\d+|AP_\d+_\d+|BP_\d+_\d+)$")
_SPEC_KEY = re.compile(r"^(NAXIS\d?|WCSAXESW|CTYPE\dW|CUNIT\dW|CRPIX\dW|CRVAL\dW|CDELT\dW|PC\d_\dW"
                       r"|PV\d_\dW|PS\d_\dW|WCSNAMEW)$")


def _subheader(header: fits.Header, pattern: re.Pattern) -> fits.Header:
    return fits.Header([c for c in header.cards if pattern.match(c.keyword)])


def celestial_wcs(header: fits.Header) -> WCS:
    return _quiet_wcs(_subheader(header, _CEL_KEY))


def spectral_wcs(hdul: fits.HDUList) -> WCS:
    """Spectral WCS per the IRSA cutouts tutorial: lookup table in WCS-WAVE, alternate
    key 'W'. The celestial SIP terms must not be applied to it (the sub-header carries
    none, and .sip is cleared as in the tutorial)."""
    sw = _quiet_wcs(_subheader(hdul["IMAGE"].header, _SPEC_KEY), fobj=hdul, key="W")
    sw.sip = None
    return sw


def wavelength_at(hdul: fits.HDUList, x: float, y: float) -> tuple[float, float]:
    """Central wavelength and bandwidth (microns) at 0-based pixel (x, y) of the IMAGE."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        lam, bw = spectral_wcs(hdul).pixel_to_world_values(x, y)
    return float(lam), float(bw)


@dataclass
class NativeFrame:
    """One detector cutout in its native pixel grid (zodi NOT yet subtracted)."""
    path: Path
    image: np.ndarray
    zodi: np.ndarray
    variance: np.ndarray
    flags: np.ndarray
    wcs: WCS
    header: fits.Header
    flag_bits: dict[int, FlagBit]
    mjd: float
    omega_arcsec2: float
    hdul: fits.HDUList = field(repr=False, default=None)

    def target_pixel(self, ra: float, dec: float) -> tuple[float, float]:
        x, y = self.wcs.world_to_pixel_values(ra, dec)
        return float(x), float(y)

    def contains(self, x: float, y: float, margin: float = 0.5) -> bool:
        ny, nx = self.image.shape
        return -margin <= x <= nx - 1 + margin and -margin <= y <= ny - 1 + margin


def load_cutout(path: Path) -> NativeFrame:
    hdul = fits.open(path, memmap=False)
    by_name = {h.name: h for h in hdul}  # one pass; name lookups on an HDUList are slow
    hdr = by_name["IMAGE"].header
    flag_hdr = by_name["FLAGS"].header
    return NativeFrame(
        path=path,
        image=by_name["IMAGE"].data.astype(np.float32),
        zodi=by_name["ZODI"].data.astype(np.float32),
        variance=by_name["VARIANCE"].data.astype(np.float32),
        flags=by_name["FLAGS"].data.astype(np.int64),
        wcs=celestial_wcs(hdr),
        header=hdr,
        flag_bits=parse_flag_bits(flag_hdr),
        mjd=float(hdr.get("MJD-AVG", hdr.get("MJD-OBS"))),
        omega_arcsec2=float(hdr.get("OMEGA_MEDIAN", 6.15 ** 2)),
        hdul=hdul,
    )


def header_summary(header: fits.Header) -> dict:
    out = {}
    for k in HEADER_SUMMARY_KEYS:
        if k in header:
            v = header[k]
            out[k] = v.strip() if isinstance(v, str) else v
    return out


# ---- Cache slimming --------------------------------------------------------------------
# Every IBE cutout carries the detector's whole EPSF table (441 PSFs, ~3.8 MB) whatever
# the cutout size. Only the PSFs nearest the cutout are kept on disk (for PSF fitting).
EPSF_KEEP = 4


def full_frame_center(header: fits.Header) -> tuple[float, float]:
    """Cutout centre in full-detector pixels (1-based), via the alternate 'A' WCS."""
    ny, nx = header["NAXIS2"], header["NAXIS1"]
    cx = header.get("CRVAL1A", 0.0) + ((nx + 1) / 2 - header.get("CRPIX1A", 1.0))
    cy = header.get("CRVAL2A", 0.0) + ((ny + 1) / 2 - header.get("CRPIX2A", 1.0))
    return float(cx), float(cy)


def slim_hdul(hdul: fits.HDUList, keep: int = EPSF_KEEP) -> fits.HDUList | None:
    """Copy of ``hdul`` whose EPSF table holds only the ``keep`` PSFs nearest the cutout
    centre. Returns None if there is nothing to slim."""
    if "EPSF" not in hdul:
        return None
    eh = hdul["EPSF"]
    if eh.data is None or len(eh.data) <= keep:
        return None
    cx, cy = full_frame_center(hdul["IMAGE"].header)
    d2 = (eh.data["XCENTER"] - cx) ** 2 + (eh.data["YCENTER"] - cy) ** 2
    idx = np.sort(np.argsort(d2)[:keep])
    new_epsf = fits.BinTableHDU(data=eh.data[idx], header=eh.header, name="EPSF")
    new_epsf.header["HISTORY"] = f"spherex_viewer: kept {keep} of {len(eh.data)} PSFs nearest the cutout"
    return fits.HDUList([h if h.name != "EPSF" else new_epsf for h in hdul])


def slim_file(path: Path) -> int:
    """Slim a cached cutout in place (atomically). Returns bytes saved (0 if unchanged)."""
    import os
    before = path.stat().st_size
    with fits.open(path, memmap=False) as hdul:
        slim = slim_hdul(hdul)
        if slim is None:
            return 0
        tmp = path.with_suffix(".slim.part")
        slim.writeto(tmp, overwrite=True)
    os.replace(tmp, path)
    return before - path.stat().st_size


def slim_bytes(content: bytes) -> bytes:
    """Slim a freshly downloaded cutout (FITS bytes). Returns the input unchanged if it
    cannot be slimmed, so a parsing surprise never loses a download."""
    import io
    try:
        with fits.open(io.BytesIO(content), memmap=False) as hdul:
            slim = slim_hdul(hdul)
            if slim is None:
                return content
            buf = io.BytesIO()
            slim.writeto(buf)
            return buf.getvalue()
    except Exception:  # noqa: BLE001 - keep the original bytes on any problem
        return content
