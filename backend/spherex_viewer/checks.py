"""End-to-end acceptance checks against live IRSA data (used by tests/test_acceptance.py
and ``python -m spherex_viewer.checks``)."""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time

import numpy as np

from .data_access.fitsmeta import DEFAULT_BAD_FLAGS, mask_for_names
from .data_access.resolver import mjd_to_epoch, resolve
from .api.sessions import Session, SessionParams
from .processing.pipeline import Selection, build_products

# Detectors where each target is best seen (for the motion check); default: all.
MOTION_DETS = {"wise0855": (5, 6)}

TARGETS = {
    "wise0855": {"q": "WISEA J085510.74-071442.5", "fov": 5.0},
    "barnard": {"q": "Barnard's Star", "fov": 5.0},
    "epsindib": {"q": "eps Indi B", "fov": 5.0},
    "rwaur": {"q": "RW Aur", "fov": 5.0},
    "rdra": {"q": "R Dra", "fov": 5.0},
    # eps Indi A is ~6.7' from B, so it needs a wider field to compare the two.
    "epsindi_wide": {"q": "eps Indi B", "fov": 15.0},
}


def centroid(img: np.ndarray, x0: float, y0: float, half: int = 2) -> tuple[float, float, float]:
    """Background-subtracted first-moment centroid in a (2*half+1)^2 box. Returns
    (x, y, peak S/N proxy)."""
    xi, yi = int(round(x0)), int(round(y0))
    box = img[yi - half: yi + half + 1, xi - half: xi + half + 1]
    if box.shape != (2 * half + 1, 2 * half + 1) or not np.all(np.isfinite(box)):
        return np.nan, np.nan, 0.0
    ring = img[yi - half - 3: yi + half + 4, xi - half - 3: xi + half + 4]
    bkg = np.nanmedian(ring)
    b = np.clip(box - bkg, 0, None)
    if b.sum() <= 0:
        return np.nan, np.nan, 0.0
    yy, xx = np.mgrid[-half: half + 1, -half: half + 1]
    return xi + (b * xx).sum() / b.sum(), yi + (b * yy).sum() / b.sum(), float(b.max())


def find_reference_stars(stack: np.ndarray, exclude_xy: tuple[float, float], n: int = 5,
                         min_sep: float = 6.0) -> list[tuple[int, int]]:
    """Brightest isolated local maxima, away from the edges and the science target.
    Candidates must be the maximum of their 7x7 neighbourhood with a centroid within
    0.75 px of the peak pixel; this rejects points on the wings of a bright (saturated)
    target's halo, whose 'centroids' only measure the halo gradient."""
    img = np.nan_to_num(stack, nan=-np.inf)
    ny, nx = img.shape
    order = np.argsort(img.ravel())[::-1]
    out: list[tuple[int, int]] = []
    for idx in order[:5000]:
        y, x = divmod(int(idx), nx)
        if not (6 <= x < nx - 6 and 6 <= y < ny - 6):
            continue
        if np.hypot(x - exclude_xy[0], y - exclude_xy[1]) < 8:
            continue
        if any(np.hypot(x - a, y - b) < min_sep for a, b in out):
            continue
        if img[y, x] < np.max(img[y - 3:y + 4, x - 3:x + 4]):
            continue
        cx, cy, _ = centroid(stack, x, y)
        if not np.isfinite(cx) or np.hypot(cx - x, cy - y) > 0.75:
            continue
        out.append((x, y))
        if len(out) >= n:
            break
    return out


def alignment_stats(session: Session) -> dict:
    """Centroid of bright stationary stars in each single frame, relative to their
    position in the per-detector stack. Reports the RMS and 95th-percentile offsets."""
    frames = list(session.frames.values())
    bad = mask_for_names(session.flag_bits, DEFAULT_BAD_FLAGS)
    c = session.grid.center_pix
    offsets = []
    for det_stack in build_products(frames, "detector", Selection(), bad):
        d = det_stack.detectors[0]
        stars = find_reference_stars(det_stack.sci, (c, c))
        for sx, sy in stars:
            rx, ry, _ = centroid(det_stack.sci, sx, sy)
            if not np.isfinite(rx):
                continue
            for f in (f for f in frames if f.detector == d):
                fx, fy, peak = centroid(f.sci, rx, ry)
                noise = np.nanmedian(np.sqrt(f.var))
                if np.isfinite(fx) and peak > 20 * noise:  # only well-measured stars
                    offsets.append(np.hypot(fx - rx, fy - ry))
    offsets = np.array(offsets)
    if offsets.size == 0:
        return {"n": 0}
    return {"n": int(offsets.size), "rms_px": float(np.sqrt(np.mean(offsets ** 2))),
            "median_px": float(np.median(offsets)), "p95_px": float(np.percentile(offsets, 95)),
            "max_px": float(offsets.max())}


