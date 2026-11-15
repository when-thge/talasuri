"""Train the mover classifier (processing/movers.py) and write its model file.

    python -m spherex_viewer.train_movers [--fields 150] [--seed 1] [--out PATH]

Needs scikit-learn (requirements-dev.txt) and network access to IRSA; the server itself
needs neither. For each of ``--fields`` random 30 arcmin fields at |b| >= 15 deg it
downloads the CatWISE2020 sources whose motion looks significant (the same cut the
interface uses) and the Gaia DR3 stars of the field. A CatWISE source with a Gaia
counterpart is labelled a mover if Gaia's total proper motion is >= MOVER_MIN_MAS; sources
without a counterpart have no truth and are left out. Downloads are cached, so a re-run
with the same seed only trains.

Gaia cannot supply truth for the objects it does not see, which are the ones a mover search
is for. So confirmed brown dwarfs from SIMBAD (object type BD*, catalogued proper motion
>= MOVER_MIN_MAS) are added as positives: each one's CatWISE entries whose motion agrees
with SIMBAD's. Use --no-brown-dwarfs to leave them out.

The reported scores come from 5-fold cross-validation with whole fields held out, next to
the obvious baseline (ranking by CatWISE motion significance alone). Brown dwarfs are held
out in groups too, and their recall is reported on its own, split by whether Gaia sees
them. Precision for sources Gaia does not see cannot be measured (there are no confirmed
non-movers there); the share of such unlabelled sources that gets flagged is reported
instead, as an upper bound on how much the brown dwarfs made the model over-eager.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import io
import json
import math
import sys
import time

import numpy as np

import httpx

from .config import settings
from .data_access import catalogs
from .data_access.names import SIMBAD_TAP_URLS
from .processing import movers

RADIUS_ARCMIN = 30.0
MIN_ABS_GLAT = 15.0


def random_fields(n: int, seed: int) -> list[tuple[float, float]]:
    """Uniform on the sphere, away from the Galactic plane."""
    from astropy import units as u
    from astropy.coordinates import SkyCoord
    rng = np.random.default_rng(seed)
    out: list[tuple[float, float]] = []
    while len(out) < n:
        ra = float(rng.uniform(0, 360))
        dec = float(np.degrees(np.arcsin(rng.uniform(-1, 1))))
        if abs(SkyCoord(ra * u.deg, dec * u.deg).galactic.b.deg) >= MIN_ABS_GLAT:
            out.append((round(ra, 4), round(dec, 4)))
    return out


async def fetch_field(ra: float, dec: float, sem: asyncio.Semaphore):
    async with sem:
        for attempt in range(4):
            try:
                cw = await catalogs.mover_candidates(ra, dec, RADIUS_ARCMIN)
                gaia = (await catalogs.cone("gaia", ra, dec, RADIUS_ARCMIN + 0.2, maglim=99))["sources"]
                return cw, gaia
            except Exception as e:  # IRSA hiccup: back off and retry
                if attempt == 3:
                    print(f"  field {ra} {dec} failed: {e}", file=sys.stderr)
                    return None
                await asyncio.sleep(5 * (attempt + 1))


async def gather(fields, concurrency: int):
    sem = asyncio.Semaphore(concurrency)
    done = 0

    async def one(f):
        nonlocal done
        r = await fetch_field(*f, sem)
        done += 1
        print(f"  {done}/{len(fields)} fields", end="\r", file=sys.stderr, flush=True)
        return r
    return await asyncio.gather(*(one(f) for f in fields))


def build_table(fields, data):
    """Labelled rows (Gaia truth), and the feature rows of candidates with no Gaia star."""
    xs, ys, groups, snr, unlabelled = [], [], [], [], []
    for gi, (f, d) in enumerate(zip(fields, data)):
        if d is None:
            continue
        cw, gaia = d
        cw = [r for r in cw if (movers.pm_snr(r) or 0) >= movers.MIN_PM_SNR]
        for r, g in zip(cw, movers.gaia_match(cw, gaia, catalogs.CATWISE_EPOCH)):
            if g is None:
                unlabelled.append(movers.features(r))
                continue
            if g["pmra"] is None or g["pmdec"] is None:
                continue   # no truth
            xs.append(movers.features(r))
            ys.append(math.hypot(g["pmra"], g["pmdec"]) >= movers.MOVER_MIN_MAS)
            groups.append(gi)
            snr.append(movers.pm_snr(r))
    return (np.array(xs, dtype=np.float32), np.array(ys, dtype=int), np.array(groups),
            np.array(snr), np.array(unlabelled, dtype=np.float32))


# ---- confirmed brown dwarfs (SIMBAD) as positives Gaia cannot supply ---------------------------
BD_QUERY = ("SELECT main_id, ra, dec, pmra, pmdec, sp_type FROM basic WHERE otype = 'BD*' "
            "AND ra IS NOT NULL AND pmra IS NOT NULL AND pmdec IS NOT NULL "
            f"AND (pmra*pmra+pmdec*pmdec) >= {movers.MOVER_MIN_MAS ** 2:g}")
BD_MATCH_ARCSEC = 4.0      # SIMBAD positions of faint brown dwarfs are good to a few arcsec
BD_GROUPS = 10


def simbad_brown_dwarfs() -> list[dict]:
    """SIMBAD's confirmed brown dwarfs with a proper motion (J2000 position, mas/yr); cached."""
    path = settings.cache_dir / "movers" / "simbad_brown_dwarfs.csv"
    if not path.exists():
        last = ""
        for url in SIMBAD_TAP_URLS:
            try:
                r = httpx.post(url, data={"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "csv",
                                          "MAXREC": "200000", "QUERY": BD_QUERY}, timeout=300)
                if r.status_code == 200 and r.text.startswith("main_id,"):
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(r.text)
                    break
                last = f"{url}: HTTP {r.status_code}"
            except httpx.HTTPError as e:
                last = f"{url}: {type(e).__name__}"
        else:
            raise RuntimeError(f"SIMBAD query failed ({last})")
    out = []
    for r in csv.DictReader(io.StringIO(path.read_text())):
        out.append({"id": r["main_id"], "ra": float(r["ra"]), "dec": float(r["dec"]),
                    "pmra": float(r["pmra"]), "pmdec": float(r["pmdec"]), "sp_type": r.get("sp_type") or ""})
    return out


