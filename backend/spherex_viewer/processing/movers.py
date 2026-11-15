"""Mover classifier: which CatWISE2020 sources with a measured motion are really moving?

CatWISE2020 fits a proper motion to every source, and most significant-looking motions of
faint sources are artifacts (blends, diffraction spikes, noise). The classifier is a
gradient-boosted tree ensemble trained on CatWISE measurements, with Gaia DR3 proper
motions as the truth and confirmed SIMBAD brown dwarfs as extra movers
(``python -m spherex_viewer.train_movers``). It returns the probability that a source's
true motion is at least ``MOVER_MIN_MAS`` mas/yr.

The model file is plain JSON and is evaluated here with numpy alone, so the server does not
need scikit-learn. Feature extraction lives here too, so training and serving cannot drift.

Known limits, also stated in the interface:
  * outside Gaia (G > 21) there are confirmed movers to learn from but no confirmed
    non-movers, so precision is unmeasured for the reddest, coldest objects;
  * the training fields are at Galactic latitude |b| >= 15 deg;
  * colour (W1 - W2) is deliberately not a feature, so "red" is never learned as a proxy.
"""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

import numpy as np

MODEL_PATH = Path(__file__).resolve().parents[1] / "data" / "mover_model.json"
MOVER_MIN_MAS = 50.0            # "moving": true total proper motion >= this, mas/yr
MIN_PM_SNR = 3.0                # candidates: CatWISE motion significance >= this
STRONG_PM_SNR = 10.0            # sources without a Gaia star are always listed above this
MATCH_ARCSEC = 1.5              # Gaia counterpart radius (at the CatWISE epoch)
GAIA_EPOCH = 2016.0
MISSING = -999.0

# CatWISE2020 columns the features are computed from (IRSA Gator names, lower case).
CATWISE_COLS = [
    "source_name", "ra_pm", "dec_pm", "pmra", "pmdec", "sigpmra", "sigpmdec",
    "w1mpro_pm", "w2mpro_pm", "w1snr_pm", "w2snr_pm", "rchi2_pm", "w1rchi2_pm", "w2rchi2_pm",
    "rchi2", "nb", "na", "delonsnr", "delatsnr", "chi2pmra", "chi2pmdec", "par_pm",
    "par_pmsig", "par_stat", "par_sigma", "q12", "rho12", "w1k", "w2k", "n_aw", "cc_flags",
    "ab_flags", "glat", "w1sat", "w2sat", "w1m", "w1nm", "w2m", "w2nm", "niters_pm",
]
# Evaluated by IRSA, so only candidates are downloaded.
CANDIDATE_SQL = (f"sigpmra>0 and sigpmdec>0 and (pmra*pmra/(sigpmra*sigpmra)"
                 f"+pmdec*pmdec/(sigpmdec*sigpmdec))>{MIN_PM_SNR ** 2:g}")

FEATURES = [
    "log_pm", "pm_snr", "log_sigpm", "w1mpro", "w1snr", "w2snr", "rchi2_pm", "w1rchi2_pm",
    "w2rchi2_pm", "rchi2_ratio", "nb", "na", "abs_delonsnr", "abs_delatsnr", "chi2pmra",
    "chi2pmdec", "par_pm_snr", "par_stat_snr", "q12", "rho12", "w1k", "w2k", "n_aw",
    "cc_flagged", "ab_flagged", "abs_glat", "w1sat", "w2sat", "w1_detfrac", "w2_detfrac",
    "niters_pm",
]


def _num(row: dict, key: str) -> float:
    try:
        x = float(row.get(key))
    except (TypeError, ValueError):
        return math.nan
    return x if math.isfinite(x) else math.nan


def _flagged(v) -> float:
    """1 if a CatWISE flag string marks any artifact ('0000' and '00' are clean)."""
    if v is None:
        return math.nan
    return float(any(ch not in "0 " for ch in str(v)))


def _ratio(a: float, b: float) -> float:
    return a / b if b and math.isfinite(a) and math.isfinite(b) else math.nan


def pm_mas(row: dict) -> tuple[float, float, float, float]:
    """(pmra, pmdec, sigpmra, sigpmdec) in mas/yr (CatWISE lists arcsec/yr)."""
    return tuple(_num(row, k) * 1000.0 for k in ("pmra", "pmdec", "sigpmra", "sigpmdec"))


