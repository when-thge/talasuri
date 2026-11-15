# Talasuri: project description

*Tagalog* tala, "star", + suri, "to examine".

## Summary

Talasuri is a free web viewer that turns NASA's SPHEREx infrared survey into a flipbook of any
spot on the sky. Type a star's name or click the sky, and it gathers every SPHEREx exposure of
that position, lines them up on one north-up grid, and plays them in time order so that moving
and changing objects stand out.

On top of the flipbook it measures the target in every image (a spectrum and a light curve),
predicts where a moving star should be from ten years of WISE data, and ranks nearby sources by
how likely they are to be moving using a machine-learning classifier. The interface is designed
for students and citizen scientists first, and works in English and Filipino.

## The problem

SPHEREx maps the whole sky in infrared light from 0.75 to 5 µm through 102 colours, about twice
a year. The data is public at NASA/IPAC's Infrared Science Archive (IRSA), but it is hard to
look at without writing code.

- **Scattered across files.** One spot on the sky appears in hundreds of separate exposures,
  each a large FITS file with its own orientation and pixel grid.
- **Every frame is a different colour.** SPHEREx's filters change across the detector, so a
  star brightens and fades between frames even when nothing about it changes. Comparing frames
  naively is misleading.
- **Big pixels.** At 6.15″ per pixel, motion of a nearby star takes months to show, so it only
  becomes visible when many epochs are lined up and compared.
- **No WiseView for SPHEREx.** Citizen-science projects such as Backyard Worlds found many cold
  brown dwarfs by blinking WISE images in WiseView. Nothing like it existed for SPHEREx.

## What Talasuri does

The app has three tabs, so a first-time visitor sees only a flipbook while a researcher can open
every control.

| Tab | Who it is for | What it shows |
| --- | --- | --- |
| Interactive Viewer (default) | Learners, first visits | The flipbook beside a sky map, a *Show* preset and the field size. Pick a position, press play. |
| Characteristics | Citizen scientists, researchers | The full console: settings on the left, the image in the centre, measurements on the right. |
| Movement Classifier | Anyone hunting for moving objects | CatWISE2020 sources in the field ranked by the probability that they really move, ringed on the image. |

Core features:

- **Find a target three ways:** a name (with suggestions from SIMBAD), typed coordinates, or a
  click on the 3D Sky Sphere or on Aladin Lite.
- **Flipbook:** every exposure on one north-up grid, with a timeline of one tick per frame
  coloured by detector, a scale bar, a crosshair and RA/Dec ticks around the image like a
  printed star atlas.
- **Stacks and differences:** one stack per visit, per detector or per wavelength range;
  false-colour composites; subtraction of the median or a reference image, so motion shows as a
  dark spot beside a bright one.
- **Band chips:** filter the six SPHEREx detectors from the top right of the image.
- **Proper-motion tracking:** a search turns on tracking automatically using the catalogue
  motion or Gaia DR3, so a fast star stays centred.
- **Measurements:** a forced-photometry spectrum and light curve for the target, flag readouts,
  frame metadata, FITS downloads and links to the originals at IRSA.
- **WISE motion prediction:** fits position, proper motion and parallax to the object's
  2010–2024 WISE and NEOWISE detections and draws the predicted position with its 95% error
  ellipse on each SPHEREx image.
- **Share and embed:** every setting lives in the page address, so a link reproduces exactly
  what you see, and `?embed=1` gives a compact player for other web pages.

## How it works

A search opens a session on the server, which finds every SPHEREx exposure of the position and
streams processed frames to the browser as they land, so the first frames show in about 10
seconds.

1. **Find the data.** The server queries IRSA's image search (SIA) for every SPHEREx release
   covering the position and removes duplicates between releases.
2. **Fetch only what is needed.** Cutouts are built from byte ranges of IRSA's public S3 copy
   of the archive: just the rows covering the field, in all planes (image, variance, zodiacal
   light, flags). Any image S3 cannot serve falls back to IRSA's cutout service. A first load
   runs at 5–7 frames per second, against about 0.4–0.75 through the cutout service; repeat
   visits load from cache in seconds.
3. **Process each frame.** A thread pool reads the wavelength at the target from the spectral
   WCS, measures forced aperture photometry on the native pixels, and reprojects the cutout
   onto one north-up 6.15″ grid centred on the target.
4. **Build products on request.** Stacks, difference images, the WISE motion fit and the mover
   classifier run when the viewer asks for them, and results are cached per parameter set.

**Tech stack:** Python 3.12, FastAPI, NumPy and Astropy on the server; TypeScript, HTML canvas,
Three.js (the Sky Sphere) and Aladin Lite v3 in the browser, bundled with esbuild. The
classifier is trained with scikit-learn and shipped as plain JSON trees evaluated with NumPy.
It runs locally or in Docker, with 81 backend and 25 frontend automated tests plus live
acceptance checks against the archives.

## Science and accuracy

The images are never tinted or altered for display: photometry and FITS downloads use the
original pixels, and every limit is stated in the app.

**Motion prediction is a physical model, not machine learning.** For one object's motion the
model is known, so weighted least squares gives error bars that mean what they say. A unit test
checks that the true position falls inside the 95% ellipse in about 95% of simulated data sets.
Live checks against SIMBAD's published motions (Nov 2026):

