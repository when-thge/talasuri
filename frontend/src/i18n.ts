// Interface language: English (the source) or Filipino. Chosen on the title screen and kept
// in localStorage; changing it reloads the page.
//
// How Filipino is applied: the HTML and most runtime text is written in English, and a
// MutationObserver translates every text node and title/aria-label/placeholder/alt attribute
// that matches the dictionary below, as it appears. Keys are the English text with runs of
// whitespace collapsed; "{0}", "{1}"… in a key match any text, and the matched pieces are
// themselves translated when they are dictionary entries. Text that is assembled from
// several pieces in code is translated there with t(). <pre>, <code>, <kbd> and anything
// inside [data-noi18n] are left alone (technical readouts, keys, the language picker).
export type Lang = "en" | "fil";
const STORE = "talasuri.lang";

export const lang: Lang = (() => {
  try { return localStorage.getItem(STORE) === "fil" ? "fil" : "en"; } catch { return "en"; }
})();

export function setLang(l: Lang) {
  if (l === lang) return;
  try { localStorage.setItem(STORE, l); } catch { /* private mode: language lasts this load only */ }
  location.reload();
}

// ---------------------------------------------------------------------------------------
// English -> Filipino. Scientific names, units, catalogue names and widely used technical
// words (pixel, detector, stack, flipbook, epoch, flux) stay in English, as Filipino science
// writing usually keeps them.
const FIL: Record<string, string> = {
  // title screen and header
  "SPHEREx flipbook and sky explorer": "SPHEREx flipbook at panggalugad ng langit",
  "Talasuri · SPHEREx flipbook and sky explorer": "Talasuri · SPHEREx flipbook at panggalugad ng langit",
  "Enter": "Pumasok",
  "Talasuri home": "Home ng Talasuri",
  "Mode": "Mode",
  "Interactive Viewer": "Interaktibong Viewer",
  "Characteristics": "Mga Katangian",
  "Movement Classifier": "Classifier ng mga Gumagalaw",
  "Pick a position and watch": "Pumili ng posisyon at manood",
  "All settings and measurements": "Lahat ng setting at sukat",
  "Sources in this field that may be moving": "Mga source sa field na ito na maaaring gumagalaw",
  "Barnard's Star, M 31, or RA Dec": "Barnard's Star, M 31, o RA Dec",
  "Target name or coordinates": "Pangalan o coordinates ng target",
  "Go": "Hanapin",
  "Retry failed": "Ulitin ang pumalya",
  "Data release": "Data release",
  "All releases": "Lahat ng release",
  "Share": "Ibahagi",
  "Share or embed": "Ibahagi o i-embed",
  "Help": "Tulong",
  "Help (?)": "Tulong (?)",
  "Close": "Isara",

  // settings rail and panel
  "Settings": "Mga setting",
  "Field": "Saklaw",
  "Time": "Oras",
  "Bands": "Banda",
  "Stack": "Stack",
  "Stretch": "Liwanag",
  "Motion": "Galaw",
  "Overlays": "Overlay",
  "Reset": "I-reset",
  "Reset every setting except the target": "Ibalik sa default ang lahat ng setting maliban sa target",
  "Close settings": "Isara ang mga setting",
  "Field of view": "Saklaw ng tanaw",
  "Field size": "Laki ng saklaw",
  "Include deep-field images (many more, slower)": "Isama ang mga deep-field na larawan (mas marami, mas mabagal)",
  "Include deep-field images": "Isama ang mga deep-field na larawan",
  "1× = fit the image to the space available": "1× = ilapat ang larawan sa espasyong mayroon",
  "Magnify": "Palakihin",
  "Time and epochs": "Oras at mga epoch",
  "From": "Mula",
  "To": "Hanggang",
  "to": "hanggang",
  "Epoch window": "Saklaw ng epoch",
  "days": "araw",
  "The window groups exposures into epochs: for per-epoch stacks, and to colour the plots.":
    "Pinagsasama ng saklaw ang mga exposure sa mga epoch: para sa stack ng bawat epoch, at para kulayan ang mga plot.",
  "Frame time": "Tagal ng frame",
  "Wavelength": "Wavelength",
  "Pick detectors with the band chips at the top right of the image. Leave everything blank to use all images.":
    "Pumili ng detector gamit ang mga band chip sa kanang itaas ng larawan. Iwanang blangko ang lahat para gamitin ang lahat ng larawan.",
  "Stack and difference": "Stack at difference",
  "Quick view": "Mabilisang tanaw",
  "Every image, in time order": "Bawat larawan, ayon sa oras",
  "One stack per visit": "Isang stack bawat pagbisita",
  "Highlight movement": "Itampok ang galaw",
  "False-colour composite": "False-colour na composite",
  "Custom": "Pasadya",
  "Show": "Ipakita",
  "Every image separately": "Bawat larawan nang hiwalay",
  "One stack per epoch": "Isang stack bawat epoch",
  "One stack per detector": "Isang stack bawat detector",
  "One stack of the selected λ": "Isang stack ng napiling λ",
  "False colour from 3 detectors": "False colour mula sa 3 detector",
  "R, G, B detectors": "Mga detector para sa R, G, B",
  "Subtract": "Ibawas",
  "Nothing": "Wala",
  "Median of all": "Median ng lahat",
  "A reference image": "Isang reference na larawan",
  "Reference #": "Reference #",
  "Scale": "Iskala",
  "asinh (bright and faint)": "asinh (maliwanag at malamlam)",
  "Black level": "Antas ng itim",
  "White level": "Antas ng puti",
  "Automatic levels": "Awtomatikong antas",
  "Dark objects on white sky (untick for bright on black)": "Madilim na bagay sa puting langit (alisin ang tsek para sa maliwanag sa itim)",
  "Bad-pixel flags": "Mga flag ng sirang pixel",
  "Flagged pixels": "Mga pixel na may flag",
  "not shown": "hindi ipinapakita",
  "highlighted": "naka-highlight",
  "blanked": "binura",
  "Flags to show": "Mga flag na ipapakita",
  "Ctrl/Cmd-click to choose several. None selected = all * flags.": "Ctrl/Cmd-click para pumili ng ilan. Walang napili = lahat ng * flag.",
  "* = treated as bad in stacks and measurements.": "* = itinuturing na sira sa mga stack at sukat.",
  "Proper motion": "Proper motion",
  "Tracking keeps a moving star centred and moves the crosshair with it.":
    "Pinananatili ng pagsubaybay sa gitna ang gumagalaw na bituin, at sinasabayan ito ng crosshair.",
  "Track target's motion": "Subaybayan ang galaw ng target",
  "Epoch": "Epoch",
  "year": "taon",
  "Look up in Gaia DR3": "Hanapin sa Gaia DR3",
  "Crosshair on target": "Crosshair sa target",
  "Catalogue stars are moved to each image's date.": "Inililipat ang mga bituin ng katalogo sa petsa ng bawat larawan.",
  "Sky Sphere": "Globo ng Langit",
  "Sky": "Langit",
  "RA/Dec grid": "Grid ng RA/Dec",
  "Ecliptic": "Ekliptiko",
  "Galactic plane": "Plano ng galaksiya",
  "Imagery": "Imahe",
  "SPHEREx (follows frame λ)": "SPHEREx (sumusunod sa λ ng frame)",
  "2MASS (near-infrared)": "2MASS (malapit na infrared)",
  "DSS2 (optical)": "DSS2 (optikal)",
  "Mellinger (optical)": "Mellinger (optikal)",
  "{0} (not built)": "{0} (hindi pa nabubuo)",
  "2MASS colour (near-infrared)": "2MASS na may kulay (malapit na infrared)",
  "DSS2 colour (optical)": "DSS2 na may kulay (optikal)",
  "SPHEREx DR1 all-sky ({0} µm)": "SPHEREx DR1 buong langit ({0} µm)",
  "DR1 only": "DR1 lang",
  "QR3 only": "QR3 lang",

  // viewport
  "Viewport": "Viewport",
  "Choose a target": "Pumili ng target",
  "Frames": "Mga frame",
  "One combined image per visit": "Isang pinagsamang larawan bawat pagbisita",
  "Highlight movement (change since first visit)": "Itampok ang galaw (pagbabago mula sa unang pagbisita)",
  "Custom (set in Characteristics)": "Pasadya (itakda sa Mga Katangian)",
  "View": "Tanaw",
  "Sky Sphere (S)": "Globo ng Langit (S)",
  "Load frames here": "Kunin ang mga frame dito",
  "Dismiss picked position": "Alisin ang napiling posisyon",
  "SPHEREx image, north up, east left": "Larawan ng SPHEREx, hilaga sa itaas, silangan sa kaliwa",
  "Detector bands (none selected = all)": "Mga banda ng detector (walang napili = lahat)",
  "Detector {0}: {1} µm": "Detector {0}: {1} µm",
  "Frame": "Frame",
  "Tick colours by detector": "Kulay ng tick ayon sa detector",
  "stack": "stack",
  "flagged at target": "may flag sa target",
  "Previous (←)": "Nakaraan (←)",
  "Previous frame": "Nakaraang frame",
  "Play/pause (Space)": "I-play/i-pause (Space)",
  "Play": "I-play",
  "Pause": "I-pause",
  "Next (→)": "Susunod (→)",
  "Next frame": "Susunod na frame",
  "Toggle difference imaging (D)": "I-on/i-off ang difference imaging (D)",
  "Sky map": "Mapa ng langit",
  "Sky map shown beside the flipbook": "Mapa ng langit sa tabi ng flipbook",
  "Drag to look around. Click the sky to pick a new position.": "I-drag para lumingon. I-click ang langit para pumili ng bagong posisyon.",
  "Sphere view": "Tanaw ng globo",
  "Inside": "Loob",
  "Outside": "Labas",
  "Stand inside the sky: north up, east left": "Tumayo sa loob ng langit: hilaga sa itaas, silangan sa kaliwa",
  "See the sky as a globe from outside": "Tingnan ang langit bilang globo mula sa labas",
  "Outside view (mirrored)": "Tanaw mula sa labas (baligtad)",
  "Preset targets": "Mga nakahandang target",
  "Loading sky sphere…": "Nilo-load ang Globo ng Langit…",
  "Sky sphere. Drag or use the arrow keys to look around, scroll or +/- to zoom, click to pick a position.":
    "Globo ng Langit. I-drag o gamitin ang mga arrow key para lumingon, mag-scroll o +/- para mag-zoom, i-click para pumili ng posisyon.",
  "Sky sphere unavailable: {0}": "Hindi magamit ang Globo ng Langit: {0}",
  "Loading {0}…": "Nilo-load ang {0}…",
  "Aladin Lite unavailable": "Hindi magamit ang Aladin Lite",
  "Open in Talasuri": "Buksan sa Talasuri",
  "target": "target",
  "picked": "napili",
  "Picked {0} ({1})": "Napili {0} ({1})",

  // measurements
  "Measurements": "Mga sukat",
  "Download the photometry as CSV": "I-download ang photometry bilang CSV",
  "Close measurements": "Isara ang mga sukat",
  "6.15″ per pixel": "6.15″ bawat pixel",
  "Include flagged": "Isama ang may flag",
  "Spectrum": "Spectrum",
  "by epoch": "ayon sa epoch",
  "Light curve": "Light curve",
  "flux vs time": "flux laban sa oras",
  "all": "lahat",
  "Motion prediction": "Hula ng galaw",
  "Predict the position from WISE epochs": "Hulaan ang posisyon mula sa mga epoch ng WISE",
  "Fits position, proper motion and parallax to this object's WISE and NEOWISE detections (2010–2024) and extrapolates to the date of each SPHEREx image. On the image, the mark with four diagonal ticks is the prediction and its ellipse the 95% uncertainty, drawn to scale.":
    "Itinutugma ang posisyon, proper motion at parallax sa mga detection ng WISE at NEOWISE ng bagay na ito (2010–2024), saka hinuhulaan ang posisyon sa petsa ng bawat larawan ng SPHEREx. Sa larawan, ang markang may apat na pahilis na guhit ang hula, at ang ellipse nito ang 95% na kawalang-katiyakan, ayon sa tunay na sukat.",
  "Position minus straight-line motion. Points: WISE visits (amber, hollow: left out of the fit). Line: fitted parallax wobble. Band: ±1σ of the predicted position. Shaded: the SPHEREx images.":
    "Posisyon na binawasan ng tuwid na galaw. Mga tuldok: mga pagbisita ng WISE (amber, hungkag: hindi isinama sa fit). Linya: na-fit na pag-uga ng parallax. Banda: ±1σ ng hinulaang posisyon. May lilim: ang mga larawan ng SPHEREx.",
  "Make the fitted position and proper motion the tracked target": "Gawing sinusubaybayang target ang na-fit na posisyon at proper motion",
  "Track with this motion": "Subaybayan gamit ang galaw na ito",
  "Flags": "Mga flag",
  "Frame metadata": "Metadata ng frame",
  "All observations": "Lahat ng obserbasyon",
  "Wavelength (µm)": "Wavelength (µm)",
  "MJD (all wavelengths)": "MJD (lahat ng wavelength)",
  "Flux density (µJy)": "Flux density (µJy)",
  "All series hidden": "Nakatago ang lahat ng serye",
  "No measurements yet": "Wala pang sukat",
  "{0}: {1} measurements in {2} epochs": "{0}: {1} sukat sa {2} epoch",
  "Epoch {0} ({1})": "Epoch {0} ({1})",
  "Epoch mean": "Average ng epoch",
  "Motion fit (no fit yet)": "Fit ng galaw (wala pang fit)",

  // movers
  "Mover candidates": "Mga kandidatong gumagalaw",
  "CatWISE2020 sources in this field whose catalogued motion looks significant, ranked by a machine-learning classifier's probability that they really move (by 50 mas/yr or more). Most significant-looking motions of faint sources are artifacts; the classifier separates the two. Rings on the image mark the candidates listed.":
    "Mga source ng CatWISE2020 sa field na ito na mukhang makabuluhan ang nakatalang galaw, inihanay ayon sa probabilidad, ayon sa isang machine-learning classifier, na talagang gumagalaw sila (nang 50 mas/yr o higit pa). Karamihan sa mukhang makabuluhang galaw ng malalamlam na source ay artifact lamang; pinaghihiwalay ng classifier ang dalawa. Minamarkahan ng mga bilog sa larawan ang mga nakalistang kandidato.",
  "Probability at least": "Probabilidad na hindi bababa sa",
  "Hide stars Gaia already measures": "Itago ang mga bituing nasusukat na ng Gaia",
  "About the classifier": "Tungkol sa classifier",
  "Reading CatWISE2020 and Gaia DR3 for this field…": "Binabasa ang CatWISE2020 at Gaia DR3 para sa field na ito…",
  "Could not list candidates: {0}": "Hindi mailista ang mga kandidato: {0}",
  "Choose a target first: the candidates are listed for the field on show.": "Pumili muna ng target: inililista ang mga kandidato para sa field na ipinapakita.",
  "{0} of {1} CatWISE sources with a significant-looking motion pass the probability filter.":
    "{0} sa {1} source ng CatWISE na mukhang makabuluhan ang galaw ang pumasa sa filter ng probabilidad.",
  "{0} of {1} CatWISE sources with a significant-looking motion pass the probability filter. Lower the probability, or widen the field.":
    "{0} sa {1} source ng CatWISE na mukhang makabuluhan ang galaw ang pumasa sa filter ng probabilidad. Babaan ang probabilidad, o palakihin ang field.",
  "P(moving)": "P(gumagalaw)",
  "CatWISE2020 total proper motion, mas/yr": "Kabuuang proper motion sa CatWISE2020, mas/yr",
  "Gaia DR3 total proper motion of the counterpart, mas/yr": "Kabuuang proper motion ng katapat sa Gaia DR3, mas/yr",
  "not in Gaia": "wala sa Gaia",
  "Not in Gaia, strong CatWISE motion": "Wala sa Gaia, malakas ang galaw sa CatWISE",
  "S/N ≥ {0}, by significance": "S/N ≥ {0}, ayon sa kahalagahan",
  "Listed whatever their probability. Outside Gaia the classifier's precision cannot be measured, so check these in the flipbook and with a WISE motion fit.":
    "Nakalista anuman ang probabilidad. Sa labas ng Gaia, hindi masusukat ang katumpakan ng classifier, kaya suriin ang mga ito sa flipbook at sa WISE motion fit.",
  "Open as target, with a WISE motion fit": "Buksan bilang target, kasama ang WISE motion fit",
  // the classifier description (built from these sentences in main.ts)
  "Gradient-boosted trees on {0} CatWISE2020 sources ({1} movers) from {2} random fields at |b| ≥ {3}°, trained {4}.":
    "Gradient-boosted trees na sinanay sa {0} source ng CatWISE2020 ({1} ang gumagalaw) mula sa {2} random na field sa |b| ≥ {3}°, noong {4}.",
  "Truth: Gaia DR3 proper motion ≥ {0} mas/yr.": "Batayan ng totoo: proper motion sa Gaia DR3 na ≥ {0} mas/yr.",
  "Tested on fields held out of training: at P ≥ {0}, <b>{1}%</b> of flagged sources are real movers and <b>{2}%</b> of real movers are flagged (ranking by motion significance alone: {3}% and {4}%).":
    "Sinubok sa mga field na hindi ginamit sa pagsasanay: sa P ≥ {0}, <b>{1}%</b> ng mga na-flag na source ay tunay na gumagalaw, at <b>{2}%</b> ng mga tunay na gumagalaw ang na-flag (kung ihahanay lang ayon sa kahalagahan ng galaw: {3}% at {4}%).",
  "Plus {0} confirmed brown dwarfs from SIMBAD as movers Gaia cannot supply: held out of training, <b>{1}%</b> are flagged":
    "Dagdag pa ang {0} kumpirmadong brown dwarf mula sa SIMBAD bilang mga gumagalaw na hindi maibibigay ng Gaia: sa mga hindi ginamit sa pagsasanay, <b>{1}%</b> ang na-flag",
  " (<b>{0}%</b> of those Gaia does not see)": " (<b>{0}%</b> sa mga hindi nakikita ng Gaia)",
  "Limits: for sources <i>not in Gaia</i> there are no confirmed non-movers, so the share of flagged sources that are real is unknown there":
    "Mga hangganan: para sa mga source na <i>wala sa Gaia</i>, walang kumpirmadong hindi gumagalaw, kaya hindi alam doon kung ilan sa mga na-flag ang totoo",
  " (the model flags {0}% of such sources in random fields)": " (na-flag ng model ang {0}% ng ganitong source sa mga random na field)",
  "near the Galactic plane the model is outside its training range. Mid-infrared colour is deliberately not used.":
    "malapit sa plano ng galaksiya, lampas na ang model sa saklaw ng pagsasanay nito. Sadyang hindi ginagamit ang kulay sa mid-infrared.",

  // sheet bar, share dialog
  "Panels": "Mga panel",
  "Talasuri: help": "Talasuri: tulong",
  "Share / embed": "Ibahagi / i-embed",
  "Link to this exact view": "Link sa eksaktong tanaw na ito",
  "Compact player link (": "Link ng compact na player (",
  "Embed code": "Code para sa embed",
  "Copy": "Kopyahin",
  "Copied.": "Nakopya na.",
  "Press Ctrl/Cmd+C to copy.": "Pindutin ang Ctrl/Cmd+C para kopyahin.",

  // settings summaries and captions (assembled in main.ts)
  "{0}′ · {1}× magnification": "{0}′ · {1}× paglaki",
  "today": "ngayon",
  "{0} d epochs": "{0} araw na epoch",
  "all detectors, all λ": "lahat ng detector, lahat ng λ",
  "every image": "bawat larawan",
  "stack per epoch": "stack bawat epoch",
  "stack per detector": "stack bawat detector",
  "one wavelength stack": "isang stack ng wavelength",
  "false colour": "false colour",
  "minus median": "bawas ang median",
  "minus reference": "bawas ang reference",
  "auto levels": "awtomatikong antas",
  "manual levels": "manwal na antas",
  "dark on white": "madilim sa puti",
  "bright on black": "maliwanag sa itim",
  "flags highlighted": "naka-highlight ang mga flag",
  "flags blanked": "binura ang mga flag",
  "tracking ({0}, {1}) mas/yr": "sinusubaybayan ({0}, {1}) mas/yr",
  "not tracking": "hindi sinusubaybayan",
  "crosshair": "crosshair",
  "WISE prediction": "hula ng WISE",
  "grid": "grid",
  "ecliptic": "ekliptiko",
  "galactic": "galaksiya",
  "none": "wala",
  "off": "naka-off",
  "no fit": "walang fit",
  "fitting…": "nagfi-fit…",
  "μ {0}″/yr from {1} WISE visits": "μ {0}″/taon mula sa {1} pagbisita ng WISE",
  "Large field ({0}′): cutouts are bigger and the first load takes longer.":
    "Malaking saklaw ({0}′): mas malaki ang mga cutout at mas matagal ang unang pag-load.",
  "Every exposure in time order. Each one sees a different infrared wavelength.":
    "Bawat exposure ayon sa oras. Ibang infrared wavelength ang nakikita ng bawat isa.",
  "Images taken within the epoch window are stacked into one sharper image per visit. Best for spotting motion.":
    "Pinagpapatong ang mga larawang kinuha sa loob ng saklaw ng epoch para maging isang mas malinaw na larawan bawat pagbisita. Pinakamainam para makita ang galaw.",
  "All images from each detector stacked: six deep images from shortest to longest wavelength.":
    "Pinagpatong ang lahat ng larawan mula sa bawat detector: anim na malalim na larawan mula pinakamaikli hanggang pinakamahabang wavelength.",
  "Everything inside the selected wavelength range stacked into one deep image.":
    "Pinagpatong sa isang malalim na larawan ang lahat ng nasa loob ng napiling saklaw ng wavelength.",
  "Stacks from three detectors shown as red, green and blue.": "Mga stack mula sa tatlong detector na ipinapakita bilang pula, berde at asul.",
  "False-colour composite of {0} images": "False-colour na composite ng {0} larawan",
  "Image {0} of {1} · {2} · infrared {3} µm": "Larawan {0} sa {1} · {2} · infrared {3} µm",
  "Visit {0} of {1} · {2} · {3} images combined": "Pagbisita {0} sa {1} · {2} · {3} larawang pinagsama",
  "Combined image {0} of {1} · {2} · {3} images combined": "Pinagsamang larawan {0} sa {1} · {2} · {3} larawang pinagsama",
  "reference (shows as blank)": "reference (blangko ang lalabas)",
  "change since the reference": "pagbabago mula sa reference",
  "· ⚠ bad pixels at the target in this image": "· ⚠ may sirang pixel sa target sa larawang ito",

  // status line, stage cards, messages
  "Could not resolve: {0}": "Hindi mahanap: {0}",
  "Resolving {0}…": "Hinahanap ang {0}…",
  "moving {0}″/yr, tracking it": "gumagalaw nang {0}″/taon, sinusubaybayan",
  "Gaia DR3 {0}: moving {1}″/yr, tracking it": "Gaia DR3 {0}: gumagalaw nang {1}″/taon, sinusubaybayan",
  "Looking up Gaia DR3 proper motion…": "Hinahanap ang proper motion sa Gaia DR3…",
  "Gaia DR3 {0}: μ=({1}, {2}) mas/yr, G={3}, {4}″ from input at {5}": "Gaia DR3 {0}: μ=({1}, {2}) mas/yr, G={3}, {4}″ mula sa input sa {5}",
  "Gaia lookup failed: {0}": "Pumalya ang paghahanap sa Gaia: {0}",
  "Querying IRSA…": "Nagtatanong sa IRSA…",
  "Contacting IRSA…": "Kumokonekta sa IRSA…",
  "Looking for SPHEREx observations of this position.": "Naghahanap ng mga obserbasyon ng SPHEREx sa posisyong ito.",
  "Search failed: {0}": "Pumalya ang paghahanap: {0}",
  "Search failed": "Pumalya ang paghahanap",
  "Try again": "Subukang muli",
  "Acquiring frames {0}/{1}…": "Kinukuha ang mga frame {0}/{1}…",
  "{0} — {1} failed": "{0} — {1} ang pumalya",
  "No SPHEREx coverage here yet": "Wala pang kuha ang SPHEREx dito",
  "No target selected": "Wala pang napiling target",
  "Search for a name or coordinates above, or click the sky map beside this panel.":
    "Maghanap ng pangalan o coordinates sa itaas, o i-click ang mapa ng langit sa tabi ng panel na ito.",
  "Pick on the Sky Sphere": "Pumili sa Globo ng Langit",
  "Could not load frames": "Hindi ma-load ang mga frame",
  "No public SPHEREx image contains this position. Try another release, or another spot.":
    "Walang pampublikong larawan ng SPHEREx na sumasaklaw sa posisyong ito. Sumubok ng ibang release o ibang lugar.",
  "No frames could be loaded": "Walang frame na na-load",
  "No frames match the filters": "Walang frame na tugma sa mga filter",
  "The detector, wavelength or date filters exclude every loaded frame.":
    "Tinatanggal ng mga filter ng detector, wavelength o petsa ang lahat ng na-load na frame.",
  "Reset settings": "I-reset ang mga setting",
  "Reading cutouts from the SPHEREx archive. Frames appear as they arrive.":
    "Binabasa ang mga cutout mula sa archive ng SPHEREx. Lumalabas ang mga frame habang dumarating.",
  "Could not build products: {0}": "Hindi mabuo ang mga larawan: {0}",
  "{0} images": "{0} larawan",
  "⚠ target flagged: {0}": "⚠ may flag ang target: {0}",
  "⚠ target flagged in {0}/{1} members": "⚠ may flag ang target sa {0}/{1} na kasapi",
  "{0}/{1} flagged at target": "{0}/{1} ang may flag sa target",
  "FLAGS at the target pixel in this frame.": "Mga FLAG sa pixel ng target sa frame na ito.",
  "OR of {0} members; {1} flagged as bad at the target.": "OR ng {0} na kasapi; {1} ang may flag na sira sa target.",
  "no flags at target": "walang flag sa target",
  "{0} flag at target": "{0} flag sa target",
  "{0} flags at target": "{0} flag sa target",
  "Original at IRSA ↗": "Orihinal sa IRSA ↗",
  "Player-only link ↗": "Link ng player lang ↗",
  "Fitting the WISE epochs… (a first fit reads the WISE archive: about 10 s)":
    "Ini-fit ang mga epoch ng WISE… (binabasa ng unang fit ang archive ng WISE: mga 10 s)",
  "No prediction: {0}": "Walang hula: {0}",
  "Tracking the WISE fit: μ=({0}, {1}) mas/yr at {2}": "Sinusubaybayan ang fit ng WISE: μ=({0}, {1}) mas/yr sa {2}",
  "CatWISE {0}: tracking μ=({1}, {2}) mas/yr": "CatWISE {0}: sinusubaybayan ang μ=({1}, {2}) mas/yr",
  "{0} query failed: {1}": "Pumalya ang query sa {0}: {1}",
  "Photometry failed: {0}": "Pumalya ang photometry: {0}",
  "⚠ Target saturated in {0}/{1} frames (OVERFLOW in aperture)": "⚠ Saturated ang target sa {0}/{1} frame (OVERFLOW sa aperture)",
  "{0} fluxes withheld because the saturated core is blank": "{0} flux ang hindi ipinakita dahil blangko ang saturated na gitna",
  "Aperture fluxes of saturated stars are not reliable.": "Hindi maaasahan ang aperture flux ng mga saturated na bituin.",
  "This object is too bright for SPHEREx: the detector saturates on it, so its measured brightness isn't reliable. The images and its motion are still fine to look at.":
    "Masyadong maliwanag ang bagay na ito para sa SPHEREx: nasasaturate ang detector, kaya hindi maaasahan ang nasukat na liwanag nito. Maayos pa ring tingnan ang mga larawan at ang galaw nito.",
  "date (UTC)": "petsa (UTC)",
  "collection": "koleksiyon",
  "status": "estado",
  "target flags": "mga flag ng target",

  // messages from the server
  "Querying {0}": "Nagtatanong sa {0}",
  "Fetching {0} cutouts": "Kinukuha ang {0} cutout",
  "Loaded {0}/{1} frames": "Na-load ang {0}/{1} frame",
  "Loaded {0}/{1} frames; {2} failed": "Na-load ang {0}/{1} frame; {2} ang pumalya",
  "Paused (no one watching): {0} cutouts left": "Naka-pause (walang nanonood): {0} cutout pa ang natitira",
  "Resuming": "Itinutuloy",
  "No SPHEREx coverage at this position.": "Walang kuha ang SPHEREx sa posisyong ito.",
  "IRSA query failed: {0}": "Pumalya ang query sa IRSA: {0}",
  "The IRSA archive is not responding right now (server error at IRSA, not in this app). Try again in a few minutes. Details: {0}":
    "Hindi tumutugon ang archive ng IRSA ngayon (error sa server ng IRSA, hindi sa app na ito). Subukang muli pagkalipas ng ilang minuto. Detalye: {0}",
};

