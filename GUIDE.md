# Talasuri: guide to opening and using the app

Talasuri shows every NASA SPHEREx infrared image of a spot on the sky as a flipbook, so you can
watch stars move and change. This guide covers starting the app on your own computer, then
using it, from your first target to measurements.

## 1. Opening the app

Talasuri runs as a small web server on your computer; you use it in your web browser. It needs
an internet connection, because the images come live from NASA's archive.

### Option A: with Docker (easiest)

You need [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running.

1. Open a terminal in the project folder (the folder that contains `docker-compose.yml`).
2. Run:

   ```bash
   docker compose up --build
   ```

   The first build takes a few minutes. Later starts take seconds.
3. Open <http://localhost:8000> in your browser.

To stop the app, press `Ctrl+C` in the terminal. Downloaded images are kept between runs, so
places you have already visited open quickly.

### Option B: with Python and Node

You need Python 3.12 or newer and Node.js 20 or newer.

1. Open a terminal in the project folder.
2. Install everything (once):

   ```bash
   python -m venv .venv
   .venv/bin/pip install -r backend/requirements-dev.txt
   cd frontend && npm ci && npm run build && cd ..
   ```

   On Windows, use `.venv\Scripts\pip` instead of `.venv/bin/pip`.
3. Start the server:

   ```bash
   cd backend
   ../.venv/bin/uvicorn spherex_viewer.api.app:app --port 8000
   ```

4. Open <http://127.0.0.1:8000> in your browser.

To stop the app, press `Ctrl+C` in the terminal. Next time, only step 3 is needed.

## 2. The title screen

The app opens on a title screen with the Talasuri logo.

- **Choose a language:** click **English** or **Filipino** under the Enter button. The page
  reloads in that language, and your browser remembers the choice.
- **Enter the app:** click **Enter**, click anywhere, or press any key.

## 3. Finding a target

Use the search box at the top of the page. You can type:

- **A name**, such as `Barnard's Star`, `M 31` or `Orion Nebula`. Suggestions appear as you
  type; pick one with the mouse or the arrow keys and Enter.
- **Coordinates**, such as `269.452 4.693` (RA and Dec in degrees) or
  `17:57:48.5 +04:41:36`.

Then press **Go**. You can also click the sky map beside the image (or open **Sky Sphere** or
**Aladin** in the Characteristics tab), click a spot, and press **Load frames here**.

The first visit to a place takes about a minute: the app downloads a few hundred images from
NASA's archive. Frames appear after about 10 seconds and keep arriving; the status line in the
header shows the progress. Return visits take seconds.

If the star is known to move, the app turns on motion tracking by itself, so the star stays
in the centre of every frame.

**Not sure where to start?** Open **Help** (the **?** button at the top right) and click one of
the six example targets, such as Barnard's Star, the fastest-moving star in the sky.

## 4. The three tabs

The tabs at the top left change how much of the app you see.

| Tab | Use it to |
| --- | --- |
| **Interactive Viewer** | Just watch. The flipbook sits beside a sky map, with a *Show* menu and the field size. Start here. |
| **Characteristics** | See everything: settings on the left, the image in the middle, measurements on the right. |
| **Movement Classifier** | Look for moving objects. It lists sources in the field ranked by how likely they are to really move. |

## 5. Watching the flipbook

- **Play and pause:** the red ▶ button, or the Space bar.
- **Step one frame:** the ◀ and ▶ buttons, or the left and right arrow keys.
- **Jump or scrub:** click or drag along the strip of ticks under the image. Each tick is one
  frame, coloured by detector; an amber cap means the target's pixel is flagged in that frame.
- **Difference imaging:** the **Diff** button, or the D key. It subtracts a reference so that
  change stands out: a moving star shows as a dark spot (where it was) beside a bright spot
  (where it is).
- **Detector bands:** the chips **D1** to **D6** at the top right of the image. Each detector
  covers a band of infrared wavelengths, from 0.75 µm (D1) to 5 µm (D6). Click chips to show
  only those bands; with none selected, all are shown.

The line under the image gives the frame number, date, detector and wavelength. North is up and
east is left. The scale bar sits in the image's bottom corner.

**Reading the images:**

- Each frame sees a slightly different infrared colour, so stars brighten and fade between
  frames even when nothing changes. Compare frames from one detector, or use stacks.
- Pixels are large (6.15″), so motion takes months to show. Use **One stack per visit** to see
  it clearly.
- Very bright stars overload the detector. The app warns you when this happens; their
  positions are still useful, but their brightness is not.

## 6. Settings (Characteristics tab)

The column of icons on the left opens each group of settings.

| Setting | What it changes |
| --- | --- |
| **Field** | How much sky to load (1 to 30 arcminutes) and how much to magnify it. |
| **Time** | The date range, the window that groups images into visits, and the playback speed. |
| **Bands** | A wavelength range in µm (the detector chips are on the image itself). |
| **Stack** | Every image, one stack per visit or detector, a false-colour picture, and what to subtract. |
| **Stretch** | Brightness scale, black and white levels, dark-on-white or bright-on-black, and bad-pixel flags. |
| **Motion** | Track a moving star, or look its motion up in the Gaia catalogue. |
| **Overlays** | Crosshair, Gaia and CatWISE stars, the sky-map grid and planes, and the Aladin imagery. |

**Reset** at the top of the panel puts every setting back except your target.

## 7. Measurements (Characteristics tab)

The right-hand panel measures the target in every image.

- **Spectrum:** brightness against wavelength, coloured by visit (darker means earlier). Click
  the legend to hide or show a visit.
- **Light curve:** brightness against time. It reads best over a narrow wavelength range; set
  one with the λ boxes above it.
- **Motion prediction:** tick *Predict the position from WISE epochs* to fit the star's motion
  from ten years of WISE data. The image then shows where the star should be, with its 95%
  uncertainty ellipse.
- **Flags, Frame metadata, All observations:** details of each frame, a FITS download and a
  link to the original file at NASA's archive.
- **CSV** (top of the panel) downloads the measurements as a spreadsheet file.

Brightness values are quick-look measurements, not publication-grade.

## 8. Hunting for moving objects (Movement Classifier tab)

1. Load a target first; the list covers the field around it.
2. Set the **Probability at least** slider. Higher values show fewer, more certain candidates.
3. Tick **Hide stars Gaia already measures** to focus on objects the Gaia satellite cannot see,
   which is where new cold brown dwarfs would be.
4. Click a row to see its details and ring it on the image.
5. Click **Open as target, with a WISE motion fit** to check it properly: watch it in the
   flipbook and look at the motion prediction.

A high probability is a reason to look, not a discovery. The classifier was not trained near
the plane of the Milky Way, so treat results there with extra care.

## 9. Sharing what you see

Every setting is saved in the page address, so copying the URL shares exactly your view. The
**Share** button (top right) gives:

- **Link to this exact view**
- **Compact player link**, a smaller player without the panels
- **Embed code** to put the player on another web page

## 10. Keyboard shortcuts

| Key | Action |
| --- | --- |
| Space | Play / pause |
| ← → | Previous / next frame |
| D | Difference imaging on / off |
| S | Sky Sphere / back to the flipbook |
| ? | Help |
| ↑ ↓ Enter Esc | Move through and pick search suggestions |
| Arrows, + −, Enter | On the Sky Sphere: look around, zoom, pick the centre |

## 11. When something goes wrong

| What you see | What to do |
| --- | --- |
| "The IRSA archive is not responding right now" | NASA's archive is down or busy. Wait a few minutes and search again. |
| "No SPHEREx coverage here yet" | No public SPHEREx image covers that spot. Pick another target or another data release (the menu at the top right). |
| "No frames match the filters" | Your detector, wavelength or date settings exclude every frame. Click **Reset settings**. |
| "Could not resolve" a name | Check the spelling, or type the coordinates instead. |
| Some frames failed | Click **Retry failed** in the header. |
| The page does not open at all | Check that the server is still running in the terminal, and that you opened the right address (port 8000). |
