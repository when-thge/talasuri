# Refactor notes (2026-11-14)

One pass that (1) merged duplicated logic and removed dead weight, (2) redesigned the
interface as **Talasuri**, and (3) added the Sky Sphere view. This file covers part 1 and
lists every behaviour change. The tests and the five-target live checks were run before and
after; results are at the end.

## What the audit found

The code was already fairly tight, so this was mostly consolidation, not deletion.

| Finding | Where | Action |
|---|---|---|
| Six separate HTTP clients (cutouts, SIA, HiPS, catalogs, SIMBAD, TAP, Sesame), most created and closed per call | `data_access/*` | one shared session, `data_access/http.py` |
| Two sessions asking for the same cutout at the same time both downloaded it | `cutouts.py` | in-flight requests are shared; the disk cache is still checked first |
| `ProductQuery` class + `product_query()` wrapper + `_query_kwargs()` + `_PQ_KEYS`: four pieces parsing the same query string | `api/app.py` | one `ProductQuery(request)` |
| `auto_limits` / `symmetric_limits`, `render_grey` / `render_rgb` / `to_png`: parallel functions | `processing/render.py` | `limits(symmetric=)`, `render()`, `encode()` |
| Reprojection, stacking and differencing in three modules, glued together in the API layer | `processing/` | `processing/pipeline.py`, one `build_products(mode=, diff=)` |
| Switching the diff mode or reference recomputed every stack | `api/app.py` | stacks cached per selection and reused by all diff modes |
| The FITS download built its product on the event loop (blocked other requests) | `api/app.py` | runs in the worker pool |
| Coordinates parsed in `resolver.py` (astropy) and formatted in three places, with two different sexagesimal formatters | backend + `main.ts` | `coords.py` and its twin `coords.ts` |
| URL state spread over `DEFAULTS`, `SCHEMA`, `CORE_KEYS`, `ALIASES` and a special case in `fromHash`; `location.hash` touched in `main.ts` | `state.ts`, `main.ts` | one `SCHEMA` object + `hashStore` |
| Chart.js (most of the 206 kB bundle) for two scatter plots | `plots.ts` | native canvas plots |
| Aladin Lite fetched at page load even when its tab was never opened | `aladin.ts`, `main.ts` | loaded when the Aladin tab first opens |
| The aperture radii were built twice (JSON and CSV URLs) | `api.ts` | `photParams()` |
| `_fetchers = None` reset hack so the CLI checks could start a new event loop | `checks.py`, `sessions.py` | client and limits are bound to the running loop |
| Dead code: `_iso()` wrapper, unused `rec` local, function-local imports to dodge an import cycle that did not exist, guide pager (`showGuide`), tab/slot juggling (`applyTab`), `fmtSexa`, `rec_url` cast | various | removed |
| Dead CSS: the whole old stylesheet (tab layouts, guide pager, accordion, short-screen overrides) | `style.css` | deleted; replaced by `theme.css` + `app.css` |

No unused Python dependency was found: `requirements.txt` is unchanged (astropy, numpy,
scipy, fastapi, uvicorn, httpx, pillow are all imported).

## What was merged

- **Coordinates.** `backend/spherex_viewer/coords.py` (parse, range check, sexagesimal and
  decimal formatting) and `frontend/src/coords.ts`, written as line-for-line twins. One
  module per language is the smallest number possible; they are held together by
  `shared/coords_cases.json` (56 parse cases, 41 format cases), which both test suites run.
  The API's session validator and the search box now apply the same range rule. The
  frontend parses coordinates itself, so typing RA/Dec no longer needs a `/api/resolve`
  round trip.
- **URL hash state.** `SCHEMA` in `frontend/src/state.ts` is the single definition of every
  parameter: name, default, encode, decode, whether it is always written, and its aliases.
  `ViewState`, `DEFAULTS`, `toHash` and `fromHash` are derived from it. `hashStore` is the
  only code that reads or writes `location.hash` (and `?embed=1`).
- **Stretch and colour.** `render.render()` draws single frames, stacks, difference images
  and the RGB composite; `render.limits()` gives their display limits. There is one
  `stretch()`.
- **Reproject, stack, diff.** `processing/pipeline.py`. Frames are reprojected once, when
  their cutout arrives (unchanged). `build_products(frames, mode, …, diff, ref_index,
  cache)` does grouping, stacking and differencing; with the session's cache, stacks are
  computed once per selection and every diff mode reuses those arrays.
- **HTTP.** `data_access/http.py`: one `httpx.AsyncClient` for everything outbound. Cutouts
  were already fetched concurrently (128 S3 range requests, 8 IBE requests); those limits
  are unchanged.

## What was removed