// The help dialog is long-form prose with inline markup, so it is swapped whole.
const FIL_HELP = `
    <section>
      <h3>Ano ito</h3>
      <p>Ang <b>Talasuri</b> (Tagalog na <i>tala</i>, “bituin”, + <i>suri</i>, “pag-aralan nang mabuti”) ay nag-iipon ng
        bawat larawan ng <b>SPHEREx</b> ng bahagi ng langit na pipiliin mo, inihahanay ang mga ito sa iisang grid at
        ipinapakita ayon sa oras, parang flipbook. Ang SPHEREx ay teleskopyo sa kalawakan ng NASA na nagmamapa ng buong
        langit sa infrared na liwanag (0.75–5 µm) sa 102 kulay, mga dalawang beses bawat taon. Lumilitaw ang mga bagay na
        <b>gumagalaw</b> o <b>nagbabago ng liwanag</b>; sinusukat din ng tool ang target sa bawat larawan, kaya may
        spectrum at light curve ka.</p>
    </section>
    <section>
      <h3>Mabilisang simula</h3>
      <ol>
        <li><b>Pumili ng target:</b> mag-type ng pangalan o coordinates sa search box, o buksan ang <i>Globo ng Langit</i>
          o <i>Aladin</i>, i-click ang langit at pindutin ang <i>Kunin ang mga frame dito</i>.</li>
        <li><b>Hintayin ang mga frame.</b> Sa unang pagbisita, ilang daang larawan ang binabasa mula sa archive ng NASA
          (mga isang minuto); lumalabas ang mga frame pagkalipas ng ~10 s. Ilang segundo lang ang mga susunod na pagbisita.</li>
        <li><b>Pindutin ang ▶</b>, o itakda ang <i>Mabilisang tanaw</i> sa <i>Itampok ang galaw</i>.</li>
      </ol>
      <div class="examples">
        <button type="button" data-ex="Barnard's star" data-preset="motion"><b>Barnard's Star</b><span>Ang pinakamabilis gumalaw na bituin sa langit.</span></button>
        <button type="button" data-ex="WISE 0855-0714" data-preset="motion" data-dets="5,6"><b>WISE 0855−0714</b><span>Ang pinakamalamig na kilalang brown dwarf; nakikita lang sa pinakamahahabang wavelength.</span></button>
        <button type="button" data-ex="eps Ind B" data-preset="visits"><b>ε Indi B</b><span>Isang pares ng brown dwarf, maliwanag sa infrared.</span></button>
        <button type="button" data-ex="RW Aur" data-preset="every"><b>RW Aur</b><span>Isang batang bituing nagbabago ng liwanag (nasasaturate ang SPHEREx).</span></button>
        <button type="button" data-ex="R Dra" data-preset="every"><b>R Dra</b><span>Isang Mira variable (nasasaturate ang SPHEREx).</span></button>
        <button type="button" data-ex="Orion Nebula" data-preset="colour"><b>Orion Nebula</b><span>Isang ulap na pinagsisilangan ng mga bituin, sa false colour.</span></button>
      </div>
    </section>
    <section>
      <h3>Ang tatlong tanaw</h3>
      <ul>
        <li><b>Classifier ng mga Gumagalaw</b> (kaliwang itaas): inililista ang mga source sa field na maaaring gumagalaw: mga galaw sa
          CatWISE2020 na inihanay ng isang classifier na sinanay laban sa Gaia at sa mga kilalang brown dwarf. Probabilidad
          ito, hindi tuklas: suriin sa flipbook.</li>
        <li><b>Interaktibong Viewer at Mga Katangian</b> (kaliwang itaas). Ang <i>Interaktibong Viewer</i> ay nagpapakita lang ng flipbook at mapa ng langit
          na magkatabi: pumili ng posisyon, pindutin ang play. Dagdag ng <i>Mga Katangian</i> ang Mga setting, Mga sukat, at ang
          buong laki ng Globo ng Langit at Aladin.</li>
        <li><b>Flipbook:</b> ang mga larawan. Ang linya sa ilalim ng larawan ay nagbibigay ng numero ng frame, petsa, MJD,
          detector at wavelength; nasa sulok ng larawan ang scale bar. Ang guhit sa ilalim ng larawan ay may isang tick
          bawat frame, kinulayan ayon sa detector; minamarkahan ng amber ang mga frame na may flag ang pixel ng target.
          Hilaga ang itaas, silangan ang kaliwa.</li>
        <li><b>Globo ng Langit:</b> ang buong langit para sa oryentasyon. Inilalagay ka ng <i>Loob</i> sa gitna ng
          celestial sphere (hilaga sa itaas, silangan sa kaliwa, gaya ng tunay na langit). Ipinapakita ng <i>Labas</i>
          ang langit bilang globo, na baligtad: nasa kanan ang silangan. I-drag para lumingon, mag-scroll para mag-zoom,
          i-click para pumili ng posisyon. Ang mga diamante ay mga nakahandang target.</li>
        <li><b>Aladin:</b> isang mapang nazo-zoom (CDS Aladin Lite) kasama ang na-load na field at mga overlay ng katalogo.</li>
      </ul>
    </section>
    <section>
      <h3>Pagbasa ng mga larawan</h3>
      <ul>
        <li><b>Ibang kulay ang bawat frame.</b> Nag-iiba ang mga filter ng SPHEREx sa buong detector, kaya lumiliwanag at
          lumalamlam ang mga bituin sa pagitan ng mga frame kahit walang nagbabago. Ihambing ang mga frame mula sa iisang
          detector, o gumamit ng stack.</li>
        <li><b>Galaw</b> sa difference na larawan: madilim na tuldok (kung saan ito dati) katabi ng maliwanag na tuldok
          (kung nasaan ito ngayon).</li>
        <li><b>Malalaki ang pixel</b> (6.15″): naghahalo ang magkalapit na pares, at karamihan sa mabibilis na bituin ay
          umaabot ng isang taon bago gumalaw nang isang pixel.</li>
        <li><b>Nasasaturate ang napakaliwanag na bituin:</b> blangko o mali ang gitna nila at nagbababala ang tool. Magagamit
          pa rin ang posisyon at galaw; ang liwanag, hindi.</li>
        <li><b>Hindi kinukulayan ang mga larawan.</b> Neutral na abo ang greyscale; ang tanging kulay na idinadagdag ay
          ang highlight ng sirang pixel na binubuksan mo sa <i>Liwanag</i>.</li>
      </ul>
    </section>
    <section>
      <h3>Mga setting</h3>
      <ul>
        <li><b>Saklaw ng tanaw:</b> gaano kalaking langit ang ilo-load (1–30′) at ang paglaki sa screen.</li>
        <li><b>Oras at mga epoch:</b> saklaw ng petsa, ang saklaw na nagsasama ng mga exposure sa mga epoch, tagal ng frame.</li>
        <li><b>Wavelength:</b> limitahan sa ilang detector (bawat isa ay may sariling banda) o sa isang saklaw ng wavelength.</li>
        <li><b>Stack at difference:</b> bawat larawan, stack bawat epoch o detector, isang stack ng wavelength, o false
          colour; maaaring ibawas ang median o isang reference na larawan.</li>
        <li><b>Liwanag:</b> iskala ng liwanag, antas ng itim at puti, pagbaligtad, at mga flag ng sirang pixel.</li>
        <li><b>Proper motion:</b> subaybayan ang gumagalaw na target; pinupunan ng <i>Hanapin sa Gaia DR3</i> ang mga
          halaga. Ang <i>Hula ng galaw</i> (sa Mga sukat) ay nagfi-fit sa mga epoch ng WISE ng bagay at minamarkahan kung
          nasaan ito dapat sa bawat larawan, kasama ang ellipse ng kawalang-katiyakan.</li>
        <li><b>Overlay:</b> crosshair, mga source ng Gaia at CatWISE, grid at mga plano ng globo, imahe ng Aladin.</li>
      </ul>
    </section>
    <section>
      <h3>Mga sukat</h3>
      <p>Sa bawat larawan, sinusuma ng tool ang liwanag sa isang maliit na bilog sa target at ibinabawas ang lokal na
        background at ang zodiacal na liwanag (<i>forced aperture photometry</i>, sa µJy, walang aperture correction).
        Kinukulayan ang <b>spectrum</b> ayon sa epoch (mas madilim = mas maaga); pinakamainam basahin ang
        <b>light curve</b> sa makitid na saklaw ng wavelength. Ang mga hungkag na tuldok ay tumatama sa sirang pixel.
        Nadaragdag ang liwanag ng kalapit na bituin kapag nasa loob ito ng bilog.</p>
    </section>
    <section>
      <h3>Keyboard</h3>
      <table class="keys">
        <tr><td><kbd>Space</kbd></td><td>I-play / i-pause</td></tr>
        <tr><td><kbd>←</kbd> <kbd>→</kbd></td><td>Nakaraan / susunod na frame</td></tr>
        <tr><td><kbd>D</kbd></td><td>Difference imaging on / off</td></tr>
        <tr><td><kbd>S</kbd></td><td>Globo ng Langit / balik sa flipbook</td></tr>
        <tr><td><kbd>?</kbd></td><td>Ang tulong na ito</td></tr>
        <tr><td><kbd>↑</kbd> <kbd>↓</kbd> <kbd>Enter</kbd> <kbd>Esc</kbd></td><td>Mga mungkahi sa paghahanap</td></tr>
        <tr><td>Sa globo</td><td>Lumingon gamit ang mga arrow, <kbd>+</kbd> <kbd>−</kbd> para mag-zoom, pinipili ng <kbd>Enter</kbd> ang gitna</td></tr>
      </table>
      <p class="hint">Nasa address ng page ang bawat setting, kaya ang pagkopya ng URL (o <i>Ibahagi</i>) ay eksaktong
        inuulit ang nakikita mo. Nagbibigay ang <code>?embed=1</code> ng compact na player para sa ibang page.</p>
    </section>
    <section id="creditsec">
      <h3>Datos, pagkilala at mga hangganan</h3>
      <p>Galing ang SPHEREx Spectral Images sa <a href="https://irsa.ipac.caltech.edu/Missions/spherex.html" target="_blank" rel="noopener">NASA/IPAC Infrared Science Archive (IRSA)</a>.
        Mga pangalan at posisyon: SIMBAD at Sesame (CDS). Mga mapa ng langit: Aladin Lite (CDS), ang SPHEREx DR1 all-sky map (IRSA),
        2MASS, unWISE/AllWISE at DSS. Mga katalogo: Gaia DR3 (ESA) at CatWISE2020.</p>
      <p class="hint">Ang mga opisyal na pagkilala ay nasa orihinal na Ingles:</p>
      <blockquote lang="en">This publication makes use of data products from the Spectro-Photometer for the History
        of the Universe, Epoch of Reionization and Ices Explorer (SPHEREx), which is a joint project of
        the Jet Propulsion Laboratory and the California Institute of Technology, and is funded by the
        National Aeronautics and Space Administration.</blockquote>
      <blockquote lang="en">This research has made use of the NASA/IPAC Infrared Science Archive, which is funded by
        the National Aeronautics and Space Administration and operated by the California Institute of Technology.</blockquote>
      <blockquote lang="en">This research has made use of “Aladin sky atlas” developed at CDS, Strasbourg Observatory, France,
        and of data from the European Space Agency (ESA) mission Gaia, processed by the Gaia Data Processing and
        Analysis Consortium (DPAC).</blockquote>
      <ul>
        <li>Masyadong mabilis gumalaw ang mga planeta, buwan at asteroid para masundan.</li>
        <li>Mabilisang sukat lamang ang mga sukat ng liwanag, hindi photometry na pang-publikasyon.</li>
        <li>Ang Talasuri ay independiyenteng tool, hindi opisyal na produkto ng NASA o IRSA.</li>
      </ul>
    </section>`;

