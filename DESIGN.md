---
name: Talasuri
description: SPHEREx infrared flipbook and sky viewer, set as a printed star-atlas plate read under a red night-vision torch.
colors:
  ink-0: "#0a1220"
  ink-1: "#0d1626"
  ink-2: "#111d31"
  ink-3: "#17253d"
  ink-4: "#22314a"
  ink-5: "#3a4b66"
  stage: "#000000"
  text: "#e9eef5"
  text-2: "#a9b6c9"
  text-3: "#8a98ae"
  red: "#ff5a4e"
  red-strong: "#ff7468"
  red-ink: "#1a0c0a"
  red-wash: "rgba(255, 90, 78, .14)"
  amber: "#f2b544"
  danger: "#ff8a80"
  series-0: "#4f79b8"
  series-1: "#8fb3e8"
  series-2: "#e9eef5"
typography:
  plate:
    fontFamily: "Source Serif 4, Georgia, Times New Roman, serif"
    fontSize: "2.5rem"
    fontWeight: 500
    lineHeight: 1
    letterSpacing: "-0.015em"
  headline:
    fontFamily: "Public Sans, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "1rem"
    fontWeight: 600
    lineHeight: 1.45
  title:
    fontFamily: "Public Sans, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 500
    lineHeight: 1.45
  body:
    fontFamily: "Public Sans, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: 1.45
  hint:
    fontFamily: "Public Sans, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "0.8125rem"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "Public Sans, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 500
    lineHeight: 1.45
  figure:
    fontFamily: "JetBrains Mono, ui-monospace, SF Mono, Menlo, Consolas, monospace"
    fontSize: "0.75rem"
    fontWeight: 400
    lineHeight: 1.35
    fontFeature: "tnum"
rounded:
  chip: "4px"
  sm: "6px"
  md: "8px"
  dialog: "12px"
  sheet: "14px"
  pill: "999px"
spacing:
  header: "56px"
  rail: "64px"
  settings: "272px"
  measurements: "336px"
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "20px"
  xxl: "28px"
components:
  button:
    backgroundColor: "{colors.ink-2}"
    textColor: "{colors.text}"
    typography: "{typography.title}"
    rounded: "{rounded.sm}"
    padding: "6px 12px"
  button-hover:
    backgroundColor: "{colors.ink-3}"
  button-primary:
    backgroundColor: "{colors.red}"
    textColor: "{colors.red-ink}"
    rounded: "{rounded.sm}"
    padding: "6px 12px"
  button-primary-hover:
    backgroundColor: "{colors.red-strong}"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.text-2}"
    rounded: "{rounded.sm}"
  button-icon:
    backgroundColor: "{colors.ink-2}"
    textColor: "{colors.text}"
    rounded: "{rounded.sm}"
    size: "34px"
  button-toggled:
    backgroundColor: "{colors.red-wash}"
    textColor: "{colors.text}"
  input:
    backgroundColor: "{colors.ink-1}"
    textColor: "{colors.text}"
    rounded: "{rounded.sm}"
    padding: "5px 8px"
  search:
    backgroundColor: "{colors.ink-2}"
    textColor: "{colors.text}"
    typography: "{typography.figure}"
    rounded: "{rounded.md}"
    height: "36px"
  segmented:
    backgroundColor: "{colors.ink-2}"
    textColor: "{colors.text-2}"
    rounded: "{rounded.md}"
    padding: "3px"
  segmented-selected:
    backgroundColor: "{colors.ink-3}"
    textColor: "{colors.text}"
    rounded: "{rounded.sm}"
  chip:
    backgroundColor: "transparent"
    textColor: "{colors.text-2}"
    typography: "{typography.figure}"
    rounded: "{rounded.chip}"
    padding: "1px 7px"
  badge-flag:
    backgroundColor: "rgba(13, 22, 38, .85)"
    textColor: "{colors.amber}"
    typography: "{typography.label}"
    rounded: "{rounded.pill}"
    padding: "2px 9px"
  readout:
    textColor: "{colors.text-2}"
    typography: "{typography.figure}"
  plot-well:
    backgroundColor: "{colors.ink-0}"
    rounded: "{rounded.sm}"
    height: "220px"
  dialog:
    backgroundColor: "{colors.ink-2}"
    textColor: "{colors.text}"
    rounded: "{rounded.dialog}"
---

# Design System: Talasuri

## Overview

**Creative North Star: "The Star-Atlas Plate"**

The interface is a printed star-atlas plate read under a red night-vision torch. The sky image owns the screen; everything else is quiet chart furniture: a chart-navy ground in one fixed tonal ramp, chalk text, 1px hairline rules, and a single night-vision red that marks only what you can act on, the current selection, and the target. The target is labelled the way an atlas labels a plate: its name in an italic serif, its coordinates in tabular mono beneath.

