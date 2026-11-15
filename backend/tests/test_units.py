"""Offline unit tests (no network)."""
from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits

from spherex_viewer.data_access.fitsmeta import (DEFAULT_BAD_FLAGS, decode_flags, load_cutout,
                                                 mask_for_names, parse_flag_bits, wavelength_at)
from spherex_viewer.data_access.releases import build_collections, parse_collection_name
from spherex_viewer.coords import (CoordinateError, check_range, format_decimal,
                                   format_sexagesimal, parse_coordinates)
from spherex_viewer.data_access.resolver import Target, epoch_to_mjd, parse_sesame_xml
from spherex_viewer.data_access.sia import Observation, dedupe
from spherex_viewer.processing.grid import make_grid
from spherex_viewer.processing.photometry import aperture_photometry, aperture_weights
from spherex_viewer.processing.pipeline import (GridFrame, Selection, build_products,
                                                group_epochs, ivw_stack, ivw_weights, single,
                                                subtract)
from spherex_viewer.processing.render import stretch

FIXTURE = Path(__file__).parent / "fixtures" / "cutout_D6_wise0855.fits"


# --- coordinate parsing ---------------------------------------------------------------
@pytest.mark.parametrize("text", [
    "133.79513 -7.24515", "133.79513,-7.24515", "133.79513, -7.24515",
    "08:55:10.831 -07:14:42.53", "08h55m10.831s -07d14m42.53s", "08 55 10.831 -07 14 42.53",
    "08:55:10.831 −07:14:42.53", "08h55m10.831s, -07°14′42.53″",
])
def test_parse_coordinates_wise0855(text):
    ra, dec = parse_coordinates(text)
    assert ra == pytest.approx(133.79513, abs=2e-5)
    assert dec == pytest.approx(-7.24515, abs=2e-5)


def test_parse_coordinates_positive_dec_and_zero():
    assert parse_coordinates("0 +0") == (0.0, 0.0)
    ra, dec = parse_coordinates("17:57:48.5 +04:41:36")
    assert ra == pytest.approx(269.452083, abs=1e-5) and dec == pytest.approx(4.693333, abs=1e-5)
    ra, dec = parse_coordinates("00:00:00 -00:30:00")  # negative zero degrees
    assert dec == pytest.approx(-0.5)


@pytest.mark.parametrize("name", ["Barnard's Star", "eps Indi B", "RW Aur", "R Dra", "M31",
                                  "WISEA J085510.74-071442.5", "HD 1234"])
def test_names_are_not_coordinates(name):
    assert parse_coordinates(name) is None


def test_out_of_range_coordinates():
    with pytest.raises(CoordinateError):
        parse_coordinates("400 10")
    with pytest.raises(CoordinateError):
        parse_coordinates("10 -95")


def test_coordinates_shared_cases():
    """The cases the frontend's coords.ts runs too (shared/coords_cases.json)."""
    import json
    cases = json.loads((Path(__file__).parents[2] / "shared" / "coords_cases.json").read_text())
    for c in cases["parse"]:
        if c["expect"] == "error":
            with pytest.raises(CoordinateError):
                parse_coordinates(c["text"])
        elif c["expect"] is None:
            assert parse_coordinates(c["text"]) is None, c["text"]
        else:
            assert parse_coordinates(c["text"]) == pytest.approx(c["expect"], abs=1e-9), c["text"]
    for c in cases["format"]:
        assert format_sexagesimal(c["ra"], c["dec"]) == c["sexagesimal"]
        assert format_sexagesimal(c["ra"], c["dec"], 1, 0) == c["sexagesimal_1_0"]
        assert format_decimal(c["ra"], c["dec"]) == c["decimal"]
        ra, dec = parse_coordinates(c["decimal"])
        assert abs((ra - c["ra"] + 180) % 360 - 180) < 1e-5 and abs(dec - c["dec"]) < 1e-5


def test_sexagesimal_matches_astropy_and_rounding_carries():
    import astropy.units as u
    from astropy.coordinates import SkyCoord
    rng = np.random.default_rng(3)
    for ra, dec in zip(rng.uniform(0, 360, 200), rng.uniform(-90, 90, 200)):
        ref = SkyCoord(ra * u.deg, dec * u.deg).to_string("hmsdms", sep=":", precision=2)
        assert format_sexagesimal(ra, dec) == ref
    assert format_sexagesimal(14.99999999, 59.9999999) == "01:00:00.00 +60:00:00.00"
    assert format_sexagesimal(10.0, -0.25, 1, 0) == "00:40:00.0 -00:15:00"


def test_session_request_uses_the_shared_range_check():
    from pydantic import ValidationError
    from spherex_viewer.api.app import SessionRequest
    assert check_range(359.9, -90.0) == (359.9, -90.0)
    assert SessionRequest(ra=10, dec=20).fov == 5.0
    for ra, dec in ((360.0, 0.0), (-0.1, 0.0), (10.0, 90.5)):
        with pytest.raises(ValidationError):
            SessionRequest(ra=ra, dec=dec)


def test_sesame_xml():
    xml = """<Sesame><Target><Resolver name="S=Simbad">
      <oname>BD+04  3561a</oname><jradeg>269.45207695</jradeg><jdedeg>4.69339088</jdedeg>
      <pmRA>-801.551</pmRA><pmDE>10362.394</pmDE></Resolver></Target></Sesame>"""
    d = parse_sesame_xml(xml)
    assert d["ra"] == pytest.approx(269.45207695) and d["pmdec"] == pytest.approx(10362.394)
    assert parse_sesame_xml("<Sesame><INFO>nothing</INFO></Sesame>") is None


def test_proper_motion_propagation():
    # Barnard's Star: ~10.36"/yr north. Over 26 yr -> ~269" in Dec.
    t = Target(269.45208, 4.69339, -801.551, 10362.394, 2000.0)
    ra, dec = t.position_at(epoch_to_mjd(2026.0))
    assert (dec - 4.69339) * 3600 == pytest.approx(10.362394 * 26, rel=1e-6)
    assert (ra - 269.45208) * 3600 * np.cos(np.radians(4.69339)) == pytest.approx(-0.801551 * 26, rel=1e-6)
    assert Target(10, 20).position_at(70000) == (10, 20)


# --- FITS: wavelength + flags ---------------------------------------------------------
def test_wavelength_extraction_fixture():
    nf = load_cutout(FIXTURE)
    x, y = nf.target_pixel(133.79513, -7.24515)
    lam, bw = wavelength_at(nf.hdul, x, y)
    # D6 covers 4.41-5.01 um; value cross-checked with the IRSA tutorial recipe.
    assert 4.41 < lam < 5.01
    assert lam == pytest.approx(4.9684, abs=2e-3)
    assert bw == pytest.approx(0.0372, abs=1e-3)
    # LVF: wavelength must vary across the cutout
    lam0, _ = wavelength_at(nf.hdul, 0, 0)
    lam1, _ = wavelength_at(nf.hdul, 28, 28)
    assert abs(lam1 - lam0) > 1e-3


def test_wavelength_uses_cutout_offset():
    """The cutout service shifts CRPIXnW; the result must equal the full-frame lookup at
    the corresponding full-frame pixel, which we reconstruct by undoing the shift."""
    from scipy.interpolate import RegularGridInterpolator
    nf = load_cutout(FIXTURE)
    h = nf.header
    tab = nf.hdul["WCS-WAVE"].data
    values, gx, gy = tab["VALUES"][0], tab["X"][0], tab["Y"][0]   # VALUES[y, x, (lam, bw)]
    for x, y in [(0.0, 0.0), (10.0, 20.0), (28.0, 5.5)]:
        # full-frame 1-based pixel from the (shifted) alternate-W linear transform
        px = h["CRVAL1W"] + (x + 1 - h["CRPIX1W"]) * h["CDELT1W"]
        py = h["CRVAL2W"] + (y + 1 - h["CRPIX2W"]) * h["CDELT2W"]
        lam_ref = RegularGridInterpolator((gy, gx), values[..., 0])([py, px])[0]
        bw_ref = RegularGridInterpolator((gy, gx), values[..., 1])([py, px])[0]
        lam, bw = wavelength_at(nf.hdul, x, y)
        assert lam == pytest.approx(lam_ref, abs=1e-6) and bw == pytest.approx(bw_ref, abs=1e-6)