// ---------------------------------------------------------------------------------------
const norm = (s: string) => s.replace(/\s+/g, " ").trim();
const reEsc = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const fill = (s: string, args: unknown[]) => s.replace(/\{(\d)\}/g, (m, i) => (i < args.length ? String(args[+i]) : m));

const exact = new Map<string, string>();
const patterns: [RegExp, string][] = [];
for (const [k, v] of Object.entries(FIL)) {
  const key = norm(k);
  if (!/\{\d\}/.test(key)) { exact.set(key, v); continue; }
  const src = key.split(/(\{\d\})/).map((p) => (/^\{\d\}$/.test(p) ? `(?<g${p[1]}>.+?)` : reEsc(p))).join("");
  patterns.push([new RegExp(`^${src}$`), v]);
}

/** Filipino for a whole (normalised) English string, or null. Pieces matched by "{n}" are
 * translated too when they are dictionary entries ("… → today · …"). */
function match(s: string, depth = 0): string | null {
  const hit = exact.get(s);
  if (hit !== undefined) return hit;
  for (const [re, v] of patterns) {
    const m = re.exec(s);
    if (!m) continue;
    return v.replace(/\{(\d)\}/g, (_, i) => {
      const part = m.groups![`g${i}`];
      return depth < 2 ? match(part, depth + 1) ?? part : part;
    });
  }
  return null;
}

