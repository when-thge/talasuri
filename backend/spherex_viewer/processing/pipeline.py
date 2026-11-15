"""The image pipeline: reproject -> stack -> difference. One implementation, with the
display mode and the difference mode as parameters.

    reproject_frame()   native cutout -> the common grid. Runs once per frame, when the
                        cutout arrives; everything below reuses those arrays.
    build_products()    frames -> displayable products for a mode ("frames", "detector",
                        "epoch", "wave", "rgb"), optionally differenced ("median", "ref").
"""
from __future__ import annotations

import warnings
from collections.abc import MutableMapping
from dataclasses import dataclass, field, replace
from functools import lru_cache

import numpy as np
from scipy.ndimage import map_coordinates

from ..data_access.fitsmeta import NativeFrame
from ..data_access.resolver import mjd_to_epoch
from .grid import Grid

MODES = ("frames", "detector", "epoch", "wave", "rgb")
DIFFS = ("none", "median", "ref")


# ---------------------------------------------------------------------------------------
# Stage 1: reprojection
# ---------------------------------------------------------------------------------------
@lru_cache(maxsize=32)
def _grid_world(grid: Grid) -> tuple[np.ndarray, np.ndarray]:
    """Sky coordinates of every output pixel (cached: the grid is shared by all frames)."""
    yy, xx = np.indices(grid.shape, dtype=float)
    ra, dec = grid.wcs.pixel_to_world_values(xx, yy)
    return ra, dec