def _at(bd: dict, epoch: float) -> tuple[float, float]:
    dt = epoch - 2000.0
    return ((bd["ra"] + bd["pmra"] * dt / 3.6e6 / math.cos(math.radians(bd["dec"]))) % 360,
            bd["dec"] + bd["pmdec"] * dt / 3.6e6)


async def brown_dwarf_rows(bds: list[dict]):
    """For each brown dwarf: its CatWISE candidate entries whose motion agrees with SIMBAD's
    (within half of it, or 3 sigma), and whether Gaia DR3 has a star there."""
    cw, gaia = await asyncio.gather(
        catalogs.upload_match("catwise_2020", movers.CATWISE_COLS, [_at(b, catalogs.CATWISE_EPOCH) for b in bds],
                              BD_MATCH_ARCSEC, movers.CANDIDATE_SQL),
        catalogs.upload_match("gaia_dr3_source", ["source_id"], [_at(b, movers.GAIA_EPOCH) for b in bds], 2.0))
    in_gaia = {int(r["cntr_01"]) for r in gaia}
    rows, owner, seen = [], [], set()
    for r in cw:
        i = int(r["cntr_01"]) - 1
        b = bds[i]
        pmra, pmdec, sra, sdec = movers.pm_mas(r)
        if not math.isfinite(pmra + pmdec + sra + sdec) or (r["source_name"], i) in seen:
            continue
        diff = math.hypot(pmra - b["pmra"], pmdec - b["pmdec"])
        if diff <= max(0.5 * math.hypot(b["pmra"], b["pmdec"]), 3 * math.hypot(sra, sdec)):
            seen.add((r["source_name"], i))
            rows.append(r)
            owner.append(i)
    return rows, np.array(owner, dtype=int), np.array([(i + 1) in in_gaia for i in range(len(bds))])


def export(clf) -> dict:
    """The fitted ensemble as plain lists: per tree, each node's feature (-1 for a leaf),
    threshold (go left when x <= threshold), children and value. scikit-learn folds the
    learning rate into the leaf values. This reads the estimator's internal node table, so
    main() checks the exported model against predict_proba before writing it."""
    trees = []
    for (pred,) in clf._predictors:
        n = pred.nodes
        leaf = n["is_leaf"].astype(bool)
        trees.append({"feature": [-1 if lf else int(f) for f, lf in zip(n["feature_idx"], leaf)],
                      "threshold": [0.0 if lf else float(v) for v, lf in zip(n["num_threshold"], leaf)],
                      "left": [-1 if lf else int(v) for v, lf in zip(n["left"], leaf)],
                      "right": [-1 if lf else int(v) for v, lf in zip(n["right"], leaf)],
                      "value": [float(v) if lf else 0.0 for v, lf in zip(n["value"], leaf)]})
    return {"init": float(np.ravel(clf._baseline_prediction)[0]), "learning_rate": 1.0, "trees": trees}