/** Translate a string assembled in code: `key` is the English text with "{0}"… placeholders. */
export function t(key: string, ...args: unknown[]): string {
  if (lang === "en") return fill(key, args);
  return fill(FIL[key] ?? key, args);
}

// ---------------------------------------------------------------------------------------
const ATTRS = ["title", "aria-label", "placeholder", "alt"];
const SKIP = "pre, code, kbd, script, style, [data-noi18n]";

function translateText(node: Text) {
  const raw = node.data;
  if (!/[A-Za-z]/.test(raw)) return;
  const parent = node.parentElement;
  if (!parent || parent.closest(SKIP)) return;
  const key = norm(raw);
  const tr = match(key);
  if (tr === null || tr === key) return;
  const lead = raw.match(/^\s*/)![0], trail = raw.match(/\s*$/)![0];
  node.data = lead + tr + trail;
}

function translateAttr(el: Element, name: string) {
  const v = el.getAttribute(name);
  if (!v || !/[A-Za-z]/.test(v) || el.closest(SKIP)) return;
  const tr = match(norm(v));
  if (tr !== null && tr !== norm(v)) el.setAttribute(name, tr);
}

function walk(root: Node) {
  if (root.nodeType === Node.TEXT_NODE) { translateText(root as Text); return; }
  if (root.nodeType !== Node.ELEMENT_NODE) return;
  const el = root as Element;
  for (const a of ATTRS) if (el.hasAttribute(a)) translateAttr(el, a);
  const w = document.createTreeWalker(el, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT);
  for (let n = w.nextNode(); n; n = w.nextNode()) {
    if (n.nodeType === Node.TEXT_NODE) translateText(n as Text);
    else for (const a of ATTRS) if ((n as Element).hasAttribute(a)) translateAttr(n as Element, a);
  }
}

if (lang === "fil") {
  document.documentElement.lang = "fil";
  const help = document.getElementById("helpbody");
  if (help) help.innerHTML = FIL_HELP;
  document.title = match(norm(document.title)) ?? document.title;
  walk(document.body);
  new MutationObserver((records) => {
    for (const r of records) {
      if (r.type === "characterData") translateText(r.target as Text);
      else if (r.type === "attributes") translateAttr(r.target as Element, r.attributeName!);
      else r.addedNodes.forEach(walk);
    }
  }).observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ATTRS });
  document.documentElement.classList.remove("i18n-pending");
}

// Language picker on the title screen.
for (const b of document.querySelectorAll<HTMLButtonElement>("#langpick [data-lang]")) {
  b.setAttribute("aria-pressed", String(b.dataset.lang === lang));
  b.addEventListener("click", (e) => { e.stopPropagation(); setLang(b.dataset.lang as Lang); });
}