def reproject_frame(frame: NativeFrame, grid: Grid) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (sci, variance, flags) on ``grid``.

    sci is IMAGE - ZODI in MJy/sr (surface brightness is conserved by interpolation;
    the grid has the native plate scale, so no flux rescaling is needed). VARIANCE is
    interpolated the same way; FLAGS use nearest-neighbour so bit patterns stay intact.
    Pixels off the cutout are NaN / flag 0 (zero weight in stacks).

    The output->input pixel mapping (including SIP distortion) is computed once and
    applied to all three planes; this is equivalent to three reproject_interp calls
    (bilinear / nearest) at a third of the cost.
    """
    ra, dec = _grid_world(grid)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        x, y = frame.wcs.world_to_pixel_values(ra, dec)
    ny, nx = frame.image.shape
    # Same footprint rule as reproject: inside the input pixel grid (half-pixel border).
    inside = (x >= -0.5) & (x <= nx - 0.5) & (y >= -0.5) & (y <= ny - 0.5)
    # Clamp so the half-pixel border samples the edge pixel rather than the fill value.
    coords = np.array([np.clip(y, 0, ny - 1), np.clip(x, 0, nx - 1)])

    sci = (frame.image - frame.zodi).astype(np.float64)
    sci_r = map_coordinates(sci, coords, order=1, mode="nearest")
    var_r = map_coordinates(frame.variance.astype(np.float64), coords, order=1, mode="nearest")
    flg_r = map_coordinates(frame.flags, coords, order=0, mode="nearest")

    off = ~inside | ~np.isfinite(sci_r)
    sci_r[off] = np.nan
    var_r[off] = np.nan
    flags = np.where(off, 0, flg_r).astype(np.int64)
    return sci_r.astype(np.float32), var_r.astype(np.float32), flags


# ---------------------------------------------------------------------------------------
# Stage 2: selection, grouping and inverse-variance stacking
# ---------------------------------------------------------------------------------------
@dataclass
class GridFrame:
    """One exposure on the common grid, plus the metadata needed for grouping."""
    key: str
    obs_id: str
    detector: int
    mjd: float
    lam_um: float          # central wavelength at the target pixel
    bw_um: float
    sci: np.ndarray        # IMAGE - ZODI, MJy/sr
    var: np.ndarray        # (MJy/sr)^2
    flags: np.ndarray      # int bitmask
    target_flags: int = 0  # FLAGS value at the target pixel (native frame)
    meta: dict = field(default_factory=dict)


@dataclass
class Product:
    """A displayable image: a single frame or a co-add of several."""
    label: str
    members: list[GridFrame]
    sci: np.ndarray
    var: np.ndarray
    flags: np.ndarray       # bitwise OR over contributing members
    n_used: np.ndarray      # number of frames contributing to each pixel

    @property
    def mjd(self) -> float:
        return float(np.mean([m.mjd for m in self.members]))

    @property
    def mjd_range(self) -> tuple[float, float]:
        t = [m.mjd for m in self.members]
        return min(t), max(t)

    @property
    def detectors(self) -> list[int]:
        return sorted({m.detector for m in self.members})

    @property
    def lam_range(self) -> tuple[float, float]:
        lam = [m.lam_um for m in self.members]
        return min(lam), max(lam)

    @property
    def target_flags(self) -> int:
        v = 0
        for m in self.members:
            v |= m.target_flags
        return v


@dataclass(frozen=True)
class Selection:
    mjd_min: float | None = None
    mjd_max: float | None = None
    detectors: tuple[int, ...] | None = None
    lam_min: float | None = None
    lam_max: float | None = None

    def accepts(self, f: GridFrame) -> bool:
        return ((self.mjd_min is None or f.mjd >= self.mjd_min)
                and (self.mjd_max is None or f.mjd <= self.mjd_max)
                and (not self.detectors or f.detector in self.detectors)
                and (self.lam_min is None or f.lam_um >= self.lam_min)
                and (self.lam_max is None or f.lam_um <= self.lam_max))


def ivw_weights(var: np.ndarray, flags: np.ndarray, bad_mask: int) -> np.ndarray:
    """Inverse-variance weights; zero for NaN/non-positive variance or bad flags."""
    with np.errstate(divide="ignore", invalid="ignore"):
        w = np.where(np.isfinite(var) & (var > 0), 1.0 / var, 0.0)
    if bad_mask:
        w = np.where((flags & bad_mask) != 0, 0.0, w)
    return w


def ivw_stack(frames: list[GridFrame], bad_mask: int) -> tuple[np.ndarray, ...]:
    """Inverse-variance weighted mean: S = sum(w x) / sum(w), Var(S) = 1 / sum(w)."""
    shape = frames[0].sci.shape
    num = np.zeros(shape)
    den = np.zeros(shape)
    n = np.zeros(shape, dtype=np.int32)
    flags = np.zeros(shape, dtype=np.int64)
    for f in frames:
        w = ivw_weights(f.var, f.flags, bad_mask)
        good = (w > 0) & np.isfinite(f.sci)
        num += np.where(good, w * np.nan_to_num(f.sci), 0.0)
        den += np.where(good, w, 0.0)
        n += good
        flags |= np.where(np.isfinite(f.sci), f.flags, 0)
    with np.errstate(divide="ignore", invalid="ignore"):
        sci = np.where(den > 0, num / den, np.nan)
        var = np.where(den > 0, 1.0 / den, np.nan)
    return sci.astype(np.float32), var.astype(np.float32), flags, n


def single(f: GridFrame, label: str) -> Product:
    finite = np.isfinite(f.sci)
    return Product(label=label, members=[f], sci=f.sci, var=f.var, flags=f.flags,
                   n_used=finite.astype(np.int32))


def stack_product(frames: list[GridFrame], bad_mask: int, label: str) -> Product:
    sci, var, flags, n = ivw_stack(frames, bad_mask)
    return Product(label=label, members=list(frames), sci=sci, var=var, flags=flags, n_used=n)


def group_epochs(frames: list[GridFrame], window_days: float) -> list[list[GridFrame]]:
    """Sequential grouping in time: a new epoch starts when a frame is more than
    ``window_days`` after the first frame of the current epoch."""
    groups: list[list[GridFrame]] = []
    for f in sorted(frames, key=lambda f: f.mjd):
        if groups and f.mjd - groups[-1][0].mjd <= window_days:
            groups[-1].append(f)
        else:
            groups.append([f])
    return groups


def epoch_index(frames: list[GridFrame], window_days: float) -> dict[str, int]:
    return {f.key: i for i, g in enumerate(group_epochs(frames, window_days)) for f in g}


def _stacks(frames: list[GridFrame], mode: str, sel: Selection, bad_mask: int,
            window_days: float, rgb_dets: tuple[int, ...]) -> list[Product]:
    chosen = sorted((f for f in frames if sel.accepts(f)), key=lambda f: (f.mjd, f.detector))
    if not chosen:
        return []
    if mode == "frames":
        return [single(f, f"D{f.detector} {f.obs_id}") for f in chosen]
    if mode == "detector":
        out = []
        for d in range(1, 7):
            fs = [f for f in chosen if f.detector == d]
            if fs:
                lam = [f.lam_um for f in fs]
                out.append(stack_product(fs, bad_mask,
                                         f"D{d} stack ({len(fs)}) {min(lam):.2f}-{max(lam):.2f} µm"))
        return out
    if mode == "epoch":
        out = []
        for i, g in enumerate(group_epochs(chosen, window_days)):
            p = stack_product(g, bad_mask, "")
            p.label = f"Epoch {i + 1} ({len(g)}) {mjd_to_epoch(p.mjd):.2f}"
            out.append(p)
        return out
    if mode == "wave":
        lam = [f.lam_um for f in chosen]
        return [stack_product(chosen, bad_mask,
                              f"λ stack ({len(chosen)}) {min(lam):.2f}-{max(lam):.2f} µm")]
    if mode == "rgb":
        out = []
        for d in rgb_dets:
            fs = [f for f in chosen if f.detector == d]
            if fs:
                out.append(stack_product(fs, bad_mask, f"D{d} stack ({len(fs)})"))
        return out
    raise ValueError(f"unknown mode {mode!r}")


# ---------------------------------------------------------------------------------------
# Stage 3: reference subtraction (motion shows as dipoles, variability as residuals)
# ---------------------------------------------------------------------------------------
def median_reference(products: list[Product]) -> tuple[np.ndarray, np.ndarray]:
    """Pixelwise median over products, with variance approximated as
    (pi/2) * mean(var) / N (the variance of a median of N Gaussian samples)."""
    cube = np.stack([p.sci for p in products])
    vcube = np.stack([p.var for p in products])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        med = np.nanmedian(cube, axis=0)
        n = np.sum(np.isfinite(cube), axis=0)
        var = (np.pi / 2) * np.nanmean(vcube, axis=0) / np.maximum(n, 1)
    return med.astype(np.float32), var.astype(np.float32)


def subtract(products: list[Product], diff: str, ref_index: int = 0) -> list[Product]:
    """Stage 3. diff='none' | 'median' (each minus median of all) | 'ref' (each minus product
    ``ref_index``). Each difference image then has its own median removed (see below)."""
    if diff in ("none", "", None) or not products:
        return products
    if diff == "median":
        ref, ref_var = median_reference(products)
    elif diff == "ref":
        if not 0 <= ref_index < len(products):
            raise ValueError(f"reference index {ref_index} out of range 0..{len(products) - 1}")
        ref, ref_var = products[ref_index].sci, products[ref_index].var
    else:
        raise ValueError(f"unknown diff mode {diff!r}")
    out = []
    for p in products:
        d = (p.sci - ref).astype(np.float64)
        # The sky level left after zodiacal subtraction differs from visit to visit, which
        # would put a uniform pedestal on the difference. Its median is removed, so an
        # unchanged sky is zero and only sources that changed or moved stand out.
        if np.isfinite(d).any():
            d -= np.nanmedian(d)
        out.append(replace(p, sci=d.astype(np.float32), var=(p.var + ref_var).astype(np.float32)))
    return out


# ---------------------------------------------------------------------------------------
# The pipeline
# ---------------------------------------------------------------------------------------
def build_products(frames: list[GridFrame], mode: str, sel: Selection, bad_mask: int,
                   window_days: float = 14.0, rgb_dets: tuple[int, ...] = (6, 4, 2),
                   diff: str = "none", ref_index: int = 0,
                   cache: MutableMapping | None = None) -> list[Product]:
    """Products for a display mode (frames are first filtered by ``sel``).

    frames   - every exposure, time-ordered
    detector - one inverse-variance stack per detector (D1..D6)
    epoch    - one stack per time window (all selected detectors combined)
    wave     - a single stack of everything in the selection (use lam_min/lam_max)
    rgb      - three detector stacks (R, G, B), rendered as a colour composite

    ``diff`` then subtracts the median of the products ("median") or product ``ref_index``
    ("ref"). With a ``cache`` (any mapping; the caller empties it when frames change) the
    stacks are computed once and reused by every difference mode and reference index.
    """
    key = (mode, sel, bad_mask, window_days, tuple(rgb_dets), len(frames))
    stacks = cache.get(key) if cache is not None else None
    if stacks is None:
        stacks = _stacks(frames, mode, sel, bad_mask, window_days, tuple(rgb_dets))
        if cache is not None:
            cache[key] = stacks
    return subtract(stacks, diff, ref_index)