def test_flag_bits_from_header():
    nf = load_cutout(FIXTURE)
    bits = nf.flag_bits
    names = {b.name for b in bits.values()}
    assert {"TRANSIENT", "OVERFLOW", "NONFUNC", "SOURCE", "PERSIST", "HALO"} <= names
    assert bits[21].name == "SOURCE" and bits[21].mask == 2097152
    assert bits[0].name == "TRANSIENT"
    bad = mask_for_names(bits, DEFAULT_BAD_FLAGS)
    assert not bad & (1 << 21)  # SOURCE is never "bad"
    assert decode_flags((1 << 0) | (1 << 21), bits) == ["TRANSIENT", "SOURCE"]


def test_flag_bit_mask_mismatch_raises():
    h = fits.Header()
    h["MSKN0003"], h["MSKM0003"] = "X", 4
    with pytest.raises(ValueError):
        parse_flag_bits(h)


# --- stacking ---------------------------------------------------------------------------
def _frame(key, sci, var, flags=None, det=1, mjd=60000.0, lam=1.0):
    sci = np.asarray(sci, dtype=np.float32)
    return GridFrame(key=key, obs_id=key, detector=det, mjd=mjd, lam_um=lam, bw_um=0.01, sci=sci,
                     var=np.asarray(var, dtype=np.float32),
                     flags=np.zeros(sci.shape, np.int64) if flags is None else np.asarray(flags))


def test_ivw_weights():
    var = np.array([[1.0, 4.0], [0.0, np.nan]])
    flags = np.array([[0, 0], [0, 0]])
    w = ivw_weights(var, flags, bad_mask=1)
    assert w.tolist()[0] == [1.0, 0.25] and w[1, 0] == 0 and w[1, 1] == 0
    w = ivw_weights(var, np.array([[1, 2], [0, 0]]), bad_mask=1)
    assert w[0, 0] == 0 and w[0, 1] == 0.25  # only bit 0 is bad


def test_ivw_stack_values_and_variance():
    a = _frame("a", [[1.0]], [[1.0]])
    b = _frame("b", [[4.0]], [[4.0]])
    sci, var, _, n = ivw_stack([a, b], bad_mask=0)
    # (1*1 + 4*0.25) / (1 + 0.25) = 1.6 ; var = 1/1.25 = 0.8
    assert sci[0, 0] == pytest.approx(1.6) and var[0, 0] == pytest.approx(0.8) and n[0, 0] == 2


def test_ivw_stack_equal_variance_is_mean_and_sqrtN_noise():
    rng = np.random.default_rng(1)
    frames = [_frame(str(i), rng.normal(0, 1, (50, 50)), np.ones((50, 50))) for i in range(16)]
    sci, var, _, _ = ivw_stack(frames, 0)
    assert np.allclose(sci, np.mean([f.sci for f in frames], axis=0), atol=1e-5)
    assert np.allclose(var, 1 / 16)
    assert np.std(sci) == pytest.approx(0.25, rel=0.1)


def test_ivw_stack_masks_flagged_and_nan():
    a = _frame("a", [[1.0, np.nan]], [[1.0, 1.0]], flags=[[4, 0]])
    b = _frame("b", [[3.0, 5.0]], [[1.0, 1.0]])
    sci, var, flags, n = ivw_stack([a, b], bad_mask=4)
    assert sci[0, 0] == pytest.approx(3.0) and sci[0, 1] == pytest.approx(5.0)
    assert n.tolist() == [[1, 1]] and flags[0, 0] == 4
    c = _frame("c", [[1.0]], [[1.0]], flags=[[4]])
    sci, var, _, n = ivw_stack([c], bad_mask=4)
    assert np.isnan(sci[0, 0]) and n[0, 0] == 0


def test_group_epochs_and_modes():
    fs = [_frame(f"f{i}", [[i]], [[1]], det=1 + i % 6, mjd=m)
          for i, m in enumerate([0, 1, 2, 180, 181, 400])]
    groups = group_epochs(fs, 10)
    assert [len(g) for g in groups] == [3, 2, 1]
    assert len(build_products(fs, "frames", Selection(), 0)) == 6
    assert len(build_products(fs, "epoch", Selection(), 0, window_days=10)) == 3
    assert len(build_products(fs, "detector", Selection(), 0)) == 6
    assert len(build_products(fs, "detector", Selection(detectors=(1, 2)), 0)) == 2
    assert len(build_products(fs, "wave", Selection(lam_min=0.5, lam_max=2), 0)) == 1
    assert build_products(fs, "frames", Selection(mjd_min=500), 0) == []


def test_difference_modes():
    """Each stack minus the median of all / minus a reference, with the sky pedestal (the
    difference image's own median) removed so an unchanged sky is exactly zero."""
    def img(sky, src):
        a = np.full((3, 3), sky, dtype=float)
        a[1, 1] += src
        return a
    # three visits: different leftover sky levels, a source that brightens
    ps = [single(_frame(str(i), img(sky, src), np.ones((3, 3))), "")
          for i, (sky, src) in enumerate([(0.10, 1.0), (0.20, 2.0), (0.30, 6.0)])]
    med = subtract(ps, "median")
    assert [float(p.sci[1, 1]) for p in med] == pytest.approx([-1.0, 0.0, 4.0], abs=1e-6)
    assert all(np.allclose(p.sci[0], 0.0, atol=1e-6) for p in med)      # sky -> 0
    ref = subtract(ps, "ref", 2)
    assert [float(p.sci[1, 1]) for p in ref] == pytest.approx([-5.0, -4.0, 0.0], abs=1e-6)
    assert all(np.allclose(p.sci[0], 0.0, atol=1e-6) for p in ref) and ref[0].var[0, 0] == 2.0
    with pytest.raises(ValueError):
        subtract(ps, "ref", 5)


def test_display_limits_keep_noise_out_of_the_grey_scale():
    from spherex_viewer.processing.render import DIFF_SIGMAS, limits, stretch
    rng = np.random.default_rng(3)
    sky = rng.normal(0.05, 0.01, (64, 64))
    sparse = sky.copy()
    sparse[10:15, 10:15] += 5.0                      # a few stars on empty sky
    sparse[40:43, 50:53] += 2.0
    lo, hi = limits([sparse])
    assert 0.05 + 0.5 * 0.01 < lo < 0.05 + 1.5 * 0.01      # black point = sky + 1 sigma
    assert (sparse < lo).mean() > 0.8                        # most of the sky is flat
    # a field filled with extended emission keeps its faint end
    filled = sky + np.linspace(0, 1, 64)[None, :]
    lo_f, _ = limits([filled])
    assert (filled < lo_f).mean() < 0.02
    # difference image: symmetric, noise within a small part of the range
    d = rng.normal(0, 0.01, (64, 64))
    lo_d, hi_d = limits([d], symmetric=True)
    assert lo_d == -hi_d and hi_d >= DIFF_SIGMAS * 0.01 * 0.9
    # bipolar stretch: the middle is mid-grey and both signs are treated alike
    for mode in ("linear", "asinh", "sqrt", "log"):
        t = stretch(np.array([-0.5, 0.0, 0.5]), -1.0, 1.0, mode, bipolar=True)
        assert t[1] == pytest.approx(0.5) and t[0] + t[2] == pytest.approx(1.0)
        ti = stretch(np.array([-0.5, 0.0, 0.5]), -1.0, 1.0, mode, invert=True, bipolar=True)
        assert ti == pytest.approx(1.0 - t)


# --- photometry -----------------------------------------------------------------------
def test_aperture_weights_area():
    w = aperture_weights((41, 41), 20.3, 19.7, 5.0, oversample=20)
    assert w.sum() == pytest.approx(np.pi * 25, rel=2e-3)