def importance(clf, x, y, seed: int) -> dict:
    """Permutation importance (drop in average precision) of the top features, on a sample."""
    from sklearn.inspection import permutation_importance
    rng = np.random.default_rng(seed)
    pick = rng.choice(len(y), min(len(y), 40000), replace=False)
    r = permutation_importance(clf, x[pick], y[pick], scoring="average_precision", n_repeats=3, random_state=seed)
    top = sorted(zip(movers.FEATURES, map(float, r.importances_mean)), key=lambda kv: -kv[1])[:8]
    return {k: round(v, 4) for k, v in top}


def scores(y, p, thr=0.5) -> dict:
    from sklearn.metrics import average_precision_score, roc_auc_score
    pred = p >= thr
    tp = int((pred & (y == 1)).sum())
    return {"roc_auc": float(roc_auc_score(y, p)), "average_precision": float(average_precision_score(y, p)),
            "precision": tp / max(int(pred.sum()), 1), "recall": tp / max(int(y.sum()), 1),
            "n_flagged": int(pred.sum())}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--fields", type=int, default=150)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--out", default=str(movers.MODEL_PATH))
    ap.add_argument("--fetch-only", action="store_true", help="download the training fields and stop")
    ap.add_argument("--no-brown-dwarfs", action="store_true", help="train on Gaia truth alone")
    a = ap.parse_args(argv)

    fields = random_fields(a.fields, a.seed)
    print(f"Fetching {len(fields)} fields (cached after the first run)…", file=sys.stderr)
    data = asyncio.run(gather(fields, a.concurrency))
    ok = sum(d is not None for d in data)
    print(f"\n{ok}/{len(fields)} fields available", file=sys.stderr)
    if a.fetch_only:
        return 0

    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.model_selection import GroupKFold

    x, y, groups, snr, unlabelled = build_table(fields, data)
    print(f"{len(y)} labelled candidates, {int(y.sum())} movers "
          f"(Gaia PM >= {movers.MOVER_MIN_MAS:g} mas/yr); {len(unlabelled)} candidates with no Gaia star",
          file=sys.stderr)
    n_gaia_rows = len(y)
    bd_info = None
    if not a.no_brown_dwarfs:
        bds = simbad_brown_dwarfs()
        bd_rows, owner, bd_in_gaia = asyncio.run(brown_dwarf_rows(bds))
        print(f"{len(bds)} SIMBAD brown dwarfs with PM >= {movers.MOVER_MIN_MAS:g} mas/yr; "
              f"{len(set(owner.tolist()))} have a CatWISE entry with an agreeing motion ({len(bd_rows)} entries)",
              file=sys.stderr)
        x = np.concatenate([x, movers.feature_matrix(bd_rows)])
        y = np.concatenate([y, np.ones(len(bd_rows), dtype=int)])
        groups = np.concatenate([groups, len(fields) + owner % BD_GROUPS])   # an object's entries stay together
        snr = np.concatenate([snr, [movers.pm_snr(r) for r in bd_rows]])
        bd_info = (bds, bd_rows, owner, bd_in_gaia)
    if y.sum() < 50:
        print("too few movers to train on; use more --fields", file=sys.stderr)
        return 1
    make = lambda: HistGradientBoostingClassifier(max_iter=300, max_depth=4, learning_rate=0.06,  # noqa: E731
                                                  l2_regularization=1.0, random_state=a.seed)
    oof = np.zeros(len(y))
    for train, test in GroupKFold(n_splits=5).split(x, y, groups):
        oof[test] = make().fit(x[train], y[train]).predict_proba(x[test])[:, 1]
    cv = scores(y[:n_gaia_rows], oof[:n_gaia_rows])      # the Gaia-truth sample, as before
    snr_all, y_all = snr, y
    snr, y_gaia = snr[:n_gaia_rows], y[:n_gaia_rows]
    # Baseline: rank by CatWISE motion significance alone; flag as many as the model does.
    order = np.argsort(-snr)
    base_pred = np.zeros(n_gaia_rows, dtype=bool)
    base_pred[order[:cv["n_flagged"]]] = True
    base_tp = int((base_pred & (y_gaia == 1)).sum())
    from sklearn.metrics import average_precision_score, roc_auc_score
    baseline = {"roc_auc": float(roc_auc_score(y_gaia, snr)), "average_precision": float(average_precision_score(y_gaia, snr)),
                "precision": base_tp / max(cv["n_flagged"], 1), "recall": base_tp / max(int(y_gaia.sum()), 1)}
    snr, y = snr_all, y_all
    print("cross-validated (fields held out):", json.dumps(cv), file=sys.stderr)
    print("baseline (PM significance only):  ", json.dumps(baseline), file=sys.stderr)

    clf = make().fit(x, y)
    brown_dwarfs = None
    if bd_info:
        bds, bd_rows, owner, bd_in_gaia = bd_info
        p_bd = oof[n_gaia_rows:]                      # each scored by a model that never saw it
        no_gaia = ~bd_in_gaia[owner]
        # What a model trained on Gaia truth alone gives the same entries, for comparison.
        before = make().fit(x[:n_gaia_rows], y[:n_gaia_rows])
        p_before = before.predict_proba(x[n_gaia_rows:])[:, 1]
        rec = lambda p, m: float((p[m] >= 0.5).mean()) if m.any() else None      # noqa: E731
        brown_dwarfs = {
            "n_simbad": len(bds), "n_objects": len(set(owner.tolist())), "n_entries": len(bd_rows),
            "n_entries_not_in_gaia": int(no_gaia.sum()),
            "cv_recall": rec(p_bd, np.ones(len(p_bd), bool)), "cv_recall_not_in_gaia": rec(p_bd, no_gaia),
            "recall_without_them": rec(p_before, np.ones(len(p_bd), bool)),
            "recall_without_them_not_in_gaia": rec(p_before, no_gaia),
            # Sources with no Gaia star in the random fields: truth unknown, mostly not movers.
            "unlabelled_n": int(len(unlabelled)),
            "unlabelled_flagged": float((clf.predict_proba(unlabelled)[:, 1] >= 0.5).mean()),
            "unlabelled_flagged_without_them": float((before.predict_proba(unlabelled)[:, 1] >= 0.5).mean()),
            "examples": {},
        }
        for name in ("WISEA J085510.74-071442.5", "WISE J085510.83-071442.5", "NAME Luhman 16"):
            for i in np.flatnonzero([bds[o]["id"] == name for o in owner]):
                brown_dwarfs["examples"][f"{name} / CatWISE {bd_rows[i]['source_name']}"] = {
                    "held_out": round(float(p_bd[i]), 3), "without_brown_dwarfs": round(float(p_before[i]), 3)}
        print("brown dwarfs:", json.dumps(brown_dwarfs), file=sys.stderr)
    model = {
        "features": movers.FEATURES, **export(clf),
        "trained": time.strftime("%Y-%m-%d"), "n_fields": ok, "n_train": int(len(y)),
        "n_movers": int(y.sum()), "mover_min_mas": movers.MOVER_MIN_MAS,
        "min_pm_snr": movers.MIN_PM_SNR, "min_abs_glat": MIN_ABS_GLAT, "threshold": 0.5,
        "cv": cv, "baseline": baseline, "brown_dwarfs": brown_dwarfs,
        "importance": importance(clf, x, y, a.seed),
    }
    # The numpy evaluator must reproduce scikit-learn exactly; a few rows travel with the
    # model so the unit tests can check that without scikit-learn installed.
    mine = movers.Model(model).predict(x)
    ref = clf.predict_proba(x)[:, 1]
    if not np.allclose(mine, ref, atol=1e-9):
        print(f"exported model disagrees with scikit-learn (max diff {np.abs(mine - ref).max():.2e}); "
              "the estimator's internals have changed, update export()", file=sys.stderr)
        return 1
    pick = np.unique(np.concatenate([np.argsort(ref)[:6], np.argsort(ref)[-6:],
                                     np.random.default_rng(a.seed).choice(len(y), 12, replace=False)]))
    model["check"] = [{"x": [float(v) for v in x[i]], "p": float(ref[i])} for i in pick]
    with open(a.out, "w") as f:
        json.dump(model, f, separators=(",", ":"))
    print(f"wrote {a.out} ({len(model['trees'])} trees)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
