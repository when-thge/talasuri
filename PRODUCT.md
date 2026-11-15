# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Two audiences, served by one interface (confirmed 2026-11-15):

- **Public and learners:** curious people and students who want to see a real infrared space
  telescope's pictures of a famous object and watch something in the sky move or change.
- **Citizen scientists:** people hunting brown dwarfs and other nearby movers, or watching
  variable stars, who blink SPHEREx frames, read spectra and light curves, and check mover
  candidates.

The interface must strike a balance: approachable on first contact, with the science depth
one step away rather than in the way.

## Product Purpose

Talasuri (Tagalog *tala*, "star", + *suri*, "to examine") gathers every NASA SPHEREx infrared
image of a chosen spot on the sky, reprojects them onto one north-up grid and plays them as a
flipbook. Things that move or change brightness stand out. It can also stack, difference,
and measure the target, giving a spectrum and a light curve. Success: a visitor picks a
target and sees it move or change within a minute, and a citizen scientist can verify a
candidate without leaving the tool.

## Positioning

A WiseView-style flipbook for SPHEREx specifically: 102 infrared colours, twice a year, across
the whole sky, combined with a whole-sky sphere for orientation, forced photometry, a
WISE-epoch motion fit with drawn-to-scale uncertainty, and a classifier that ranks CatWISE
mover candidates.

## Operating Context

- Desktop browser is the main workspace; phones get a single-column layout with bottom sheets.
- First visits read a few hundred images from NASA's IRSA archive (about a minute); frames
  appear after ~10 s. Loading progress is part of the experience.
- Every setting lives in the URL; links and `?embed=1` compact players are shared and embedded.

## Capabilities and Constraints

- Modes today: Basic (flipbook + sky map), Advanced (all controls and measurements), Movers.
- Views: Flipbook, Sky Sphere (Three.js, inside/outside), Aladin Lite.
- Stack (vanilla TypeScript + CSS bundled with esbuild, served by a FastAPI backend). No UI
  framework.
- Science images are rendered by the backend as a neutral grey ramp; the frontend displays
  them as delivered.
- The user did not require keeping every control as-is: decluttering may consolidate or move
  controls, as long as the science capabilities stay reachable.

## Brand Commitments

- Name: Talasuri. Wordmark `frontend/assets/logo.svg` and symbol `frontend/assets/symbol.svg`
  are kept (file slots; replaced by swapping the file).
- The full-screen title screen on open is kept.
- The visual style around them is open to replacement (user chose a new, sleeker style).

## Evidence on Hand

- Real data: SPHEREx Spectral Images (IRSA), Gaia DR3, CatWISE2020, WISE/NEOWISE, SIMBAD.
- Measured classifier and motion-fit results in README.md. No testimonials or usage numbers
  exist; do not invent them.
- Required data credits and acknowledgement text (index.html help dialog) must remain.

## Product Principles

1. The sky leads: the image is the hero, chrome recedes.
2. One step to depth: the first screen works for a newcomer; everything a citizen scientist
   needs is one deliberate action away.
3. Honest science: never tint, flatter or overclaim; state limits plainly.
4. Shareable state: whatever you see can be linked and reproduced.

## Accessibility & Inclusion

Text contrast at WCAG AA, full keyboard operation (existing shortcuts), reduced-motion support.