def test_aperture_photometry_recovers_injected_source():
    nf = load_cutout(FIXTURE)
    rng = np.random.default_rng(0)
    ny, nx = nf.image.shape
    nf.zodi[:] = 0.5
    nf.image[:] = 0.5 + 0.1 + rng.normal(0, 0.01, (ny, nx))  # zodi + flat background + noise
    nf.variance[:] = 0.01 ** 2
    nf.flags[:] = 0
    x0, y0 = 14.2, 13.8
    yy, xx = np.indices((ny, nx))
    sigma = 9.0 / 6.15 / 2.355
    total_sb = 10.0
    nf.image += total_sb * np.exp(-((xx - x0) ** 2 + (yy - y0) ** 2) / (2 * sigma ** 2)) / (2 * np.pi * sigma ** 2)
    ra, dec = nf.wcs.pixel_to_world_values(x0, y0)
    ph = aperture_photometry(nf, float(ra), float(dec), bad_mask=0, r_ap=4.0, r_in=6.0, r_out=11.0)
    omega_sr = nf.omega_arcsec2 * (np.pi / 180 / 3600) ** 2
    expected = total_sb * omega_sr * 1e12
    assert ph.ok and ph.flux_ujy == pytest.approx(expected, rel=0.02)
    assert ph.bkg_mjysr == pytest.approx(0.1, abs=2e-3)
    assert 0 < ph.err_ujy < 0.05 * expected


# --- grid, render, registry -------------------------------------------------------------
def test_grid_is_north_up_and_centered():
    g = make_grid(133.8, -7.2, 5.0)
    assert g.npix % 2 == 1
    x, y = g.sky_to_pix(133.8, -7.2)
    assert x == pytest.approx(g.center_pix) and y == pytest.approx(g.center_pix)
    x1, y1 = g.sky_to_pix(133.8, -7.2 + 6.15 / 3600)  # 1 px north -> +y
    assert y1 - y == pytest.approx(1.0, abs=1e-3) and x1 == pytest.approx(x, abs=1e-3)
    x2, _ = g.sky_to_pix(133.8 + 6.15 / 3600 / np.cos(np.radians(7.2)), -7.2)  # east -> -x
    assert x2 - x == pytest.approx(-1.0, abs=1e-3)


def test_stretches_monotonic_and_invert():
    a = np.linspace(-1, 2, 50)
    for m in ("linear", "asinh", "log", "sqrt"):
        t = stretch(a, 0, 1, m)
        assert t.min() == 0 and t.max() == 1 and np.all(np.diff(t) >= 0)
    assert np.allclose(stretch(a, 0, 1, "linear", invert=True), 1 - stretch(a, 0, 1, "linear"))


def test_registry_parsing_and_priority():
    assert parse_collection_name("spherex_qr3_deep")[:2] == ("qr3", "deep")
    assert parse_collection_name("spherex_dr1")[:2] == ("dr1", "wide")
    assert parse_collection_name("spherex_qr")[:2] == ("qr", "wide")
    assert parse_collection_name("wise_allwise") is None
    rows = [{"obs_collection": c} for c in
            ("spherex_qr3", "spherex_dr1", "spherex_dr1_cal", "spherex_qr4", "spherex_dr2_deep")]
    cols = build_collections(rows)
    assert [c.name for c in cols] == ["spherex_dr2_deep", "spherex_dr1", "spherex_qr4", "spherex_qr3"]


def test_dedupe_prefers_higher_priority():
    def obs(coll, key):
        return Observation(key, key[:-3], 1, coll, coll[8:], f"u/{coll}", 1.0, 1.0, 1, 2, 40)
    cols = {c.name: c for c in build_collections(
        [{"obs_collection": "spherex_qr3"}, {"obs_collection": "spherex_dr1"}])}
    out = dedupe([(cols["spherex_qr3"], [obs("spherex_qr3", "A_D1"), obs("spherex_qr3", "B_D1")]),
                  (cols["spherex_dr1"], [obs("spherex_dr1", "A_D1")])])
    assert {o.key: o.collection for o in out} == {"A_D1": "spherex_dr1", "B_D1": "spherex_qr3"}


def test_photometry_withholds_flux_for_blank_saturated_core():
    nf = load_cutout(FIXTURE)
    ny, nx = nf.image.shape
    nf.zodi[:] = 0.0
    nf.image[:] = 0.1
    nf.variance[:] = 1e-4
    nf.flags[:] = 0
    overflow = mask_for_names(nf.flag_bits, ["OVERFLOW"])
    x0, y0 = 14.0, 14.0
    yy, xx = np.indices((ny, nx))
    core = np.hypot(xx - x0, yy - y0) <= 1.5
    nf.image[core] = np.nan            # pipeline blanks the saturated core
    nf.flags[core] = overflow
    ra, dec = nf.wcs.pixel_to_world_values(x0, y0)
    bad = mask_for_names(nf.flag_bits, DEFAULT_BAD_FLAGS)
    ph = aperture_photometry(nf, float(ra), float(dec), bad)
    assert ph.saturated and not ph.ok
    assert np.isnan(ph.flux_ujy) and ph.frac_missing > 0.2
    assert "OVERFLOW" in ph.ap_flag_names and "saturated" in ph.note


# --- optimisations: fast reprojection, cache slimming, Sesame fallback -----------------
def test_fast_reprojection_matches_reproject_package():
    reproject = pytest.importorskip("reproject")
    nf = load_cutout(FIXTURE)
    from spherex_viewer.processing.pipeline import reproject_frame
    g = make_grid(133.79513, -7.24515, 2.0)
    sci, var, flg = reproject_frame(nf, g)
    so, _ = reproject.reproject_interp((nf.image - nf.zodi, nf.wcs), g.wcs, shape_out=g.shape, order="bilinear")
    vo, _ = reproject.reproject_interp((nf.variance, nf.wcs), g.wcs, shape_out=g.shape, order="bilinear")
    fo, _ = reproject.reproject_interp((nf.flags.astype(float), nf.wcs), g.wcs, shape_out=g.shape,
                                       order="nearest-neighbor")
    assert np.array_equal(np.isfinite(sci), np.isfinite(so))
    ok = np.isfinite(so)
    assert np.allclose(sci[ok], so[ok], rtol=1e-5, atol=1e-6)
    assert np.allclose(var[ok], vo[ok], rtol=1e-5, atol=1e-9)
    assert np.array_equal(flg[ok], fo[ok].astype(np.int64))


def test_slim_keeps_nearest_psfs_and_data(tmp_path):
    from spherex_viewer.data_access.fitsmeta import full_frame_center, slim_file
    with fits.open(FIXTURE) as h:
        cx, cy = full_frame_center(h["IMAGE"].header)
        gx, gy = np.meshgrid(np.arange(21) * 97.0 + 49, np.arange(21) * 97.0 + 49)
        cols = [fits.Column("XCENTER", "E", array=gx.ravel()), fits.Column("YCENTER", "E", array=gy.ravel()),
                fits.Column("EPSF", "1089D", dim="(33,33)", array=np.zeros((441, 33, 33)))]
        epsf = fits.BinTableHDU.from_columns(cols, name="EPSF")
        path = tmp_path / "c.fits"
        fits.HDUList([h[0], h["IMAGE"], h["FLAGS"], h["VARIANCE"], h["ZODI"], epsf, h["WCS-WAVE"]]).writeto(path)
    before = load_cutout(path)
    assert slim_file(path) > 0
    after = load_cutout(path)
    for k in ("image", "variance", "flags", "zodi"):
        assert np.array_equal(getattr(before, k), getattr(after, k), equal_nan=True)
    kept = fits.open(path)["EPSF"].data
    assert len(kept) == 4
    d = np.hypot(kept["XCENTER"] - cx, kept["YCENTER"] - cy)
    assert d.max() <= 97 * np.sqrt(2)  # the four grid PSFs around the cutout
    assert slim_file(path) == 0  # idempotent