Density is working-instrument density. Panels are flat and separated from the ground by hairlines, never boxed or carded; settings sit behind a labelled icon rail, measurements in one right-hand column, and the only scrolling regions are the side panels. Type is small and sentence case throughout, with numbers always in tabular mono so columns of coordinates and fluxes align.

Science images are shown exactly as the backend renders them: neutral grey ramp, no tint, no filter, no blend mode, on a plain black stage. The system styles the furniture around the pixels and never the pixels. It rejects the category default of a glowing neon HUD console with boxed panels on every side.

**Key Characteristics:**
- One tonal ramp of chart navy (ink-0 to ink-5) carries every surface, rule and hover.
- One accent, night-vision red, reserved for primary actions, the current selection and the target ring.
- Amber means a flag or warning and nothing else.
- Italic serif for object names only; Public Sans for the interface; JetBrains Mono tabular figures for every number.
- Hairlines, not boxes; flat panels, shadows only on things that float.
- Untinted science imagery on a black stage.

## Colors

A cold, low-chroma chart navy ramp with chalk text, one warm red for action, and amber for flags.

### Primary
- **Night-Vision Red** (red): the only accent. Primary buttons (play, Go, the first action in a state card or mover detail), toggled-on buttons (outlined in red over the red wash), checkbox and range accents, the focus ring, the pick bar outline, the selected mover row wash, the mobile sheet-tab indicator, and the target ring drawn on the flipbook, sphere and Aladin maps. Hover lifts it to **Torch Red** (red-strong); text on it is **Ember Black** (red-ink).
- **Red Wash** (red-wash): the 14% red fill behind a pressed toggle, the pick bar and the selected candidate row.

### Neutral
- **Plot Well** (ink-0): the deepest navy, behind plots and under the scale readout.
- **Chart Navy** (ink-1): the page ground, header, rail, viewport and inputs.
- **Panel Navy** (ink-2): side panels, dialogs, buttons at rest, segmented-control trays.
- **Raised Navy** (ink-3): hover, selected rail item, selected segment.
- **Hairline** (ink-4): every 1px rule, control border, table row divider.
- **Strong Rule** (ink-5): control borders on hover, plot axes, scrollbar thumbs, link underlines.
- **Black Stage** (stage): behind science images only.
- **Chalk** (text), **Chalk Dim** (text-2), **Chalk Faint** (text-3): primary text, secondary text and labels, tertiary metadata and placeholders. All three clear 4.5:1 on Panel Navy.

### Semantic
- **Flag Amber** (amber): flagged frames, warning messages, the flags summary, the flagged badge, the amber cap on timeline ticks, and the target ring when the target pixel is flagged.
- **Error Coral** (danger): error rows in the observation table.

### Data
- **Epoch Blues** (series-0, series-1, series-2): the ordinal plot ramp, earliest epoch deepest, latest epoch in chalk. Plots extend it with a fixed 8-step blue ramp from #3f69a8 to #e9eef5 when more series are needed; the motion model line and its confidence band use the same blues.
- **Detector spectrum**: a wavelength-ordered key used only for interface marks (timeline ticks, the detector checklist), never applied to images: D1 #a78bfa, D2 #60a5fa, D3 #4de3ff, D4 #5eead4, D5 #ffb547, D6 #ff7a59; a mixed stack is #9fb0d0.
- **Overlay marks on the sky**: Gaia sources #86b6ef, CatWISE sources #ffb547, the galactic plane and the predicted-position ellipse #b79cff, the ecliptic in amber. Each has a deeper variant for inverted (white) skies, where the target ring becomes #d92d20 and a flagged ring #b25e00.

### Named Rules
**The Torch Rule.** Red marks only what you can act on, the current selection and the target. Never use it for decoration, headings, status or data series.

**The One Ramp Rule.** Every surface, rule and hover state is a step on the ink ramp. A new surface picks an existing step; it does not mix a new navy.

**The Untinted Sky Rule.** Nothing in the system touches science-image pixels: no tint, filter, blend mode or colour overlay. Marks are drawn on top as thin strokes; readouts sit in one corner.

## Typography

**Display Font:** Source Serif 4, italic 500 (with Georgia)
**Body Font:** Public Sans 400/500/600 (with system-ui)
**Label/Mono Font:** JetBrains Mono 400/500 (with ui-monospace), tabular figures

**Character:** An atlas engraver's italic for the names of things, a plain public-service sans for the interface, and an instrument mono for every measurement.