def pm_snr(row: dict) -> float:
    pmra, pmdec, sra, sdec = pm_mas(row)
    if not (sra > 0 and sdec > 0):
        return math.nan
    return math.hypot(pmra / sra, pmdec / sdec)


def features(row: dict) -> list[float]:
    """The feature vector of one CatWISE row, in FEATURES order (missing -> MISSING)."""
    pmra, pmdec, sra, sdec = pm_mas(row)
    pm, sig = math.hypot(pmra, pmdec), math.hypot(sra, sdec)
    f = {
        "log_pm": math.log10(pm) if pm > 0 else math.nan,
        "pm_snr": pm_snr(row),
        "log_sigpm": math.log10(sig) if sig > 0 else math.nan,
        "w1mpro": _num(row, "w1mpro_pm"), "w1snr": _num(row, "w1snr_pm"),
        "w2snr": _num(row, "w2snr_pm"), "rchi2_pm": _num(row, "rchi2_pm"),
        "w1rchi2_pm": _num(row, "w1rchi2_pm"), "w2rchi2_pm": _num(row, "w2rchi2_pm"),
        "rchi2_ratio": _ratio(_num(row, "rchi2"), _num(row, "rchi2_pm")),
        "nb": _num(row, "nb"), "na": _num(row, "na"),
        "abs_delonsnr": abs(_num(row, "delonsnr")), "abs_delatsnr": abs(_num(row, "delatsnr")),
        "chi2pmra": _num(row, "chi2pmra"), "chi2pmdec": _num(row, "chi2pmdec"),
        "par_pm_snr": _ratio(_num(row, "par_pm"), _num(row, "par_pmsig")),
        "par_stat_snr": _ratio(_num(row, "par_stat"), _num(row, "par_sigma")),
        "q12": _num(row, "q12"), "rho12": _num(row, "rho12"),
        "w1k": _num(row, "w1k"), "w2k": _num(row, "w2k"), "n_aw": _num(row, "n_aw"),
        "cc_flagged": _flagged(row.get("cc_flags")), "ab_flagged": _flagged(row.get("ab_flags")),
        "abs_glat": abs(_num(row, "glat")),
        "w1sat": _num(row, "w1sat"), "w2sat": _num(row, "w2sat"),
        "w1_detfrac": _ratio(_num(row, "w1m"), _num(row, "w1nm")),
        "w2_detfrac": _ratio(_num(row, "w2m"), _num(row, "w2nm")),
        "niters_pm": _num(row, "niters_pm"),
    }
    return [f[k] if math.isfinite(f[k]) else MISSING for k in FEATURES]


def feature_matrix(rows: list[dict]) -> np.ndarray:
    return np.array([features(r) for r in rows], dtype=np.float32).reshape(len(rows), len(FEATURES))


# ---- the model: exported gradient-boosted trees, evaluated with numpy ---------------------
class Model:
    def __init__(self, d: dict):
        if d["features"] != FEATURES:
            raise ValueError("mover model was trained on a different feature list; retrain it")
        self.meta = {k: v for k, v in d.items() if k not in ("trees", "check")}
        self.init, self.rate = float(d["init"]), float(d.get("learning_rate", 1.0))
        self.trees = [tuple(np.asarray(t[k], dtype=dt) for k, dt in
                            (("feature", np.int64), ("threshold", np.float64), ("left", np.int64),
                             ("right", np.int64), ("value", np.float64))) for t in d["trees"]]
        self.check = d.get("check", [])

    def predict(self, x: np.ndarray) -> np.ndarray:
        """P(mover) for each row of a float32 feature matrix."""
        x = np.asarray(x, dtype=np.float32)
        raw = np.full(len(x), self.init)
        rows = np.arange(len(x))
        for feat, thr, left, right, value in self.trees:
            node = np.zeros(len(x), dtype=np.int64)
            while True:
                f = feat[node]
                inner = f >= 0
                if not inner.any():
                    break
                go_left = x[rows, np.where(inner, f, 0)] <= thr[node]
                node = np.where(inner, np.where(go_left, left[node], right[node]), node)
            raw += self.rate * value[node]
        return 1.0 / (1.0 + np.exp(-raw))


@lru_cache(maxsize=1)
def load_model() -> Model | None:
    """The trained model, or None if it has not been built."""
    if not MODEL_PATH.exists():
        return None
    return Model(json.loads(MODEL_PATH.read_text()))