@pytest.fixture
def isolated_settings(tmp_path):
    """Point the (frozen) global settings at a temp cache and fake Sesame mirrors."""
    from spherex_viewer.config import settings
    saved = {k: getattr(settings, k) for k in ("cache_dir", "sesame_urls")}
    object.__setattr__(settings, "cache_dir", tmp_path)
    object.__setattr__(settings, "sesame_urls", ("https://primary.invalid/s", "https://mirror.invalid/s"))
    yield settings
    for k, v in saved.items():
        object.__setattr__(settings, k, v)


def test_sesame_falls_back_to_mirror_and_caches(isolated_settings):
    import asyncio
    import httpx
    from spherex_viewer.data_access import resolver
    xml = ("<Sesame><Resolver><oname>X</oname><jradeg>10.5</jradeg><jdedeg>-5.25</jdedeg>"
           "<pmRA>1.0</pmRA><pmDE>2.0</pmDE></Resolver></Sesame>")
    calls = []

    def handler(req):
        calls.append(req.url.host)
        if req.url.host == "primary.invalid":
            raise httpx.ReadTimeout("slow", request=req)
        return httpx.Response(200, text=xml)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    t = asyncio.run(resolver.sesame_resolve("Test Star", client))
    assert (t.ra, t.dec, t.pmdec) == (10.5, -5.25, 2.0) and calls == ["primary.invalid", "mirror.invalid"]
    # second lookup comes from the disk cache, no network
    t2 = asyncio.run(resolver.sesame_resolve("test  star", httpx.AsyncClient(transport=httpx.MockTransport(
        lambda r: (_ for _ in ()).throw(AssertionError("network used"))))))
    assert t2.ra == 10.5


# --- name suggestions -----------------------------------------------------------------
from spherex_viewer.data_access import names as names_mod


def test_name_normalize_and_expand():
    assert names_mod.normalize("Barnard's  Star!") == "barnards star"
    assert names_mod.display_label("NAME Barnard's star") == "Barnard's star"
    assert names_mod.display_label("V* R Dra") == "R Dra"
    assert names_mod.display_label("M  31") == "M 31"
    key = names_mod.expand("eps Ind B")
    assert "epsilon" in key and "indi" in key
    assert "m31" in names_mod.expand("M 31")


@pytest.mark.parametrize("query,expected_first", [
    ("barnard", None),            # checked separately below (several Barnard objects)
    ("m31", "M 31"), ("M 31", "M 31"), ("ngc7027", "NGC 7027"),
    ("epsilon indi b", "eps Ind B"), ("r dra", "R Dra"), ("rw aur", "RW Aur"),
    ("wise 0855", "WISE 0855-0714"), ("betelgeuse", "Betelgeuse"), ("sirius", "Sirius"),
])
def test_local_suggestions_rank_the_obvious_object_first(query, expected_first):
    items = names_mod.suggest_local(query, 5)
    assert items, query
    if expected_first:
        assert items[0]["label"] == expected_first, [i["label"] for i in items]
    for it in items:
        assert -90 <= it["dec"] <= 90 and 0 <= it["ra"] < 360 and it["type"]


def test_barnards_star_suggestion_carries_proper_motion():
    items = names_mod.suggest_local("barnards st", 3)
    star = next(i for i in items if "star" in i["label"].lower())
    assert star["pmdec"] == pytest.approx(10362.394, abs=1)  # mas/yr, as Sesame returns
    assert star["dec"] == pytest.approx(4.6934, abs=1e-3)


def test_suggestions_are_deduplicated_and_short_queries_ignored():
    items = names_mod.suggest_local("sirius", 8)
    assert len({i["main_id"] for i in items}) == len(items)
    assert names_mod.suggest_local("s", 8) == []


def test_solar_system_note():
    assert "Solar-System" in names_mod.solar_system_note("Jupiter")
    assert names_mod.solar_system_note("Vega") is None


def test_suggest_endpoint_handles_coordinates_and_names():
    import asyncio
    from spherex_viewer.api.app import suggest
    r = asyncio.run(suggest(q="133.79 -7.24", live=False, limit=8))
    assert r["items"] == [] and "Coordinates" in r["note"]
    r = asyncio.run(suggest(q="jupiter", live=False, limit=8))
    assert "Solar-System" in r["note"]
    r = asyncio.run(suggest(q="vega", live=False, limit=8))
    assert r["items"][0]["label"] == "Vega"


# --- S3 byte-range cutouts --------------------------------------------------------------
def _fake_full_frame(flag_seed: int) -> bytes:
    """A small 'full-frame' MEF with the archive layout: plain IMAGE/VARIANCE/ZODI, RICE
    tile-compressed FLAGS (one row per tile), EPSF and WCS-WAVE tables."""
    import io
    with fits.open(FIXTURE) as h:
        rng = np.random.default_rng(flag_seed)
        flags = (rng.integers(0, 4, h["FLAGS"].data.shape) * (1 << rng.integers(0, 28))).astype(np.int32)
        flag_hdr = h["FLAGS"].header.copy()
        comp = fits.CompImageHDU(data=flags, header=flag_hdr, compression_type="RICE_1",
                                 tile_shape=(1, flags.shape[1]), name="FLAGS")
        epsf = fits.BinTableHDU.from_columns(
            [fits.Column("XCENTER", "E", array=np.arange(4.0)), fits.Column("YCENTER", "E", array=np.arange(4.0))],
            name="EPSF")
        hdul = fits.HDUList([fits.PrimaryHDU(), h["IMAGE"].copy(), comp, h["VARIANCE"].copy(),
                             h["ZODI"].copy(), epsf, h["WCS-WAVE"].copy()])
        buf = io.BytesIO()
        hdul.writeto(buf)
        return buf.getvalue(), flags


def _range_transport(files: dict[str, bytes]):
    import httpx

    def handler(req):
        data = files[req.url.path]
        a, b = req.headers["Range"].removeprefix("bytes=").split("-")
        return httpx.Response(206, content=data[int(a): int(b) + 1])
    return httpx.MockTransport(handler)


def test_s3_cutout_matches_direct_crop_and_learns_layout():
    import asyncio
    import io
    import httpx
    from spherex_viewer.data_access import s3cutouts
    from spherex_viewer.data_access.fitsmeta import celestial_wcs
    full_a, flags_a = _fake_full_frame(1)
    full_b, flags_b = _fake_full_frame(7)   # different flags -> different compressed size
    base = "https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/level2/X/l2b-v27-2026-197/6/"
    files = {"/" + "dr1/level2/X/l2b-v27-2026-197/6/" + n: d for n, d in (("a.fits", full_a), ("b.fits", full_b))}
    s3cutouts.layouts._known.clear()
    orig = load_cutout(FIXTURE)
    ra, dec = (float(v) for v in orig.wcs.pixel_to_world_values(14.0, 13.0))
    size = 10 * 6.15 / 3600

    async def run():
        sem = asyncio.Semaphore(8)
        async with httpx.AsyncClient(transport=_range_transport(files),
                                     base_url="https://nasa-irsa-spherex.s3.us-east-1.amazonaws.com") as c:
            a = await s3cutouts.fetch_s3_cutout(c, sem, base + "a.fits", ra, dec, size)
            learned = s3cutouts.layouts.get(base + "a.fits") is not None
            b = await s3cutouts.fetch_s3_cutout(c, sem, base + "b.fits", ra, dec, size)  # predicted path
            off = await s3cutouts.fetch_s3_cutout(c, sem, base + "a.fits", ra + 5, dec, size)
            return a, b, learned, off

    a, b, learned, off = asyncio.run(run())
    assert learned and off is None
    for raw, flags in ((a, flags_a), (b, flags_b)):
        cut = fits.open(io.BytesIO(raw))
        x0, y0 = cut[0].header["CUTX0"], cut[0].header["CUTY0"]
        ny, nx = cut["IMAGE"].data.shape
        assert 9 <= nx <= 13 and 9 <= ny <= 13
        assert np.array_equal(cut["IMAGE"].data, orig.image[y0:y0 + ny, x0:x0 + nx], equal_nan=True)
        assert np.array_equal(cut["VARIANCE"].data, orig.variance[y0:y0 + ny, x0:x0 + nx], equal_nan=True)
        assert np.array_equal(cut["FLAGS"].data, flags[y0:y0 + ny, x0:x0 + nx])
        # same sky position -> same detector pixel, and the same wavelength
        cx, cy = celestial_wcs(cut["IMAGE"].header).world_to_pixel_values(ra, dec)
        assert cx + x0 == pytest.approx(14.0, abs=1e-6) and cy + y0 == pytest.approx(13.0, abs=1e-6)
        assert wavelength_at(cut, float(cx), float(cy)) == pytest.approx(wavelength_at(orig.hdul, 14.0, 13.0), abs=1e-9)


