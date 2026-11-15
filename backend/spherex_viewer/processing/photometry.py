"""Forced aperture photometry on native (un-resampled) cutouts.

Done on the native pixels, not the reprojected grid, so the VARIANCE plane stays
uncorrelated and the per-pixel wavelength is exact.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field

import numpy as np

from ..data_access.fitsmeta import NativeFrame, decode_flags, mask_for_names, wavelength_at

ARCSEC2_TO_SR = (np.pi / 180.0 / 3600.0) ** 2
MJY_TO_UJY = 1e12


@dataclass
class PhotResult:
    flux_ujy: float
    err_ujy: float
    bkg_mjysr: float          # local background (after zodi subtraction), per pixel
    zodi_mjysr: float         # zodi model at the target
    lam_um: float
    bw_um: float
    x: float                  # target position on the native cutout (0-based)
    y: float
    n_bad_ap: int             # bad pixels inside the aperture
    target_flags: int         # FLAGS value at the nearest pixel
    target_flag_names: list[str]
    ok: bool
    note: str = ""
    saturated: bool = False   # OVERFLOW inside the aperture (core unreliable or blank)
    frac_missing: float = 0.0  # aperture weight on blank (non-finite) pixels
    ap_flag_names: list[str] = field(default_factory=list)  # bad flags present in aperture

    def to_json(self) -> dict:
        d = asdict(self)
        for k, v in d.items():
            if isinstance(v, float) and not np.isfinite(v):
                d[k] = None
        return d


def aperture_weights(shape: tuple[int, int], x0: float, y0: float, r: float,
                     oversample: int = 10) -> np.ndarray:
    """Fractional pixel coverage of a circle (supersampled), 0-based pixel centres."""
    ny, nx = shape
    w = np.zeros(shape)
    x_lo, x_hi = max(int(np.floor(x0 - r - 1)), 0), min(int(np.ceil(x0 + r + 1)), nx - 1)
    y_lo, y_hi = max(int(np.floor(y0 - r - 1)), 0), min(int(np.ceil(y0 + r + 1)), ny - 1)
    if x_lo > x_hi or y_lo > y_hi:
        return w
    sub = (np.arange(oversample) + 0.5) / oversample - 0.5
    yy, xx = np.mgrid[y_lo:y_hi + 1, x_lo:x_hi + 1]
    dx = xx[..., None, None] + sub[None, None, None, :] - x0
    dy = yy[..., None, None] + sub[None, None, :, None] - y0
    w[y_lo:y_hi + 1, x_lo:x_hi + 1] = np.mean(dx ** 2 + dy ** 2 <= r ** 2, axis=(-1, -2))
    return w


def _robust_stats(v: np.ndarray) -> tuple[float, float]:
    """Sigma-clipped (3 sigma, 5 iterations) median and standard deviation."""
    v = v[np.isfinite(v)]
    for _ in range(5):
        if v.size < 5:
            break
        med = np.median(v)
        std = 1.4826 * np.median(np.abs(v - med))
        keep = np.abs(v - med) <= 3 * max(std, 1e-30)
        if keep.all():
            break
        v = v[keep]
    if v.size == 0:
        return np.nan, np.nan
    med = float(np.median(v))
    return med, float(1.4826 * np.median(np.abs(v - med))) if v.size > 1 else np.nan


def aperture_photometry(frame: NativeFrame, ra: float, dec: float, bad_mask: int,
                        r_ap: float = 2.0, r_in: float = 5.0, r_out: float = 9.0) -> PhotResult:
    """Radii in native pixels (6.15"). Flux = sum(w * (I - ZODI - bkg)) * Omega_pix.

    Error: sqrt(sum(w^2 VAR) + (sum w)^2 sigma_bkg^2 / N_annulus), with sigma_bkg the
    robust annulus scatter. Bad pixels are excluded from the background; bad pixels
    inside the aperture are excluded from the sum, counted (n_bad_ap) and the measurement
    is marked not ok. If >20% of the aperture weight is blank (non-finite, e.g. a
    saturated core), no flux is reported. Saturated stars need PSF-wing fitting (Phase 2).
    No aperture correction is applied (PSF FWHM ~9" vs r_ap=12.3" by default).
    """
    x, y = frame.target_pixel(ra, dec)
    lam, bw = wavelength_at(frame.hdul, x, y)
    ny, nx = frame.image.shape
    xi, yi = int(round(x)), int(round(y))
    on_image = 0 <= xi < nx and 0 <= yi < ny
    tflags = int(frame.flags[yi, xi]) if on_image else 0
    names = decode_flags(tflags, frame.flag_bits)
    nan = float("nan")
    if not frame.contains(x, y, margin=-r_ap):
        return PhotResult(nan, nan, nan, nan, lam, bw, x, y, 0, tflags, names, False,
                          "aperture off cutout")

    sci = frame.image.astype(np.float64) - frame.zodi
    var = frame.variance.astype(np.float64)
    bad = ((frame.flags & bad_mask) != 0) | ~np.isfinite(sci) | ~np.isfinite(var)

    yy, xx = np.indices(sci.shape)
    rr = np.hypot(xx - x, yy - y)
    ann = (rr >= r_in) & (rr <= r_out) & ~bad
    bkg, bkg_std = _robust_stats(sci[ann])
    n_ann = int(ann.sum())

    w = aperture_weights(sci.shape, x, y, r_ap)
    in_ap = w > 0
    n_bad = int((bad & in_ap).sum())
    blank = in_ap & (~np.isfinite(sci) | ~np.isfinite(var))
    frac_missing = float(w[blank].sum() / w.sum()) if w.sum() > 0 else 1.0
    ap_flags = int(np.bitwise_or.reduce(frame.flags[in_ap & bad])) if n_bad else 0
    ap_names = decode_flags(ap_flags & bad_mask, frame.flag_bits)
    saturated = bool(ap_flags & mask_for_names(frame.flag_bits, ("OVERFLOW",)))
    good_ap = in_ap & ~bad
    sb_sum = np.sum(w[good_ap] * (sci[good_ap] - bkg))
    var_sum = np.sum(w[good_ap] ** 2 * var[good_ap])
    wsum = np.sum(w[good_ap])
    err2 = var_sum + (wsum ** 2) * (bkg_std ** 2) / max(n_ann, 1)
    omega_sr = frame.omega_arcsec2 * ARCSEC2_TO_SR
    zodi_t = float(frame.zodi[yi, xi]) if on_image else nan
    note = "" if n_ann >= 10 else "few background pixels"
    ok = n_bad == 0 and n_ann >= 10 and np.isfinite(bkg)
    if n_bad:
        note = f"{n_bad} bad pixel(s) in aperture: {','.join(ap_names)}"
    if saturated:
        note = "saturated (OVERFLOW in aperture); " + note
    flux, err = float(sb_sum * omega_sr * MJY_TO_UJY), float(np.sqrt(err2) * omega_sr * MJY_TO_UJY)
    if frac_missing > 0.2:
        # e.g. a saturated core that the pipeline blanked: the sum would be meaningless
        flux = err = nan
        note = f"{frac_missing:.0%} of aperture blank; " + note
    return PhotResult(
        flux_ujy=flux, err_ujy=err, bkg_mjysr=float(bkg), zodi_mjysr=zodi_t, lam_um=lam,
        bw_um=bw, x=x, y=y, n_bad_ap=n_bad, target_flags=tflags, target_flag_names=names,
        ok=bool(ok), note=note.rstrip("; "), saturated=saturated, frac_missing=frac_missing,
        ap_flag_names=ap_names)