### Hierarchy
- **Plate** (Source Serif 4 italic 500, 2rem, 1.05, -0.01em): the target name on the atlas-plate label; drops to 2rem under 900px. The title screen sets the product name in the same face at clamp(40px, 9vw, 72px). Example-target names in Help use it at 1rem.
- **Headline** (Public Sans 600, 1rem): panel and dialog headings, state-card heads.
- **Title** (Public Sans 500 to 600, 0.875rem): section summaries, plot titles, buttons.
- **Body** (Public Sans 400, 0.875rem, 1.45): the default; Help body runs at 1.6 line height in two 340px-min columns.
- **Hint** (Public Sans 400, 0.8125rem, 1.5): explanatory hints, option rows, segmented controls.
- **Label** (Public Sans 500, 0.75rem): sub-section labels, badges, captions, status messages; rail labels drop to 11px.
- **Figure** (JetBrains Mono, 0.75rem, tabular): coordinates, readouts, section summaries, chips, the search field, numeric and date inputs; tables at 11.5px.

### Named Rules
**The Named-Object Rule.** The italic serif is for the names of celestial objects (and the product name on the title screen). It never sets interface labels, headings or numbers.

**The Tabular Figures Rule.** Every coordinate, date, flux and count is set in the mono with tabular numerals.

**The Sentence-Case Rule.** Interface text is sentence case at normal tracking. Labels are not uppercased or letterspaced, and nothing is labelled twice.

## Layout

Desktop is a fixed-height workspace with no page scroll: a 56px header (wordmark, Basic/Advanced/Movers text tabs with a 2px chalk underline on the selected tab, centred search up to 520px, release select, icon tools, and a 2px progress line along its bottom edge), then a grid. Advanced mode is a 64px labelled icon rail, a 272px settings column (always open; the rail picks its section), the fluid viewport, and a 336px measurements column, so the two sides balance at 336px each; Basic is the viewport alone (flipbook and sky map side by side, 28px apart on one grid so their frames and foot bars align); Movers is the viewport plus a 440px candidate list. Only the side panels scroll.

The viewport pads 18px 28px 16px. Its head is the atlas-plate label at left and the view switch at right, 14px above the stage; beneath the stage sit a 16px tick strip, the scrubber, and the player bar (transport, Diff, one caption line), 12px apart.

At 1280px and below the measurements column narrows to 296px, the settings column to 232px, the movers list to 380px, and viewport padding to 16px 20px. At 900px and below everything stacks in one column: the header wraps (search, then tabs, then status), the rail disappears, the stage becomes square, and the settings and measurements panels become bottom sheets opened from a 52px tab bar fixed to the bottom.

Spacing runs on a 4px base with 8, 12, 16, 20 and 28px as the working steps; panel interiors pad 16px 20px, collapsible section rows 11px vertically.

## Elevation & Depth

Flat by default. Panels sit level with the ground and are separated from it by 1px Hairline rules and one step of the ink ramp, never by shadow. Depth appears only on layers that genuinely float above the workspace, as a large, soft, pure-black shadow; overlays on the stage use a translucent chart-navy fill instead.

### Shadow Vocabulary
- **Dialog lift** (`box-shadow: 0 24px 64px rgba(0, 0, 0, .55)`): modal dialogs, over a `rgba(5, 9, 17, .72)` backdrop.
- **Dropdown lift** (`box-shadow: 0 16px 40px rgba(0, 0, 0, .5)`): the search suggestion list.
- **Sheet lift** (`box-shadow: 0 -16px 40px rgba(0, 0, 0, .45)`): mobile bottom sheets.

### Named Rules
**The Hairline Rule.** Structure is drawn with 1px Hairline rules. Panels are not boxed, carded or shadowed; if it does not float, it has no shadow.

## Shapes

Gently rounded and small. Controls and wells take 6px; trays, the search field, the pick bar and floating menus take 8px; chips, readouts and keycaps take 4px; dialogs 12px and mobile sheets 14px on their top corners. The flag badge is the only pill. Rules are always 1px; the only 2px strokes are the selected-tab underline, the progress line, the mobile sheet-tab indicator and the focus ring. The target ring, a thin circle with four crosshair arms that stop short of the target, is the recurring geometric mark.

## Components

### Buttons
Quiet instrument keys; only the action that moves the story forward is red.
- **Shape:** gently rounded (6px), 1px Hairline border.
- **Default:** Panel Navy fill, chalk text, Public Sans 500, padding 6px 12px.
- **Hover / Active / Focus:** hover steps to Raised Navy with a Strong Rule border; active steps to Hairline; focus shows a 2px red outline offset 2px. Transitions run 150ms on border, background and colour.
- **Primary:** red fill and border, Ember Black text at 600, hover to Torch Red. Used once per context (play, Go, the first action in a group).
- **Ghost:** transparent, Chalk Dim text; hover gains the Raised Navy fill.
- **Icon:** 34px square (36px wide in the transport), inline SVG icon centred.
- **Toggled (aria-pressed):** Red Wash fill, red border, chalk text.
- **Disabled:** 40% opacity.