def test_s3_url_mapping():
    from spherex_viewer.data_access.s3cutouts import s3_url
    u = "https://irsa.ipac.caltech.edu/ibe/data/spherex/qr3/level2/2026W40_1A/l2b-v27-2026-276/4/f.fits?center=1,2&size=0.1"
    assert s3_url(u).endswith("/qr3/level2/2026W40_1A/l2b-v27-2026-276/4/f.fits")


def test_rgb_render_never_invents_colour_where_a_channel_is_missing():
    import io
    from PIL import Image
    from spherex_viewer.processing.render import NAN_GREY, render
    yy, xx = np.indices((21, 21))
    r = np.hypot(xx - 10, yy - 10)
    star = 100.0 * np.exp(-r ** 2 / 20)
    red = np.where(r < 2, np.nan, star)      # blanked core, small (long wavelength)
    green = np.where(r < 5, np.nan, star)    # blanked core, larger
    blue = np.where(r < 4.5, np.nan, star)   # slightly different size -> would give fringes
    png = render([red, green, blue], [(0, 50)] * 3, "linear")
    img = np.asarray(Image.open(io.BytesIO(png)))[::-1]  # back to FITS orientation
    missing = ~(np.isfinite(red) & np.isfinite(green) & np.isfinite(blue))
    assert (img[missing] == NAN_GREY).all()            # neutral grey, no red/magenta/cyan
    assert (img[~missing][:, 0] > 0).any()             # real data still coloured


