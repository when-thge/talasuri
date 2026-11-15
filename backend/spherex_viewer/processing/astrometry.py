"""Astrometric fit to WISE/NEOWISE single-exposure positions, and position prediction
with its uncertainty.

The model is the standard five-parameter one, linear in its parameters, written in the
tangent plane at a fixed point (xi east, eta north, arcsec):

    xi(t)  = xi0  + mu_xi  * (t - t_ref) + parallax * P_xi(t)
    eta(t) = eta0 + mu_eta * (t - t_ref) + parallax * P_eta(t)

P are the parallax factors of an observer at the Earth (WISE and SPHEREx are both in low
Earth orbit). It is solved by weighted least squares, so the parameter covariance is exact
for the adopted errors, and the covariance of a predicted position follows by linear
propagation. That is what the uncertainty ellipse shows.

Steps: (1) pick the detections that belong to the target (within a match radius of the
current track), (2) average them per visit, with an error floor for the frame-to-frame
systematics of single exposures, (3) fit, (4) repeat from (1) with the new track until the
selection is stable. Parallax is kept only if it is detected (>= 3 sigma, positive);
otherwise the four-parameter solution is reported.

No network access here: catalogs.wise_exposures() supplies the detections.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from ..data_access.resolver import DAYS_PER_YEAR, mjd_to_epoch

MATCH_RADIUS = 3.0          # arcsec; half the WISE beam (6 arcsec FWHM)
VISIT_DAYS = 10.0           # detections within this many days form one visit
SYS_FLOOR = 0.04            # arcsec per axis per visit: single-exposure frame systematics
MIN_SIGMA = 0.03            # arcsec: lower bound on a catalogued single-exposure error
MIN_VISITS, MIN_SPAN_YR = 3, 1.0
MIN_VISITS_PARALLAX, PARALLAX_SNR = 6, 3.0
OUTLIER_SIGMA = 4.0
K95 = math.sqrt(-2.0 * math.log(0.05))   # 1-sigma ellipse axes x K95 = 95 % region (2-D normal)


class FitError(ValueError):
    """The WISE data cannot support a fit (too few detections, too short a baseline)."""


# ---- geometry ------------------------------------------------------------------------------
def to_tangent(ra, dec, ra0: float, dec0: float):
    """Gnomonic projection about (ra0, dec0): (xi east, eta north) in arcsec."""
    a, d = np.radians(np.asarray(ra, float) - ra0), np.radians(np.asarray(dec, float))
    d0 = math.radians(dec0)
    cosc = math.sin(d0) * np.sin(d) + math.cos(d0) * np.cos(d) * np.cos(a)
    xi = np.cos(d) * np.sin(a) / cosc
    eta = (math.cos(d0) * np.sin(d) - math.sin(d0) * np.cos(d) * np.cos(a)) / cosc
    return np.degrees(xi) * 3600.0, np.degrees(eta) * 3600.0


def from_tangent(xi, eta, ra0: float, dec0: float):
    """Inverse of :func:`to_tangent`: (ra, dec) in degrees."""
    x, y = np.radians(np.asarray(xi, float) / 3600.0), np.radians(np.asarray(eta, float) / 3600.0)
    d0 = math.radians(dec0)
    den = math.cos(d0) - y * math.sin(d0)
    ra = ra0 + np.degrees(np.arctan2(x, den))
    dec = np.degrees(np.arctan2((math.sin(d0) + y * math.cos(d0)) * np.cos(np.arctan2(x, den)), den))
    return ra % 360.0, dec


def earth_position(mjd) -> np.ndarray:
    """Barycentric position of the Earth, ICRS axes, AU; shape (3, N). Uses astropy's
    built-in analytic ephemeris (no download), good to far better than needed here."""
    from astropy.coordinates import get_body_barycentric, solar_system_ephemeris
    from astropy.time import Time
    with solar_system_ephemeris.set("builtin"):
        p = get_body_barycentric("earth", Time(np.atleast_1d(np.asarray(mjd, float)), format="mjd", scale="tdb"))
    return p.xyz.to_value("au")


def parallax_factors(ra0: float, dec0: float, mjd) -> tuple[np.ndarray, np.ndarray]:
    """Displacement (xi, eta) per unit parallax, for an observer at the Earth."""
    x, y, z = earth_position(mjd)
    a, d = math.radians(ra0), math.radians(dec0)
    p_xi = x * math.sin(a) - y * math.cos(a)
    p_eta = x * math.cos(a) * math.sin(d) + y * math.sin(a) * math.sin(d) - z * math.cos(d)
    return p_xi, p_eta


# ---- data ----------------------------------------------------------------------------------
@dataclass
class Detections:
    """Single-exposure detections of everything near the track (not just the target)."""
    mjd: np.ndarray
    ra: np.ndarray
    dec: np.ndarray
    sig_ra: np.ndarray      # arcsec (already includes cos dec)
    sig_dec: np.ndarray

    def __len__(self) -> int:
        return len(self.mjd)


@dataclass
class Visit:
    mjd: float
    xi: float
    eta: float
    sig_xi: float
    sig_eta: float
    n: int
    used: bool = True


def bin_visits(mjd, xi, eta, sig_xi, sig_eta) -> list[Visit]:
    """One robust weighted-mean position per visit."""
    order = np.argsort(mjd)
    mjd, xi, eta, sig_xi, sig_eta = (np.asarray(v, float)[order] for v in (mjd, xi, eta, sig_xi, sig_eta))
    sig_xi, sig_eta = np.maximum(sig_xi, MIN_SIGMA), np.maximum(sig_eta, MIN_SIGMA)
    visits: list[Visit] = []
    start = 0
    for i in range(1, len(mjd) + 1):
        if i < len(mjd) and mjd[i] - mjd[start] <= VISIT_DAYS:
            continue
        s = slice(start, i)
        keep = np.ones(i - start, dtype=bool)
        if i - start >= 4:      # clip detections far from the visit's median
            for v in (xi[s], eta[s]):
                med = np.median(v)
                mad = 1.4826 * np.median(np.abs(v - med))
                keep &= np.abs(v - med) <= 3.5 * max(mad, 0.05)
        mean, err = [], []
        for v, sg in ((xi[s][keep], sig_xi[s][keep]), (eta[s][keep], sig_eta[s][keep])):
            w = 1.0 / sg ** 2
            m = float(np.sum(w * v) / np.sum(w))
            e = math.sqrt(1.0 / np.sum(w))
            if len(v) > 1:      # scatter larger than the catalogued errors: believe the scatter
                e *= max(1.0, math.sqrt(float(np.sum(w * (v - m) ** 2)) / (len(v) - 1)))
            mean.append(m)
            err.append(math.hypot(e, SYS_FLOOR))
        visits.append(Visit(float(np.mean(mjd[s][keep])), mean[0], mean[1], err[0], err[1], int(keep.sum())))
        start = i
    return visits


# ---- the fit -------------------------------------------------------------------------------
def _design(ra0: float, dec0: float, mjd, t_ref: float) -> np.ndarray:
    """Rows (xi_1..xi_N, eta_1..eta_N) x columns (xi0, eta0, mu_xi, mu_eta, parallax)."""
    mjd = np.atleast_1d(np.asarray(mjd, float))
    tau = (mjd - t_ref) / DAYS_PER_YEAR
    p_xi, p_eta = parallax_factors(ra0, dec0, mjd)
    one, zero = np.ones_like(tau), np.zeros_like(tau)
    return np.concatenate([np.stack([one, zero, tau, zero, p_xi], axis=1),
                           np.stack([zero, one, zero, tau, p_eta], axis=1)])


@dataclass
class Fit:
    ra0: float                    # tangent point, deg
    dec0: float
    t_ref: float                  # MJD the position parameters refer to
    params: np.ndarray            # xi0, eta0 (arcsec), mu_xi, mu_eta (arcsec/yr), parallax (arcsec)
    cov: np.ndarray               # 5x5, scaled by the reduced chi-square when that exceeds 1
    use_parallax: bool
    parallax_trial: tuple[float, float] | None   # (value, error) arcsec from the 5-parameter fit
    chi2_red: float
    visits: list[Visit]
    n_exposures: int
    iterations: int = 1
    n_visits_available: int = 0   # WISE visits of this field (any source), for comparison
    warnings: list[str] = field(default_factory=list)

    def offsets(self, mjd) -> tuple[np.ndarray, np.ndarray]:
        a = _design(self.ra0, self.dec0, mjd, self.t_ref) @ self.params
        n = len(a) // 2
        return a[:n], a[n:]

    def offsets_cov(self, mjd) -> np.ndarray:
        """Covariance (N, 2, 2) of the predicted (xi, eta), arcsec^2."""
        a = _design(self.ra0, self.dec0, mjd, self.t_ref)
        n = len(a) // 2
        j = np.stack([a[:n], a[n:]], axis=1)             # (N, 2, 5)
        return j @ self.cov @ np.transpose(j, (0, 2, 1))

    def linear(self, mjd) -> tuple[np.ndarray, np.ndarray]:
        """The straight-line part of the motion (no parallax)."""
        tau = (np.atleast_1d(np.asarray(mjd, float)) - self.t_ref) / DAYS_PER_YEAR
        return self.params[0] + self.params[2] * tau, self.params[1] + self.params[3] * tau

    def position(self) -> tuple[float, float]:
        """(ra, dec) at t_ref, parallax removed."""
        ra, dec = from_tangent(self.params[0], self.params[1], self.ra0, self.dec0)
        return float(ra), float(dec)

    def predict(self, mjd) -> list[dict]:
        mjd = np.atleast_1d(np.asarray(mjd, float))
        if not len(mjd):
            return []
        xi, eta = self.offsets(mjd)
        ra, dec = from_tangent(xi, eta, self.ra0, self.dec0)
        out = []
        for t, r, d, c in zip(mjd, ra, dec, self.offsets_cov(mjd)):
            a, b, pa = ellipse(c)
            out.append({"mjd": float(t), "ra": float(r), "dec": float(d),
                        "a_mas": a * 1000, "b_mas": b * 1000, "pa_deg": pa})
        return out


def ellipse(cov2: np.ndarray) -> tuple[float, float, float]:
    """1-sigma semi-axes (same unit as sqrt(cov)) and position angle of the major axis,
    degrees east of north in [0, 180)."""
    w, v = np.linalg.eigh(cov2)
    major = v[:, 1]
    pa = math.degrees(math.atan2(major[0], major[1])) % 180.0
    return math.sqrt(max(w[1], 0.0)), math.sqrt(max(w[0], 0.0)), pa


def _solve(visits: list[Visit], ra0: float, dec0: float, t_ref: float, with_parallax: bool):
    mjd = np.array([v.mjd for v in visits])
    y = np.array([v.xi for v in visits] + [v.eta for v in visits])
    sig = np.array([v.sig_xi for v in visits] + [v.sig_eta for v in visits])
    a = _design(ra0, dec0, mjd, t_ref)[:, :5 if with_parallax else 4]
    aw, yw = a / sig[:, None], y / sig
    p, *_ = np.linalg.lstsq(aw, yw, rcond=None)
    resid = yw - aw @ p
    dof = len(y) - a.shape[1]
    chi2_red = float(resid @ resid / dof) if dof > 0 else 1.0
    cov = np.linalg.inv(aw.T @ aw) * max(1.0, chi2_red)
    params, full = np.zeros(5), np.zeros((5, 5))
    k = a.shape[1]
    params[:k], full[:k, :k] = p, cov
    return params, full, chi2_red, resid.reshape(2, -1)


def fit_visits(visits: list[Visit], ra0: float, dec0: float) -> Fit:
    """Fit visit positions (tangent plane about ra0, dec0). Rejects outlying visits once."""
    def check(vs):
        if len(vs) < MIN_VISITS:
            raise FitError(f"only {len(vs)} WISE visit(s) of this object; a motion fit needs {MIN_VISITS}")
        span = (max(v.mjd for v in vs) - min(v.mjd for v in vs)) / DAYS_PER_YEAR
        if span < MIN_SPAN_YR:
            raise FitError(f"the WISE detections span only {span:.1f} yr; a motion fit needs {MIN_SPAN_YR:g}")
    check(visits)
    used = list(visits)
    for attempt in range(2):
        w = np.array([1 / (v.sig_xi ** 2 + v.sig_eta ** 2) for v in used])
        t_ref = float(np.sum(w * np.array([v.mjd for v in used])) / np.sum(w))
        params, cov, chi2_red, resid = _solve(used, ra0, dec0, t_ref, False)
        if attempt or len(used) < MIN_VISITS + 2:
            break
        # One pass of outlier rejection, in units of the errors scaled by the fit quality.
        scale = max(1.0, math.sqrt(chi2_red))
        # Robust scale: an outlier inflates chi2 itself, so compare with the median residual.
        rr = np.hypot(resid[0], resid[1])
        robust = max(1.0, float(np.median(rr)) / 1.1774)       # median of a 2-D normal radius
        bad = rr > OUTLIER_SIGMA * min(scale, robust) * math.sqrt(2)
        if not bad.any() or (~bad).sum() < MIN_VISITS:
            break
        keep = [v for v, b in zip(used, bad) if not b]
        try:
            check(keep)
        except FitError:
            break
        used = keep
    use_ids = {id(v) for v in used}
    for v in visits:
        v.used = id(v) in use_ids
    trial, use_plx = None, False
    if len(used) >= MIN_VISITS_PARALLAX:
        p5, c5, chi5, _ = _solve(used, ra0, dec0, t_ref, True)
        err = math.sqrt(c5[4, 4])
        trial = (float(p5[4]), err)
        if err > 0 and p5[4] / err >= PARALLAX_SNR:
            params, cov, chi2_red, use_plx = p5, c5, chi5, True
    return Fit(ra0, dec0, t_ref, params, cov, use_plx, trial, chi2_red, visits,
               sum(v.n for v in used))


def match_and_fit(det: Detections, ra: float, dec: float, pmra: float = 0.0, pmdec: float = 0.0,
                  epoch: float = 2000.0, radius: float = MATCH_RADIUS, max_iter: int = 8) -> Fit:
    """Select the target's detections along its track and fit them.

    (ra, dec) at Julian ``epoch`` with (pmra, pmdec) in mas/yr is the starting track; it
    only has to be good to ``radius`` arcsec at some of the WISE epochs, since the selection
    is repeated with each new solution."""
    if not len(det):
        raise FitError("no WISE single-exposure detections near this position")
    from ..data_access.resolver import Target
    seed = Target(ra, dec, pmra, pmdec, epoch)
    t_mid = float(np.median(det.mjd))
    ra0, dec0 = seed.position_at(t_mid)
    xi, eta = to_tangent(det.ra, det.dec, ra0, dec0)
    track = Fit(ra0, dec0, t_mid, np.array([0, 0, pmra / 1000, pmdec / 1000, 0.0]), np.zeros((5, 5)),
                False, None, 1.0, [], 0)
    frame = np.round(det.mjd, 5)        # detections of one exposure share its MJD
    selected: np.ndarray | None = None
    fit: Fit | None = None
    for it in range(1, max_iter + 1):
        px, py = track.offsets(det.mjd)
        d = np.hypot(xi - px, eta - py)
        cand = np.flatnonzero(d <= radius)
        best: dict[float, int] = {}
        for i in cand:                  # at most one detection per exposure: the nearest
            j = best.get(frame[i])
            if j is None or d[i] < d[j]:
                best[frame[i]] = int(i)
        sel = np.array(sorted(best.values()), dtype=int)
        if not len(sel):
            if fit is not None:
                break
            raise FitError(f"no WISE detection within {radius:g} arcsec of the expected position "
                           "(too faint for single WISE exposures, or the position is off)")
        if selected is not None and np.array_equal(sel, selected):
            break
        selected = sel
        visits = bin_visits(det.mjd[sel], xi[sel], eta[sel], det.sig_ra[sel], det.sig_dec[sel])
        try:
            fit = fit_visits(visits, ra0, dec0)
        except FitError:
            if fit is not None:        # a later, worse selection: keep the last good fit
                break
            raise
        fit.iterations = it
        track = fit
    assert fit is not None
    if fit.iterations == max_iter:
        fit.warnings.append("the selection of detections did not settle; treat the fit with caution")
    # How many visits WISE made here at all (every source in the cone has detections then).
    t = np.sort(det.mjd)
    fit.n_visits_available = 1 + int(np.sum(np.diff(t) > VISIT_DAYS))
    n_used = sum(v.used for v in fit.visits)
    if n_used < 0.5 * fit.n_visits_available:
        fit.warnings.append(
            f"detected in only {n_used} of {fit.n_visits_available} WISE visits: the object is faint, "
            "or it moves too fast to follow without a starting motion; the fit may be wrong")
    return fit


# ---- JSON for the API ------------------------------------------------------------------------
def summary(fit: Fit, curve_until_mjd: float) -> dict:
    """Everything the interface shows, in mas and Julian years."""
    used = [v for v in fit.visits if v.used]
    ra, dec = fit.position()
    err = np.sqrt(np.diag(fit.cov))
    lin = fit.linear([v.mjd for v in fit.visits])
    visits = [{"mjd": v.mjd, "epoch": mjd_to_epoch(v.mjd), "n": v.n, "used": v.used,
               "dxi_mas": (v.xi - lx) * 1000, "deta_mas": (v.eta - ly) * 1000,
               "sig_xi_mas": v.sig_xi * 1000, "sig_eta_mas": v.sig_eta * 1000}
              for v, lx, ly in zip(fit.visits, *lin)]
    resid = []
    if used:
        mx, my = fit.offsets([v.mjd for v in used])
        resid = [math.hypot(v.xi - a, v.eta - b) for v, a, b in zip(used, mx, my)]
    t0 = min(v.mjd for v in fit.visits) - 120
    grid = np.arange(t0, max(curve_until_mjd, t0 + 1) + 15, 15.0)
    mx, my = fit.offsets(grid)
    lx, ly = fit.linear(grid)
    sig = np.sqrt(np.clip(np.diagonal(fit.offsets_cov(grid), axis1=1, axis2=2), 0, None))
    r3 = lambda a: [round(float(v), 3) for v in a]      # noqa: E731
    return {
        "source": "WISE and NEOWISE single-exposure source tables (IRSA)",
        "n_exposures": fit.n_exposures, "n_visits": len(fit.visits), "n_visits_used": len(used),
        "n_visits_available": fit.n_visits_available,
        "first_mjd": min(v.mjd for v in fit.visits), "last_mjd": max(v.mjd for v in fit.visits),
        "span_yr": (max(v.mjd for v in fit.visits) - min(v.mjd for v in fit.visits)) / DAYS_PER_YEAR,
        "ref_mjd": fit.t_ref, "ref_epoch": mjd_to_epoch(fit.t_ref), "ra": ra, "dec": dec,
        "pos_err_mas": [float(err[0] * 1000), float(err[1] * 1000)],
        "pmra": float(fit.params[2] * 1000), "pmdec": float(fit.params[3] * 1000),
        "pmra_err": float(err[2] * 1000), "pmdec_err": float(err[3] * 1000),
        "pm": float(math.hypot(fit.params[2], fit.params[3]) * 1000),
        "parallax": {"used": fit.use_parallax,
                     "mas": None if fit.parallax_trial is None else fit.parallax_trial[0] * 1000,
                     "err_mas": None if fit.parallax_trial is None else fit.parallax_trial[1] * 1000},
        "chi2_red": fit.chi2_red, "rms_mas": float(np.sqrt(np.mean(np.square(resid))) * 1000) if resid else None,
        "sys_floor_mas": SYS_FLOOR * 1000, "match_radius_arcsec": MATCH_RADIUS, "k95": K95,
        "iterations": fit.iterations, "warnings": list(fit.warnings), "visits": visits,
        # Deviation from straight-line motion (the parallax wobble, if any) and the 1-sigma
        # uncertainty of the predicted position on each axis, sampled every 15 days.
        "curve": {"mjd": r3(grid), "xi_mas": r3((mx - lx) * 1000), "eta_mas": r3((my - ly) * 1000),
                  "sig_xi_mas": r3(sig[:, 0] * 1000), "sig_eta_mas": r3(sig[:, 1] * 1000)},
    }