| Removed | Replaced by |
|---|---|
| `processing/reprojection.py`, `stacking.py`, `differencing.py` | `processing/pipeline.py` |
| `chart.js` (npm dependency) | canvas code in `plots.ts` (144 → 262 lines) |
| `frontend/src/style.css` | `theme.css` (design tokens) + `app.css` (layout) |
| `Fetchers` dataclass, `sessions._shared()`, `sessions._fetchers` | `cutouts.limits()`, `http.client()` |
| astropy `Angle`/`SkyCoord` use for parsing and formatting coordinates | `coords.py` |
| About tab and the paged guide | Help dialog (Basic and Advanced tabs are kept) |

Added dependencies: `three` (runtime, lazy chunk) and `@types/three` (dev).

## Size before and after

Lines of code (`wc -l`):

| | Before | After | Note |
|---|---|---|---|
| Backend Python (`spherex_viewer/`) | 3494 | 3616 | +`coords.py`, `http.py`, in-flight dedupe, WebP |
| Frontend TypeScript (`src/`) | 1782 | 2689 | +493 for the sphere (`sphere.ts`, `sphere-math.ts`), +89 `coords.ts`, +118 native plots, HUD, timeline, states |
| CSS | 219 | 353 | full design system |
| `index.html` | 395 | 388 | |
| Tests (Python + TS) | 685 | 1017 | 59 → 66 backend tests, 5 → 19 frontend tests |
| Build script: `scripts/build_sky_textures.py` | 0 | 166 | |

Total code went **up**, not down: parts 2 and 3 are new features. The consolidation itself
is visible in `api/app.py` (521 → 502 lines while gaining WebP and validation) and in the
three deleted processing modules.

Bundle (minified; gzip in brackets):

| File | Before | After | Loaded |
|---|---|---|---|
| `main.js` | 206.5 kB (73.2 kB) | **47.8 kB (18.2 kB)** | always |
| `main.css` | 11.3 kB (3.2 kB) | 17.7 kB (4.8 kB) | always |
| Aladin wrapper chunk | (inside main.js) | 4.9 kB (2.2 kB) | when the Aladin tab opens |
| Sky Sphere chunk (Three.js) | none | 486.4 kB (123.6 kB) | when the Sky Sphere tab opens |
| shared chunk (`coords`, sky config) | none | 2.7 kB (1.5 kB) | always |

Initial JavaScript is 77 % smaller (73.2 → 19.7 kB gzipped). Aladin Lite itself (from
jsDelivr) is now also deferred until its tab opens.

Frame images, same pixels (a 49×49 frame, asinh):

| Format | Bytes | Encode time |
|---|---|---|
| Before: PNG, 3 identical channels | 2761 | 0.20 ms |
| After: PNG, 1 channel (`.png`) | 1689 | 0.09 ms |
| After: lossless WebP (`.webp`, what the UI requests) | 1488 | 0.24 ms |

FITS is only built by the explicit `.fits` download, as before.

## Behaviour changes

The goal was none. The science path has none. The full list of anything observable:

**Pixels and numbers: unchanged, verified.**
- 100 renders (4 stretches × invert × 3 flag modes × 2 images, plus RGB, in PNG and WebP)
  were compared against the old renderer: decoded pixels are identical. Display limits are
  identical. A permanent test checks PNG = WebP and R = G = B for grey frames.
- The five-target live checks give the same numbers before and after (see below).
- `format_sexagesimal` matches astropy's output on 307 positions (and a permanent test
  compares 200 random positions against astropy).

**Deliberate differences, all at the edges:**
1. Frame images are served as `.webp` (lossless) or single-channel `.png`. The old
   `.png` URL still works and decodes to the same pixels; only the encoding changed.
2. Coordinate parsing is stricter on five malformed inputs. `24:00:00 +10:00:00` was
   accepted through a floating-point accident (as RA 359.99999999999994°) and
   `25:00:00 +10:00:00` fell through to the name resolver; both are now reported as out of
   range. `10m +5m` and `10s +5s` were read as minutes/seconds of arc and `10: +5:` was
   not; all three are now "not coordinates". Everything else in the shared case file
   behaves as before, including the odd-but-valid forms (`10h30 +5d30`, `1d +5h`).
3. An RA that rounds up to 24h/360° now prints as `00:00:00.00` / `0.00000` instead of
   `24:00:00.00` / `360.00000` (which could not be parsed back).
4. `POST /api/sessions` reports an out-of-range position through the shared range check;
   it is still a 422.
5. A cutout wanted by two sessions at once is downloaded once (it was twice).
6. Typing coordinates in the search box no longer calls `/api/resolve`.

**Interface (part 2), by design:** the Basic and Advanced tabs are kept (`tab=basic|adv`,
Basic by default): Basic shows the flipbook beside the sky map (`map=sphere|aladin`),
Advanced the full console. The About tab became the Help dialog; `tab=about` in old links
opens Basic. All other parameters still work. The one-line
frame label became the corner readouts. The compass moved from the image canvas to a
readout. The flagged-target crosshair is amber instead of red. Keys **D**, **S** and **?**
are new.

