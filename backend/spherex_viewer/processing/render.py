"""Display limits, brightness stretches and image encoding: the one rendering path for
single frames, stacks, difference images and colour composites.

Science pixels are never tinted or styled: a greyscale product is a neutral grey ramp, and
the only colour ever added is the explicit bad-pixel overlay the user switches on.
"""
from __future__ import annotations

import io
import warnings

import numpy as np
from PIL import Image

STRETCHES = ("linear", "asinh", "log", "sqrt")
FORMATS = {"png": "image/png", "webp": "image/webp"}
NAN_GREY = 40
MASK_RGB = (255, 0, 200)


SPARSE_RATIO = 10.0     # bright range / dark range above which a field counts as sparse
BIPOLAR_ASINH_A = 1.0   # asinh softening for difference images (0.1 for normal images)
DIFF_SIGMAS = 8.0       # least half-range of a difference image, in noise sigma


def limits(arrays: list[np.ndarray], symmetric: bool = False, max_samples: int = 2_000_000
           ) -> tuple[float, float]:
    """Display limits shared by a set of images, chosen so that background noise takes up
    little of the grey scale while every pixel value stays untouched.

    Normal images: 1 % .. 99.5 % of the finite pixels. On a sparse field (stars on empty
    sky: the bright range is over ``SPARSE_RATIO`` times the dark one) the black point moves
    up to background + 1 sigma, so the sky is flat and only sources carry tone. Fields
    filled by extended emission keep the 1 % point, which would otherwise be clipped.

    Difference images (``symmetric``): +-m about zero, m = the 99th percentile of |value|
    but at least ``DIFF_SIGMAS`` sigma, so pure noise stays near mid-grey.

    Sigma is the robust scatter, 1.4826 x the median absolute deviation."""
    finite = [a[np.isfinite(a)].ravel() for a in arrays]
    vals = np.concatenate(finite) if finite else np.array([])
    if vals.size > max_samples:
        vals = vals[:: vals.size // max_samples + 1]
    if symmetric:
        # The reference minus itself is exactly zero everywhere; counting those pixels
        # would understate the noise of the real differences.
        vals = vals[vals != 0]
        if vals.size == 0:
            return -1.0, 1.0
        sigma = 1.4826 * float(np.median(np.abs(vals - np.median(vals))))
        m = max(float(np.percentile(np.abs(vals), 99.0)), DIFF_SIGMAS * sigma) or 1e-6
        return -m, m
    if vals.size == 0:
        return 0.0, 1.0
    lo, med, hi = np.percentile(vals, [1.0, 50.0, 99.5])
    sigma = 1.4826 * float(np.median(np.abs(vals - med)))
    if sigma > 0 and hi - med > SPARSE_RATIO * (med - lo) and med + sigma < hi:
        lo = med + sigma
    if hi <= lo:
        hi = lo + 1e-6
    return float(lo), float(hi)


def stretch(arr: np.ndarray, vmin: float, vmax: float, mode: str = "linear",
            invert: bool = False, asinh_a: float = 0.1, bipolar: bool = False) -> np.ndarray:
    """Map to [0, 1]. NaNs stay NaN.

    ``bipolar`` is for difference images: the curve is applied to the distance from the
    middle of the range, the same way on both sides, so the middle (zero for auto limits)
    is exactly mid-grey and brightening and fading look alike. Without it a non-linear
    curve would push zero far from mid-grey."""
    if bipolar:
        centre, half = 0.5 * (vmin + vmax), 0.5 * (vmax - vmin)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            u = np.clip((arr - centre) / half, -1.0, 1.0)
        # asinh uses a gentle knee here: the default one is tuned to lift faint sources off
        # a dark sky, and around zero it would mostly magnify the noise.
        s = np.sign(u) * stretch(np.abs(u), 0.0, 1.0, mode, asinh_a=BIPOLAR_ASINH_A)
        t = 0.5 + 0.5 * s
        return 1.0 - t if invert else t
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        t = np.clip((arr - vmin) / (vmax - vmin), 0.0, 1.0)
        if mode == "asinh":
            t = np.arcsinh(t / asinh_a) / np.arcsinh(1.0 / asinh_a)
        elif mode == "log":
            t = np.log10(1.0 + 1000.0 * t) / np.log10(1001.0)
        elif mode == "sqrt":
            t = np.sqrt(t)
        elif mode != "linear":
            raise ValueError(f"unknown stretch {mode!r}")
    return 1.0 - t if invert else t


def encode(pixels: np.ndarray, fmt: str = "png") -> bytes:
    """pixels: (ny, nx) or (ny, nx, 3) uint8 in FITS orientation (row 0 = south); the
    encoded image is north-up. Both formats are lossless; grey images stay single-channel."""
    img = Image.fromarray(np.ascontiguousarray(pixels[::-1]))
    buf = io.BytesIO()
    if fmt == "webp":
        img.save(buf, format="WEBP", lossless=True, quality=60, method=3)
    elif fmt == "png":
        img.save(buf, format="PNG", optimize=False, compress_level=6)
    else:
        raise ValueError(f"unknown image format {fmt!r}")
    return buf.getvalue()


def render(channels: list[np.ndarray], limits: list[tuple[float, float]], mode: str,
           invert: bool = False, flags: np.ndarray | None = None, flag_mask: int = 0,
           flag_mode: str = "off", fmt: str = "png", bipolar: bool = False) -> bytes:
    """Stretch and encode one image (``bipolar``: a difference image, see stretch()).

    One channel gives a grey image; ``flag_mode`` 'overlay' tints the pixels whose FLAGS
    match ``flag_mask`` and 'mask' blanks them. Three channels give a false-colour
    composite: a pixel missing in any channel (e.g. a saturated core that the pipeline
    blanked, which happens at different radii at different wavelengths) is shown as neutral
    "no data" grey in all three. Zeroing just the missing channel would paint fake colours:
    black centres with red/magenta/cyan rims around bright stars.
    """
    if len(channels) == 1:
        t = stretch(channels[0], *limits[0], mode, invert, bipolar=bipolar)
        out = np.where(np.isfinite(t), np.round(t * 255), NAN_GREY).astype(np.uint8)
        if flags is not None and flag_mask and flag_mode != "off":
            hit = (flags & flag_mask) != 0
            if flag_mode == "mask":
                out[hit] = NAN_GREY
            else:
                out = np.repeat(out[..., None], 3, axis=2)
                out[hit] = (0.45 * out[hit] + 0.55 * np.array(MASK_RGB)).astype(np.uint8)
        return encode(out, fmt)
    planes, valid = [], None
    for arr, (lo, hi) in zip(channels, limits):
        t = stretch(arr, lo, hi, mode)
        ok = np.isfinite(t)
        valid = ok if valid is None else valid & ok
        planes.append(np.where(ok, np.round(t * 255), 0).astype(np.uint8))
    out = np.stack(planes, axis=-1)
    out[~valid] = NAN_GREY
    return encode(out, fmt)