def test_spherex_hips_proxy_serves_slices_as_plain_image_hips(tmp_path, monkeypatch):
    """Slice k of the IRSA cube is re-served as an image HiPS: cube keywords and the mirror
    list are dropped (Aladin would otherwise draw it as a cube, or bypass the proxy), tiles
    map to upstream ``Npix{n}_{k}.png``, are cached on disk, and upstream 404s stay 404s."""
    import asyncio
    import dataclasses
    import httpx
    from spherex_viewer.data_access import hips, http

    props = ("creator_did          = ivo://IPAC/P/SPHEREx/DR1/cube\n"
             "obs_title            = SPHEREx DR1 all-sky data cube\n"
             "hips_service_url     = https://irsa.example/cube\n"
             "hips_service_url_1   = https://mirror.example/cube\n"
             "dataproduct_type     = cube\nhips_cube_depth      = 3\nhips_order           = 5\n"
             "data_cube_crval3_arr = 0.753 2.189 4.988\n")
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.url.path)
        if req.url.path.endswith("/properties"):
            return httpx.Response(200, text=props)
        if req.url.path.endswith("Npix7_1.png") or req.url.path.endswith("/Moc.fits"):
            return httpx.Response(200, content=b"PNGDATA")
        return httpx.Response(404)

    monkeypatch.setattr(hips, "settings", dataclasses.replace(hips.settings, cache_dir=tmp_path,
                                                              spherex_hips_url="https://up.example/cube"))
    monkeypatch.setattr(http, "_override", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(hips, "_props", None)
    monkeypatch.setattr(hips, "_missing", {})

    async def run():
        p = await hips.slice_properties(1)
        assert "hips_service_url" not in p and "hips_cube_depth" not in p and "data_cube" not in p
        assert "dataproduct_type     = image" in p and "dataproduct_type     = cube" not in p
        assert "creator_did          = ivo://IPAC/P/SPHEREx/DR1/cube/slice1" in p
        assert "(2.189 um)" in p and "hips_order           = 5" in p
        assert "hips_service_url" not in await hips.cube_properties()
        assert hips.wavelengths(await hips.cube_properties()) == [0.753, 2.189, 4.988]

        assert await hips.tile(1, "Norder5/Dir0/Npix7.png") == b"PNGDATA"
        assert seen[-1] == "/cube/Norder5/Dir0/Npix7_1.png"
        n = len(seen)
        assert await hips.tile(1, "Norder5/Dir0/Npix7.png") == b"PNGDATA"   # from disk
        assert len(seen) == n
        assert (tmp_path / "hips/spherex/s1/Norder5/Dir0/Npix7.png").exists()

        assert await hips.tile(1, "Norder5/Dir0/Npix8.png") is None
        n = len(seen)
        assert await hips.tile(1, "Norder5/Dir0/Npix8.png") is None         # 404 remembered
        assert len(seen) == n

        assert await hips.tile(2, "Moc.fits") == b"PNGDATA"
        assert seen[-1] == "/cube/Moc.fits"
        assert await hips.tile(9, "Moc.fits") == b"PNGDATA" and seen[-1] == "/cube/Moc.fits"

        # Concurrent requests for one tile share a single upstream fetch.
        (tmp_path / "hips/spherex/s1/Norder5/Dir0/Npix7.png").unlink()
        n = len(seen)
        a, b = await asyncio.gather(hips.tile(1, "Norder5/Dir0/Npix7.png"),
                                    hips.tile(1, "Norder5/Dir0/Npix7.png"))
        assert a == b == b"PNGDATA" and len(seen) == n + 1

    asyncio.run(run())


def test_spherex_hips_tile_route_rejects_paths_outside_the_tile_pattern():
    from fastapi.testclient import TestClient
    from spherex_viewer.api.app import app
    c = TestClient(app)
    for bad in ["46/..%2F..%2Fetc%2Fpasswd", "46/Norder3/Dir0/Npix1.png.exe", "999/Norder3/Dir0/Npix1.png",
                "46/index.html"]:
        assert c.get(f"/api/hips/spherex/{bad}").status_code == 404, bad


# --- one pipeline, one renderer, one HTTP session -----------------------------------------
def test_pipeline_reuses_stacks_across_difference_modes():
    """With a cache, the stacks are computed once; every diff mode / reference index reuses
    the very same arrays, and the result equals the uncached pipeline."""
    fs = [_frame(f"f{i}", [[float(i)]], [[1.0]], det=1 + i % 2, mjd=m)
          for i, m in enumerate([0, 1, 2, 180, 181, 400])]
    cache: dict = {}
    plain = build_products(fs, "epoch", Selection(), 0, 10, cache=cache)
    assert len(cache) == 1
    med = build_products(fs, "epoch", Selection(), 0, 10, diff="median", cache=cache)
    ref = build_products(fs, "epoch", Selection(), 0, 10, diff="ref", ref_index=1, cache=cache)
    assert len(cache) == 1 and build_products(fs, "epoch", Selection(), 0, 10, cache=cache)[0].sci is plain[0].sci
    assert ref[1].sci[0, 0] == 0 and med[1].sci[0, 0] == 0
    fresh = build_products(fs, "epoch", Selection(), 0, 10, diff="ref", ref_index=1)
    assert all(np.array_equal(a.sci, b.sci) and np.array_equal(a.var, b.var) for a, b in zip(ref, fresh))
    build_products(fs, "detector", Selection(), 0, cache=cache)
    assert len(cache) == 2
    with pytest.raises(ValueError):
        build_products(fs, "epoch", Selection(), 0, 10, diff="ref", ref_index=9, cache=cache)


def test_render_png_and_webp_are_lossless_and_identical():
    """Grey frames are single-channel; WebP and PNG decode to exactly the same pixels, and
    those are a neutral grey ramp (R = G = B) unless the flag overlay is on."""
    import io
    from PIL import Image
    from spherex_viewer.processing.render import NAN_GREY, limits, render
    rng = np.random.default_rng(1)
    arr = rng.normal(0.02, 0.01, (31, 31)).astype(np.float32)
    arr[:2] = np.nan
    flags = (rng.integers(0, 20, arr.shape) == 0).astype(np.int64) * 4
    lo, hi = limits([arr])
    assert limits([arr - np.nanmedian(arr)], symmetric=True)[0] < 0
    decode = lambda b: Image.open(io.BytesIO(b))
    for mode in ("linear", "asinh", "log", "sqrt"):
        png, webp = (decode(render([arr], [(lo, hi)], mode, fmt=f)) for f in ("png", "webp"))
        assert png.mode == "L"
        rgb = np.asarray(webp.convert("RGB"))
        assert np.array_equal(np.asarray(png.convert("RGB")), rgb)
        assert (rgb[..., 0] == rgb[..., 1]).all() and (rgb[..., 1] == rgb[..., 2]).all()
        assert (rgb[::-1][:2] == NAN_GREY).all()          # blank rows, flipped north-up
    over = np.asarray(decode(render([arr], [(lo, hi)], "asinh", False, flags, 4, "overlay")).convert("RGB"))
    hit = (flags[::-1] & 4) != 0
    assert (over[hit][:, 0] != over[hit][:, 1]).any() and (over[~hit][:, 0] == over[~hit][:, 1]).all()
    with pytest.raises(ValueError):
        render([arr], [(lo, hi)], "asinh", fmt="gif")


def test_cutout_is_downloaded_once_and_cache_is_checked_first(tmp_path, monkeypatch):
    """Two sessions asking for the same cutout share one download; later requests are
    served from disk without touching the network."""
    import asyncio
    import dataclasses
    import httpx
    from spherex_viewer.data_access import cutouts, http
    body = FIXTURE.read_bytes()
    calls = []

    async def handler(req: httpx.Request) -> httpx.Response:
        calls.append(str(req.url))
        await asyncio.sleep(0.02)
        return httpx.Response(200, content=body)

    cfg = dataclasses.replace(cutouts.settings, cache_dir=tmp_path, cutout_source="ibe")
    monkeypatch.setattr(cutouts, "settings", cfg)
    monkeypatch.setattr(http, "_override", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    obs = Observation(key="o1-D6", obs_id="o1", detector=6, collection="c", release="dr1",
                      url="https://irsa.example/x.fits", mjd=60000.0, t_exptime=1.0,
                      em_min_um=4.4, em_max_um=5.0, res_power=None)
    req = cutouts.CutoutRequest(obs, 133.79513, -7.24515, 0.05)

    async def run():
        a, b, c = await asyncio.gather(*[cutouts.fetch_cutout(req) for _ in range(3)])
        assert a == b == c == req.cache_path and a.exists() and len(calls) == 1
        assert await cutouts.fetch_cutout(req) == a and len(calls) == 1

    asyncio.run(run())


def test_image_route_serves_webp_and_png_but_fits_only_on_request():
    from fastapi.testclient import TestClient
    from spherex_viewer.api.app import app
    c = TestClient(app)
    for ext in ("webp", "png", "fits"):
        assert c.get(f"/api/sessions/nosuch/products/0.{ext}").status_code == 404
    r = c.get("/api/sessions/nosuch/products/0.gif")
    assert r.status_code == 404 and "format" in r.json()["detail"]


# --- astrometric fit to WISE epochs ------------------------------------------------------
from spherex_viewer.processing import astrometry as astm


def _wise_like_epochs(n_visits=22, per_visit=12, start=55300.0):
    """Visits every half year (as WISE revisits a field), a dozen exposures over a day."""
    return np.concatenate([start + 182.6 * k + np.linspace(0, 1.2, per_visit) for k in range(n_visits)])


def _simulate(ra0, dec0, pmra, pmdec, plx, mjd, sigma, rng, t0=57000.0):
    """Detections of a star with the given motion (mas/yr) and parallax (mas)."""
    tau = (mjd - t0) / 365.25
    p_xi, p_eta = astm.parallax_factors(ra0, dec0, mjd)
    xi = pmra / 1000 * tau + plx / 1000 * p_xi + rng.normal(0, sigma, len(mjd))
    eta = pmdec / 1000 * tau + plx / 1000 * p_eta + rng.normal(0, sigma, len(mjd))
    ra, dec = astm.from_tangent(xi, eta, ra0, dec0)
    return astm.Detections(mjd, ra, dec, np.full(len(mjd), sigma), np.full(len(mjd), sigma))


def test_tangent_plane_round_trip_and_orientation():
    ra, dec = astm.from_tangent([100.0, 0.0], [0.0, 100.0], 133.8, -7.2)
    assert ra[0] > 133.8 and dec[0] == pytest.approx(-7.2, abs=1e-5)       # +xi is east
    assert dec[1] == pytest.approx(-7.2 + 100 / 3600, abs=1e-7)             # +eta is north
    xi, eta = astm.to_tangent(ra, dec, 133.8, -7.2)
    assert xi == pytest.approx([100.0, 0.0], abs=1e-8) and eta == pytest.approx([0.0, 100.0], abs=1e-8)
    xi, eta = astm.to_tangent(*astm.from_tangent(-250.0, 310.0, 0.01, 88.0), 0.01, 88.0)   # near the pole
    assert (xi, eta) == (pytest.approx(-250.0, abs=1e-7), pytest.approx(310.0, abs=1e-7))


def test_parallax_factors_match_the_geometry():
    """Independent check: move the observer to the Earth and look at the star's direction."""
    ra0, dec0, plx = 133.8, -7.2, 0.5                         # arcsec
    mjd = np.array([58000.0, 58091.0, 58182.0, 58274.0])
    a, d = np.radians(ra0), np.radians(dec0)
    star = np.array([np.cos(d) * np.cos(a), np.cos(d) * np.sin(a), np.sin(d)]) * (206264.806 / plx)   # AU
    seen = star[:, None] - astm.earth_position(mjd)
    ra = np.degrees(np.arctan2(seen[1], seen[0])) % 360
    dec = np.degrees(np.arcsin(seen[2] / np.linalg.norm(seen, axis=0)))
    xi, eta = astm.to_tangent(ra, dec, ra0, dec0)
    p_xi, p_eta = astm.parallax_factors(ra0, dec0, mjd)
    assert xi == pytest.approx(plx * p_xi, abs=1e-5) and eta == pytest.approx(plx * p_eta, abs=1e-5)
    assert np.hypot(p_xi, p_eta).max() < 1.02                 # at most ~1 AU of baseline


def test_fit_recovers_motion_and_parallax_among_other_sources():
    rng = np.random.default_rng(3)
    mjd = _wise_like_epochs()
    target = _simulate(133.80, -7.24, -8100.0, 680.0, 440.0, mjd, 0.25, rng)
    # Two field stars the track passes close to: they must not be picked up.
    others = [_simulate(133.80 + dx / 3600 / np.cos(np.radians(-7.24)), -7.24 + dy / 3600, 0, 0, 0, mjd, 0.1, rng)
              for dx, dy in ((-20.0, 6.0), (30.0, -9.0))]
    det = astm.Detections(*(np.concatenate([getattr(s, k) for s in (target, *others)])
                            for k in ("mjd", "ra", "dec", "sig_ra", "sig_dec")))
    # Seed: the true position at 2015.2 (MJD 57000) with a motion good to a few per cent.
    fit = astm.match_and_fit(det, 133.80, -7.24, -8000.0, 700.0, 2014.9377)
    s = astm.summary(fit, 61500.0)
    assert s["n_visits_used"] == 22 and not s["warnings"]
    assert s["pmra"] == pytest.approx(-8100.0, abs=4 * s["pmra_err"])
    assert s["pmdec"] == pytest.approx(680.0, abs=4 * s["pmdec_err"])
    assert s["pmra_err"] < 15 and s["parallax"]["used"]
    assert s["parallax"]["mas"] == pytest.approx(440.0, abs=4 * s["parallax"]["err_mas"])
    assert 0.5 < s["chi2_red"] < 2.0


def test_fit_drops_undetected_parallax_and_predicts_a_static_star():
    rng = np.random.default_rng(5)
    det = _simulate(10.0, 45.0, 0.0, 0.0, 0.0, _wise_like_epochs(), 0.3, rng)
    fit = astm.match_and_fit(det, 10.0, 45.0)
    assert not fit.use_parallax and fit.params[4] == 0 and not fit.cov[4].any()
    p = fit.predict([61000.0])[0]
    sep = np.hypot((p["ra"] - 10.0) * np.cos(np.radians(45.0)), p["dec"] - 45.0) * 3.6e6
    assert sep < astm.K95 * p["a_mas"] * 1.5


def test_prediction_ellipse_is_calibrated_and_grows_with_time():
    """Over many simulated data sets the true future position must fall inside the 95 %
    ellipse about 95 % of the time: the ellipse is the real uncertainty, not decoration."""
    rng = np.random.default_rng(11)
    mjd = _wise_like_epochs(n_visits=14)
    truth, t_pred = (300.0, -200.0, 120.0), 61000.0
    inside, n = 0, 300
    for _ in range(n):
        det = _simulate(200.0, 20.0, *truth, mjd, 0.2, rng)
        fit = astm.match_and_fit(det, 200.0, 20.0, 280.0, -180.0, 2015.0)
        tau = (t_pred - 57000.0) / 365.25
        p_xi, p_eta = astm.parallax_factors(200.0, 20.0, t_pred)
        true = np.array([truth[0] / 1000 * tau + truth[2] / 1000 * p_xi[0],
                         truth[1] / 1000 * tau + truth[2] / 1000 * p_eta[0]])
        # compare on the sky: the fit works in its own tangent plane (about the seed position)
        p = fit.predict([t_pred])[0]
        xi, eta = astm.to_tangent(p["ra"], p["dec"], 200.0, 20.0)
        d = np.array([float(xi), float(eta)]) - true
        inside += d @ np.linalg.inv(fit.offsets_cov(t_pred)[0]) @ d <= astm.K95 ** 2
    # The visit error floor and chi-square scaling make the ellipse slightly conservative.
    assert 0.93 <= inside / n <= 1.0
    near, far = fit.predict([float(mjd[-1]), 62000.0])
    assert far["a_mas"] > near["a_mas"] and near["a_mas"] >= near["b_mas"] > 0


def test_ellipse_axes_and_position_angle():
    a, b, pa = astm.ellipse(np.array([[4.0, 0.0], [0.0, 1.0]]))     # long axis along xi = east
    assert (a, b, pa) == (pytest.approx(2.0), pytest.approx(1.0), pytest.approx(90.0))
    a, b, pa = astm.ellipse(np.array([[1.0, 0.0], [0.0, 9.0]]))     # along eta = north
    assert (a, b) == (pytest.approx(3.0), pytest.approx(1.0)) and min(pa, 180 - pa) == pytest.approx(0.0, abs=1e-6)
    _, _, pa = astm.ellipse(np.array([[2.0, 1.0], [1.0, 2.0]]))     # north-east
    assert pa == pytest.approx(45.0)


def test_fit_refuses_too_little_data_and_flags_poor_coverage():
    rng = np.random.default_rng(7)
    with pytest.raises(astm.FitError, match="no WISE"):
        astm.match_and_fit(astm.Detections(*(np.array([]) for _ in range(5))), 10.0, 10.0)
    two = _simulate(10.0, 10.0, 0, 0, 0, _wise_like_epochs(n_visits=2), 0.2, rng)
    with pytest.raises(astm.FitError, match="visit"):
        astm.match_and_fit(two, 10.0, 10.0)
    far = _simulate(10.0, 10.0, 0, 0, 0, _wise_like_epochs(), 0.2, rng)
    with pytest.raises(astm.FitError, match="within 3 arcsec"):
        astm.match_and_fit(far, 10.0, 10.0 + 20 / 3600)
    # A fast mover with no starting motion: only the epochs near the input position match.
    fast = _simulate(10.0, 10.0, 9000.0, 0.0, 0.0, _wise_like_epochs(), 0.2, rng, t0=57200.0)
    field_star = _simulate(10.0, 10.0 + 60 / 3600, 0, 0, 0, _wise_like_epochs(), 0.2, rng)
    det = astm.Detections(*(np.concatenate([getattr(s, k) for s in (fast, field_star)])
                            for k in ("mjd", "ra", "dec", "sig_ra", "sig_dec")))
    try:
        fit = astm.match_and_fit(det, 10.0, 10.0)
    except astm.FitError:
        return                                   # refusing outright is also correct
    assert any("WISE visits" in w for w in fit.warnings)


def test_visit_binning_clips_outliers_and_applies_the_error_floor():
    mjd = np.concatenate([np.full(10, 58000.0) + np.arange(10) * 0.1, [58200.0]])
    xi = np.concatenate([np.full(9, 1.0), [3.0], [2.0]])           # one stray detection
    v = astm.bin_visits(mjd, xi, np.zeros(11), np.full(11, 0.1), np.full(11, 0.1))
    assert len(v) == 2 and v[0].n == 9 and v[0].xi == pytest.approx(1.0)
    assert v[0].sig_xi == pytest.approx(np.hypot(0.1 / 3, astm.SYS_FLOOR))
    assert v[1].n == 1 and v[1].sig_xi == pytest.approx(np.hypot(0.1, astm.SYS_FLOOR))


def test_wise_motion_endpoint_fits_and_predicts(tmp_path, monkeypatch):
    """The route end to end with canned WISE detections (no network)."""
    from fastapi.testclient import TestClient
    from spherex_viewer.api import app as app_mod
    from spherex_viewer.data_access import catalogs as cat
    rng = np.random.default_rng(2)
    det = _simulate(50.0, -30.0, 1500.0, -900.0, 200.0, _wise_like_epochs(), 0.15, rng)
    asked = {}

    async def fake_exposures(ra, dec, radius):
        asked.update(ra=ra, dec=dec, radius=radius)
        return {"mjd": det.mjd, "ra": det.ra, "dec": det.dec, "sig_ra": det.sig_ra,
                "sig_dec": det.sig_dec, "counts": {"neowiser_p1bs_psd": len(det)}}, []
    monkeypatch.setattr(cat, "wise_exposures", fake_exposures)
    app_mod._fits.clear()
    c = TestClient(app_mod.app)
    body = {"ra": 50.0, "dec": -30.0, "epoch": 2014.9377, "pmra": 1400, "pmdec": -1000, "mjds": [60900.0, 61100.0]}
    r = c.post("/api/wise_motion", json=body)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["pmra"] == pytest.approx(1500, abs=25) and j["pmdec"] == pytest.approx(-900, abs=25)
    assert [p["mjd"] for p in j["predictions"]] == [60900.0, 61100.0]
    assert all(p["a_mas"] >= p["b_mas"] > 0 and 0 <= p["pa_deg"] < 180 for p in j["predictions"])
    assert len(j["curve"]["mjd"]) == len(j["curve"]["sig_xi_mas"]) and j["visits"][0]["n"] == 12
    # the cone covers the 2010-2024 track: ~1.75"/yr over 14.6 yr -> ~13" half length + margin
    assert 25 < asked["radius"] < 32
    assert c.post("/api/wise_motion", json={**body, "dec": 95}).status_code == 422
    monkeypatch.setattr(cat, "wise_exposures", lambda *a: (_ for _ in ()).throw(AssertionError("refetched")))
    assert c.post("/api/wise_motion", json={**body, "mjds": []}).json()["predictions"] == []   # cached fit


# --- mover classifier ----------------------------------------------------------------------
from spherex_viewer.processing import movers as mv


def _catwise_row(**kw):
    """A CatWISE row as IRSA returns it (strings; motions in arcsec/yr)."""
    row = {"source_name": "J000000.00+000000.0", "ra_pm": "10.0", "dec_pm": "20.0", "pmra": "0.30",
           "pmdec": "-0.40", "sigpmra": "0.05", "sigpmdec": "0.05", "w1mpro_pm": "14.2",
           "w2mpro_pm": "14.0", "w1snr_pm": "40", "w2snr_pm": "25", "rchi2_pm": "1.0",
           "rchi2": "2.0", "nb": "1", "na": "0", "cc_flags": "0000", "ab_flags": "00",
           "glat": "-40.0", "w1m": "100", "w1nm": "120", "par_pm": "0.1", "par_pmsig": "0.05"}
    row.update({k: (None if v is None else str(v)) for k, v in kw.items()})
    return row


def _stump_model(feature="pm_snr", threshold=8.0):
    """One tree: P = sigmoid(-2 + 4) above the threshold, sigmoid(-2 - 4) below."""
    return {"features": mv.FEATURES, "init": -2.0, "learning_rate": 1.0,
            "trees": [{"feature": [mv.FEATURES.index(feature), -1, -1], "threshold": [threshold, 0, 0],
                       "left": [1, -1, -1], "right": [2, -1, -1], "value": [0.0, -4.0, 4.0]}],
            "trained": "test", "n_fields": 1, "n_train": 2, "n_movers": 1, "mover_min_mas": 50.0,
            "min_pm_snr": 3.0, "min_abs_glat": 15.0, "threshold": 0.5,
            "cv": {"roc_auc": 1, "average_precision": 1, "precision": 1, "recall": 1},
            "baseline": {"roc_auc": 1, "average_precision": 1, "precision": 1, "recall": 1}}


def test_mover_features_units_and_missing_values():
    f = dict(zip(mv.FEATURES, mv.features(_catwise_row())))
    assert f["log_pm"] == pytest.approx(np.log10(500.0))            # 0.3, 0.4 arcsec/yr -> 500 mas/yr
    assert f["pm_snr"] == pytest.approx(10.0)                        # hypot(6, 8)
    assert f["rchi2_ratio"] == pytest.approx(2.0) and f["w1_detfrac"] == pytest.approx(100 / 120)
    assert f["abs_glat"] == 40.0 and f["cc_flagged"] == 0.0 and f["par_pm_snr"] == pytest.approx(2.0)
    assert f["w2k"] == mv.MISSING and f["w2_detfrac"] == mv.MISSING  # absent columns
    g = dict(zip(mv.FEATURES, mv.features(_catwise_row(cc_flags="0d00", ab_flags=None, sigpmra="0"))))
    assert g["cc_flagged"] == 1.0 and g["ab_flagged"] == mv.MISSING and g["pm_snr"] == mv.MISSING
    assert "w1mpro" in mv.FEATURES and not any("w1w2" in k or "colour" in k for k in mv.FEATURES)
    assert mv.feature_matrix([]).shape == (0, len(mv.FEATURES))


def test_mover_model_walks_trees_like_scikit_learn():
    m = mv.Model(_stump_model())
    x = mv.feature_matrix([_catwise_row(), _catwise_row(pmra="0.10", pmdec="0.0", sigpmra="0.05")])  # S/N 10 and 2
    assert m.predict(x) == pytest.approx([1 / (1 + np.exp(-2.0)), 1 / (1 + np.exp(6.0))])
    edge = np.full((1, len(mv.FEATURES)), 0.0, dtype=np.float32)
    edge[0, mv.FEATURES.index("pm_snr")] = 8.0                       # <= threshold goes left
    assert m.predict(edge)[0] == pytest.approx(1 / (1 + np.exp(6.0)))
    with pytest.raises(ValueError, match="different feature list"):
        mv.Model({**_stump_model(), "features": mv.FEATURES[:-1]})


def test_shipped_mover_model_reproduces_its_training_time_probabilities():
    """The model file carries rows scored by scikit-learn when it was trained; the numpy
    evaluator must return the same numbers."""
    mv.load_model.cache_clear()
    m = mv.load_model()
    if m is None:
        pytest.skip("mover model not built (python -m spherex_viewer.train_movers)")
    assert len(m.check) >= 10 and m.meta["n_movers"] >= 50
    got = m.predict(np.array([c["x"] for c in m.check], dtype=np.float32))
    assert got == pytest.approx([c["p"] for c in m.check], abs=1e-9)
    assert 0 <= m.meta["cv"]["precision"] <= 1 and "baseline" in m.meta


def test_gaia_match_moves_gaia_to_the_catwise_epoch():
    cw = [_catwise_row(ra_pm="10.0", dec_pm="20.0"), _catwise_row(ra_pm="10.01", dec_pm="20.0")]
    # A star 3" north of the first source in 2016.0, moving 5"/yr north: it was on the source in 2015.4.
    gaia = [{"id": "fast", "ra": 10.0, "dec": 20.0 + 3 / 3600, "pmra": 0.0, "pmdec": 5000.0, "mag": 12.0},
            {"id": "far", "ra": 10.01, "dec": 20.0 + 5 / 3600, "pmra": None, "pmdec": None, "mag": 18.0}]
    a, b = mv.gaia_match(cw, gaia, 2015.4)
    assert a["id"] == "fast" and a["sep_arcsec"] == pytest.approx(0.0, abs=1e-6) and b is None
    assert mv.gaia_match(cw, [], 2015.4) == [None, None] and mv.gaia_match([], gaia, 2015.4) == []


def test_movers_endpoint_ranks_candidates(monkeypatch):
    from fastapi.testclient import TestClient
    from spherex_viewer.api import app as app_mod
    from spherex_viewer.data_access import catalogs as cat
    rows = [_catwise_row(source_name="noise", pmra="0.10", pmdec="0.0", sigpmra="0.03"),      # S/N 3.3
            _catwise_row(source_name="mover"),                                                 # S/N 10
            _catwise_row(source_name="below-cut", pmra="0.05", pmdec="0.0")]                   # S/N 1
    asked = {}

    async def fake_candidates(ra, dec, radius):
        asked["radius"] = radius
        return rows

    async def fake_cone(name, ra, dec, radius, maglim=None):
        return {"sources": [{"id": "G1", "ra": 10.0, "dec": 20.0, "pmra": 310.0, "pmdec": -395.0, "epoch": 2016.0, "mag": 15.0}]}
    monkeypatch.setattr(cat, "mover_candidates", fake_candidates)
    monkeypatch.setattr(cat, "cone", fake_cone)
    monkeypatch.setattr(mv, "load_model", lambda: mv.Model(_stump_model()))
    c = TestClient(app_mod.app)
    j = c.get("/api/movers?ra=10&dec=20&radius=4").json()
    assert [x["id"] for x in j["candidates"]] == ["mover", "noise"] and asked["radius"] == 4
    top = j["candidates"][0]
    assert top["prob"] > 0.5 > j["candidates"][1]["prob"] and top["pm"] == pytest.approx(500.0)
    assert top["gaia"]["id"] == "G1" and top["gaia"]["pm"] == pytest.approx(np.hypot(310, 395))
    assert j["model"]["mover_min_mas"] == 50.0 and "trees" not in j["model"]
    # beyond the list limit, only sources without a Gaia star and a strong motion are kept
    ranked = mv.rank(rows, [], 2015.4, limit=0)
    assert [x["id"] for x in ranked] == ["mover"] and ranked[0]["gaia"] is None
    assert mv.rank(rows, [{"id": "G1", "ra": 10.0, "dec": 20.0, "pmra": 1.0, "pmdec": 1.0, "mag": 15.0}], 2015.4, limit=0) == []
    assert c.get("/api/movers?ra=10&dec=20&radius=40").status_code == 422
    monkeypatch.setattr(mv, "load_model", lambda: None)
    assert c.get("/api/movers?ra=10&dec=20").status_code == 503