# ---- Gaia counterparts (truth for training; "already known" in the interface) -------------
def gaia_match(cw: list[dict], gaia: list[dict], epoch: float) -> list[dict | None]:
    """For each CatWISE row, the nearest Gaia star within MATCH_ARCSEC once Gaia positions
    are moved to ``epoch`` (the CatWISE position epoch). Gaia rows: ra, dec, pmra, pmdec
    (mas/yr, may be None), mag."""
    if not cw:
        return []
    if not gaia:
        return [None] * len(cw)
    g_ra = np.array([g["ra"] for g in gaia])
    g_dec = np.array([g["dec"] for g in gaia])
    g_pmra = np.array([g["pmra"] if g["pmra"] is not None else 0.0 for g in gaia])
    g_pmdec = np.array([g["pmdec"] if g["pmdec"] is not None else 0.0 for g in gaia])
    dt = epoch - GAIA_EPOCH
    g_dec_e = g_dec + g_pmdec * dt / 3.6e6
    g_ra_e = g_ra + g_pmra * dt / 3.6e6 / np.cos(np.radians(g_dec))
    from scipy.spatial import cKDTree
    c_ra = np.array([_num(r, "ra_pm") for r in cw])
    c_dec = np.array([_num(r, "dec_pm") for r in cw])
    ok = np.isfinite(c_ra) & np.isfinite(c_dec)
    # Nearest neighbour on the unit sphere; a chord equals the angle at these separations.
    dist, idx = cKDTree(_unit(g_ra_e, g_dec_e)).query(_unit(np.where(ok, c_ra, 0.0), np.where(ok, c_dec, 0.0)))
    sep = np.degrees(dist) * 3600
    return [{**gaia[i], "sep_arcsec": float(s)} if good and s <= MATCH_ARCSEC else None
            for i, s, good in zip(idx, sep, ok)]


def _unit(ra, dec) -> np.ndarray:
    a, d = np.radians(ra), np.radians(dec)
    return np.stack([np.cos(d) * np.cos(a), np.cos(d) * np.sin(a), np.sin(d)], axis=1)


def rank(cw: list[dict], gaia: list[dict], epoch: float, limit: int = 200) -> list[dict]:
    """Score CatWISE candidate rows and return them most-likely-moving first: the top
    ``limit``, plus every source with no Gaia counterpart and a strong CatWISE motion. The
    model's precision is unmeasured for those, so a low score must never hide one."""
    model = load_model()
    if model is None:
        raise RuntimeError("the mover model has not been trained "
                           "(python -m spherex_viewer.train_movers)")
    rows = [r for r in cw if (pm_snr(r) or 0) >= MIN_PM_SNR
            and math.isfinite(_num(r, "ra_pm")) and math.isfinite(_num(r, "dec_pm"))]
    if not rows:
        return []
    prob = model.predict(feature_matrix(rows))
    matches = gaia_match(rows, gaia, epoch)
    out = []
    for r, p, g in zip(rows, prob, matches):
        pmra, pmdec, sra, sdec = pm_mas(r)
        w1, w2 = _num(r, "w1mpro_pm"), _num(r, "w2mpro_pm")
        fin = lambda v: v if math.isfinite(v) else None   # noqa: E731
        gaia_pm = (math.hypot(g["pmra"], g["pmdec"]) if g and g["pmra"] is not None
                   and g["pmdec"] is not None else None)
        out.append({
            "id": r.get("source_name"), "ra": _num(r, "ra_pm"), "dec": _num(r, "dec_pm"),
            "epoch": epoch, "prob": float(p),
            "pmra": pmra, "pmdec": pmdec, "pm": math.hypot(pmra, pmdec),
            "pm_err": math.hypot(sra, sdec), "pm_snr": pm_snr(r),
            "w1": fin(w1), "w2": fin(w2),
            "flagged": bool(_flagged(r.get("cc_flags")) == 1 or _flagged(r.get("ab_flags")) == 1),
            "gaia": None if g is None else {
                "id": g.get("id"), "pmra": g["pmra"], "pmdec": g["pmdec"], "pm": gaia_pm,
                "mag": g.get("mag"), "sep_arcsec": g["sep_arcsec"]},
        })
    out.sort(key=lambda c: -c["prob"])
    return out[:limit] + [c for c in out[limit:] if c["gaia"] is None and c["pm_snr"] >= STRONG_PM_SNR]