### Later changes to defaults and display (after the refactor)

- **Default view** is `mode=epoch` with `win=60` (was `mode=frames`, `win=14`) and
  `inv=1` (dark on white). `win` and `inv` are now always written to the URL. Old links
  that carried no `win` or `inv` open with the new values.
- **Automatic levels** (`render.limits`): on sparse fields the black point is the sky
  median + 1σ (was the 1st percentile); difference images use ±max(99th percentile of
  |value|, 8σ). Fields filled with extended emission keep the 1st percentile.
- **Difference images** (`pipeline.subtract`) have their own median removed, and are drawn
  with a stretch that is symmetric about the middle of the range (`stretch(bipolar=True)`;
  asinh there uses a softening of 1.0). Before, a non-linear stretch put zero far from
  mid-grey. Difference FITS files include the median removal.
- **Search** turns proper-motion tracking on from Gaia DR3 when the resolver gives no
  motion (at least 50 mas/yr).
- **Sky Sphere** loads HiPS tiles when zoomed in (`healpix.ts`).

## Verification

Run before the first edit and again after the last:

| Check | Before | After |
|---|---|---|
| `pytest` (offline) | 59 passed | 66 passed |
| `npm test` | 5 passed | 19 passed |
| `tsc --noEmit` | clean | clean |
| Live checks: `python -m spherex_viewer.checks` | 6/6 pass | 6/6 pass |

Live checks, warm cache (frames loaded / alignment RMS px / spectrum points measured):

| Target | Before | After | Time |
|---|---|---|---|
| WISE 0855−0714 | 258 / 0.4941 / 258 | 258 / 0.4941 / 258 | 7.2 s → 2.6 s |
| Barnard's Star | 358 / 0.2038 / 222 | 358 / 0.2038 / 222 | 8.5 s → 3.6 s |
| ε Indi B | 458 / 0.4067 / 458 | 458 / 0.4067 / 458 | 9.0 s → 4.5 s |
| RW Aur | 335 / 0.3132 / 334 | 335 / 0.3132 / 334 | 6.7 s → 3.3 s |
| R Dra | 539 / 0.4626 / 31 | 539 / 0.4626 / 31 | 9.9 s → 5.3 s |
| ε Indi A+B (15′) | 458 / 0.3596 / 458 | 458 / 0.3596 / 458 | 5.2 s → 5.3 s |

The full result files are identical field for field for five targets; for WISE 0855 one
number differs in its 16th digit (alignment RMS 0.49409583432176885 vs …896), which is
summation order: frames are measured in arrival order. The timings are single runs on a
warm cache and include name resolution, so treat the speed-up as indicative only.

Test edits: `tests/test_units.py` needed import changes only (new module paths,
`render_rgb` → `render`, the HiPS test's mock client hook), plus seven new tests.

## Not done / trade-offs

- **DSS2 texture not built.** CDS (hips2fits and its HiPS tiles) returned 404 "Page
  unavailable" all day, and no IRSA mirror of DSS2 colour exists. The layer stays in
  `sky.config.json` and shows as "(not built)"; `scripts/build_sky_textures.py dss`
  builds it once CDS is back.
- **Textures come from HiPS `Norder3/Allsky`, not hips2fits**, for the same reason: the
  script tries hips2fits first and fell back. The mosaics hold 64 px per order-3 tile
  (about 0.11° per pixel), so the 4096×2048 textures are slightly oversampled and soft. They
  are only the whole-sky view: zoomed in, the sphere loads the survey's HiPS tiles (up to
  order 9 for 2MASS, order 5 for SPHEREx), which needs IRSA at run time. With IRSA down the
  sphere falls back to the static image and reports "detail tiles unavailable".
- **Fonts load from Google Fonts** (Orbitron, Inter, JetBrains Mono) with system fallbacks.
  Self-hosting them would remove the last third-party request at page load.
- **Three.js is 124 kB gzipped** even tree-shaken. It is isolated in the sphere chunk.
- **Docker build still untested** here (no access to the Docker socket). The Dockerfile
  needs no change: `npm run build` copies `frontend/assets/` into `dist/`.
- **Aladin's CDS console errors remain** (a CDS logger hostname that does not resolve),
  as recorded in TESTING.md.
- **Old screenshots** from the previous interface (`docs/screenshots/ui_*`, `guide_*`,
  `fit_*`, `search_*`, `embed_mode.png`) have since been deleted.
- The Python package is still named `spherex_viewer` and the env prefix is still `SPX_`;
  renaming them would break existing deployments and caches for no user-visible gain.