### Chips
- **Style:** mono 0.75rem, transparent, 1px Hairline border, 4px radius, Chalk Dim text. A bad-state chip turns amber in text and border.
- **Flag badge:** amber text and border in a pill over translucent chart navy.

### Cards / Containers
- **Panels:** flat Panel Navy or Chart Navy, separated by hairlines; padding 16px 20px.
- **Plot wells:** Plot Well fill, 6px radius, 220px tall.
- **Collapsible sections:** rows divided by a top hairline, title at 500, a mono summary of the current value right-aligned in Chalk Faint (amber when it reports a flag), and a thin chalk chevron that rotates on open.
- **State card:** centred over the stage on Chart Navy, a 1rem head, 46ch body, red first action.

### Inputs / Fields
- **Style:** Chart Navy fill, 1px Hairline border, 6px radius, padding 5px 8px; numbers and dates in mono. Checkboxes and ranges use the red accent.
- **Focus:** hover takes the Strong Rule border; focus shows the red focus ring. The search combo's border shifts to Chalk Faint while focused.

### Navigation
- **Header tabs:** text only, Chalk Dim at 500, selected tab in chalk with a 2px chalk underline sitting on the header rule.
- **Settings rail:** 52px icon-over-label buttons in Chalk Faint, 11px labels; hover chalk on Panel Navy, open item on Raised Navy.
- **View switch / segmented:** an 8px Panel Navy tray with a 3px inset; the selected segment fills Raised Navy.
- **Mobile:** a 52px bottom tab bar opens bottom sheets; the open tab carries a 2px red inset top line.

### Atlas-Plate Label (signature)
The target's name in the Plate style (2.5rem; 2rem under 900px), with a catalogue line beneath: label/value pairs (RA, Dec, μ, Field, Frames) with labels in Chalk Faint 0.75rem and values in mono Chalk. Only known facts appear; phones keep RA, Dec and Field. A 1px hairline under the whole view header closes the plate. When the target changes, the name sets in once (700ms opacity, 6px rise and blur release on the system ease; off under reduced motion). It pairs with the red target ring, the same mark on the flipbook, the Sky Sphere and Aladin, so the label and the ring always name the same thing.

### Plate Frame (signature)
Every sky view (flipbook stage, Sky Sphere, Aladin) carries a chart neat-line: a 1px Strong Rule, a 4px gap of ground, and a fainter 1px outer rule. Inside the flipbook stage, an overlay canvas draws a second double neat-line around the image itself, 6px out, with RA ticks along the top and bottom and Dec ticks along both sides at about one per 70–90px; RA labels run along the top, Dec labels up the left edge, the first of each in full (8h55m05s, −7°16′) and the rest abbreviated. The frame is drawn outside the image and never on its pixels.

### Acquire Moment
The interface's one authored motion: when a new target's first frame lands, a red ring closes from wide onto the target over about 600ms (exponential ease-out) and fades in the next 300ms, drawn on the frame overlay. Skipped under reduced motion.

### Stage Readout
Scale bar and N/E orientation sit as one mono line in the plate frame's bottom margin, bottom-right, with no plate behind them, like a chart's scale line. They never cover the image.

### Timeline
A 16px strip of ticks, one per frame, coloured by detector; the current frame is marked in white, flagged frames carry an amber cap. The strip is the scrubber: press and drag across it to move between frames. A visually hidden range input keeps keyboard and screen-reader access; there is no filled progress track.

### Band Chips
One chip per detector (D1–D6, with its tick colour as a dot) in a small Plot Well tray at the top right of the flipbook plate frame. Selected chips fill Raised Navy with a full-strength dot; none selected means all bands. Hidden until a target exists; still shown when no frame matches, so a filter can be undone.

## Do's and Don'ts

### Do:
- **Do** keep red to primary actions, the current selection and the target ring (The Torch Rule).
- **Do** take every surface and rule from the ink ramp, ink-0 to ink-5.
- **Do** show science images untinted on the black stage, with marks drawn on top as 1.5px strokes.
- **Do** set object names in Source Serif 4 italic and every number in JetBrains Mono tabular figures.
- **Do** separate panels with 1px Hairline rules and keep them flat.
- **Do** use amber only for flags and warnings.
- **Do** honour reduced motion: dialogs stop rising and transitions drop to zero.

### Don't:
- **Don't** tint, filter, blend or recolour science-image pixels.
- **Don't** build a glowing neon HUD: no glows, no boxed or carded panels on every side.
- **Don't** use red for decoration, headings, status or a data series.
- **Don't** put shadows on anything that does not float above the workspace.
- **Don't** uppercase or letterspace interface labels, or label the same thing twice.
- **Don't** use the serif italic for interface text.