def motion_stats(session: Session, dets: tuple[int, ...] = (), window_days: float = 60.0,
                 half: int = 3) -> dict:
    """Measured vs predicted target motion between epoch stacks. The target's centroid is
    measured in each epoch stack (blank saturated cores are filled with the box maximum so
    the centroid still finds the star); displacements are relative to the first epoch."""
    frames = list(session.frames.values())
    bad = mask_for_names(session.flag_bits, DEFAULT_BAD_FLAGS)
    prods = build_products(frames, "epoch", Selection(detectors=dets or None), bad, window_days)
    rows = []
    for p in prods:
        ra, dec = session.position_at(p.mjd)
        px, py = session.grid.sky_to_pix(ra, dec)
        xi, yi = int(round(float(px))), int(round(float(py)))
        box = p.sci[yi - half: yi + half + 1, xi - half: xi + half + 1].astype(float)
        if box.shape != (2 * half + 1,) * 2 or np.all(~np.isfinite(box)):
            continue
        box = np.where(np.isfinite(box), box, np.nanmax(box))
        b = np.clip(box - np.nanmedian(box), 0, None) ** 2  # squared: favours the core
        yy, xx = np.mgrid[-half: half + 1, -half: half + 1]
        mx, my = xi + (b * xx).sum() / b.sum(), yi + (b * yy).sum() / b.sum()
        rows.append({"epoch": round(mjd_to_epoch(p.mjd), 3), "n": len(p.members),
                     "pred_xy": [float(px), float(py)], "meas_xy": [float(mx), float(my)]})
    if len(rows) < 2:
        return {"n_epochs": len(rows)}
    p0, m0 = np.array(rows[0]["pred_xy"]), np.array(rows[0]["meas_xy"])
    for r in rows:
        r["pred_shift_px"] = float(np.hypot(*(np.array(r["pred_xy"]) - p0)))
        r["meas_shift_px"] = float(np.hypot(*(np.array(r["meas_xy"]) - m0)))
        r["resid_px"] = float(np.hypot(*((np.array(r["meas_xy"]) - m0) - (np.array(r["pred_xy"]) - p0))))
    return {"n_epochs": len(rows), "epochs": rows,
            "total_pred_shift_px": rows[-1]["pred_shift_px"],
            "total_meas_shift_px": rows[-1]["meas_shift_px"],
            "max_resid_px": max(r["resid_px"] for r in rows)}


def spectrum_stats(session: Session) -> dict:
    rows = [r for r in session.records.values() if r.get("phot")]
    measured = [r for r in rows if r["phot"]["flux_ujy"] is not None]
    saturated = [r for r in rows if r["phot"].get("saturated")]
    good = [r for r in measured if r["phot"]["ok"]]
    per_det = {}
    for d in range(1, 7):
        fl = [r["phot"]["flux_ujy"] for r in good if r["detector"] == d]
        er = [r["phot"]["err_ujy"] for r in good if r["detector"] == d]
        if fl:
            per_det[f"D{d}"] = {"n": len(fl), "median_flux_ujy": float(np.median(fl)),
                                "median_snr": float(np.median(np.array(fl) / np.array(er)))}
    lam = [r["phot"]["lam_um"] for r in measured]
    return {"n_points": len(rows), "n_measured": len(measured), "n_good": len(good),
            "n_saturated": len(saturated),
            "lam_range_um": [float(min(lam)), float(max(lam))] if lam else None,
            "per_detector": per_det}


async def check_target(name: str, q: str, fov: float, pm: bool = True) -> dict:
    t0 = time.time()
    # The registry's TAP aggregate can take minutes; checks use the bootstrap list.
    tgt = await resolve(q)
    params = SessionParams(ra=tgt.ra, dec=tgt.dec, fov=fov, pmra=tgt.pmra, pmdec=tgt.pmdec,
                           epoch=tgt.epoch, pm=pm, name=tgt.name)
    s = Session(params)
    last = [0.0]

    def log_progress(_s=s):
        p = _s.progress()
        if time.time() - last[0] > 15:
            last[0] = time.time()
            print(f"  [{name}] {p['state']} {p['done']}/{p['total']} loaded={p['loaded']} "
                  f"failed={p['failed']}", file=sys.stderr, flush=True)

    q_ = asyncio.Queue()
    s.subscribers.append(q_)
    task = asyncio.create_task(s.run())
    while not task.done():
        try:
            await asyncio.wait_for(q_.get(), 5)
        except asyncio.TimeoutError:
            pass
        log_progress()
    await task
    res = {
        "target": name, "query": q, "resolved": tgt.to_json(), "fov_arcmin": fov,
        "center": s.center, "state": s.state, "message": s.message, "errors": s.errors[:5],
        "n_observations": len(s.observations), "n_loaded": len(s.frames),
        "n_failed": s.progress()["failed"],
        "elapsed_s": round(time.time() - t0, 1),
    }
    if s.frames:
        res["alignment"] = alignment_stats(s)
        res["spectrum"] = spectrum_stats(s)
        res["motion"] = motion_stats(s, dets=MOTION_DETS.get(name, ()))
        res["detectors"] = sorted({f.detector for f in s.frames.values()})
        mjd = [f.mjd for f in s.frames.values()]
        res["mjd_range"] = [min(mjd), max(mjd)]
    res["pass"] = bool(res["n_loaded"] > 0
                       and res.get("alignment", {}).get("rms_px", 99) < 1.0
                       and res.get("spectrum", {}).get("n_measured", 0) > 0)
    return res, s


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("targets", nargs="*", default=list(TARGETS))
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING)
    results = {}
    for t in args.targets:
        cfg = TARGETS[t]
        r, _ = asyncio.run(check_target(t, cfg["q"], cfg["fov"]))
        results[t] = r
        print(json.dumps(r, indent=1, default=float))
    if args.out:
        with open(args.out, "w") as f:
            json.dump(results, f, indent=1, default=float)


if __name__ == "__main__":
    main()