| Object | Fitted μ (mas/yr) | Published μ (mas/yr) | Fitted parallax (mas) | Published (mas) |
| --- | --- | --- | --- | --- |
| WISE 0855−0714 | −8132.9 ± 9.1, +681.7 ± 10.4 | −8123.7, +673.2 | 491 ± 37 | 439 |
| Barnard's Star (saturated) | −787.6 ± 14.3, +10375.2 ± 10.7 | −801.6, +10362.4 | 458 ± 56 | 547 |
| ε Indi B (close binary) | +3990.1 ± 3.5, −2514.0 ± 3.4 | +3982.0, −2466.8 | 269 ± 13 | 275 |

**The Movement Classifier is where machine learning earns its place.** CatWISE2020 fits a
motion to every source, and most significant-looking motions of faint sources are blends or
artifacts. Gradient-boosted trees learn which are real from CatWISE's own quality columns, with
Gaia DR3 as the truth. Training used 162,029 Gaia-labelled sources (7,858 movers) from 150
random fields, plus 1,707 entries of 1,589 confirmed brown dwarfs from SIMBAD. With whole fields
held out (5-fold cross-validation):

| Method | Precision at P ≥ 0.5 | Recall | ROC AUC |
| --- | --- | --- | --- |
| Talasuri classifier | 84% | 65% | 0.973 |
| Ranking by CatWISE motion S/N alone | 62% | 48% | 0.875 |

Held-out brown dwarfs are flagged 93% of the time (89% of the 860 with no Gaia star). WISE
0855−0714, the coldest known brown dwarf, scores P = 0.98.

**Honest limits, also shown in the app:**

- For sources with no Gaia star, precision cannot be measured, so a high probability is a
  reason to look, not a discovery.
- The classifier was trained at Galactic latitude |b| ≥ 15°; in the Galactic plane it is
  outside its training range.
- Brightness values are quick-look forced photometry, not publication-grade. Very bright stars
  saturate SPHEREx, and the app warns when they do.
- Planets, moons and asteroids move too fast to follow.

## Design and accessibility

The interface is styled as a printed star-atlas plate read under a red night-vision torch: deep
chart navy, chalk-white text, hairline rules, and one red reserved for actions, the current
selection and the target.

- **Atlas plate frame.** A double neat-line with RA/Dec ticks surrounds the image, the target's
  name is set like a chart label, and a red ring closes onto the target when its first frame
  lands (skipped for people who prefer reduced motion).
- **Science first.** Overlays are drawn on a separate layer, so the science pixels are never
  tinted; the only colour added to an image is the bad-pixel highlight you turn on.
- **English and Filipino.** A language switch on the title screen translates the whole
  interface, including the Help guide, status messages and chart labels. Scientific terms and
  catalogue names stay in English, as Filipino science writing usually keeps them.
- **Phones and tablets.** On a phone the settings and measurements become bottom sheets and the
  image stays square.
- **Keyboard and screen readers.** Space plays and pauses, the arrow keys step frames, D
  toggles difference imaging, S opens the Sky Sphere and ? opens Help. Controls carry labels
  for screen readers, and keyboard focus is always visible.

## Who it is for and impact

Talasuri is built for two audiences at once: the public and students meeting infrared astronomy
for the first time, and citizen scientists who want real measurements.

- **Learners** start with six worked examples in Help, from Barnard's Star, the fastest-moving
  star in the sky, to the Orion Nebula in false colour, and see motion and variability with one
  press of play.
- **Citizen scientists** get the tools of a WiseView-style search for SPHEREx: blinking,
  difference images, motion tracking, WISE fits and a ranked candidate list, with every number
  traceable to the archive.
- **Filipino speakers** can use the whole tool in their own language. That puts NASA mission
  data in front of students in the Philippines who are more comfortable reading Filipino.
- **Teachers and writers** can share a link that reproduces an exact view, or embed the compact
  player on a class page or article.

## Data, credits and next steps

All data comes from public archives, queried live:

- **SPHEREx Spectral Images:** [NASA/IPAC Infrared Science Archive (IRSA)](https://irsa.ipac.caltech.edu/Missions/spherex.html),
  read from IRSA's public S3 copy with the IRSA cutout service as a fallback.
- **Names and positions:** SIMBAD and Sesame (CDS, Strasbourg).
- **Catalogues:** Gaia DR3 (ESA) and CatWISE2020; WISE and NEOWISE single-exposure detections
  (IRSA).
- **Sky maps:** Aladin Lite (CDS), the SPHEREx DR1 all-sky map (IRSA), 2MASS, unWISE/AllWISE
  and DSS.

The SPHEREx, IRSA, Aladin and Gaia acknowledgements are reproduced in full in the app's Help.
Talasuri is an independent tool, not an official NASA or IRSA product.

Next steps:

- Have a native speaker review the Filipino translation.
- Measure the classifier's precision for sources Gaia cannot see, which needs confirmed
  non-movers outside Gaia.
- Add new SPHEREx data releases as IRSA publishes them (the release list is discovered from
  IRSA automatically).
