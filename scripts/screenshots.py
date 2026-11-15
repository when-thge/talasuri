"""Drive the Talasuri UI headlessly (Playwright/Chromium) and save screenshots to
docs/screenshots/. The backend must be running on :8000 with a built frontend.

    python scripts/screenshots.py                       # the standard set (README)
    python scripts/screenshots.py <name> "<url hash>"   # one flipbook shot

Prints each page's browser console errors.
"""
import asyncio
import sys
from pathlib import Path

from playwright.async_api import async_playwright

BASE = "http://127.0.0.1:8000/"
OUT = Path(__file__).resolve().parents[1] / "docs" / "screenshots"
WISE = "ra=133.79513&dec=-7.24515&name=WISE%200855-0714&pm=1&pmra=-8123.7&pmdec=673.2"
FRAMES_READY = ("document.querySelector('#barfill').style.width === '100%' && "
                "/^\\d+\\/\\d+/.test(document.querySelector('#hud-frame').textContent)")
SPHERE_READY = "document.querySelector('#spherestate').hidden && /2MASS|SPHEREx|DSS/.test(document.querySelector('#spherenote').textContent)"

# name, query string, hash, viewport, what to wait for, extra JS to run before the shot
SHOTS = [
    ("talasuri_basic", "", f"{WISE}&mode=epoch&win=60&dets=5,6", (1600, 1000), FRAMES_READY, None),
    ("talasuri_flipbook", "", f"tab=adv&{WISE}&mode=epoch&win=60&dets=5,6", (1600, 1000), FRAMES_READY, None),
    ("talasuri_flipbook_diff", "", f"tab=adv&{WISE}&mode=epoch&win=60&dets=5,6&diff=ref&frame=2", (1600, 1000), FRAMES_READY, None),
    ("talasuri_sphere_inside", "", f"tab=adv&{WISE}&view=sphere&sphere=inside&secl=1&sgal=1", (1600, 1000), SPHERE_READY, None),
    ("talasuri_sphere_outside", "", f"tab=adv&{WISE}&view=sphere&sphere=outside&secl=1&sgal=1", (1600, 1000), SPHERE_READY, None),
    ("talasuri_sphere_pick", "", "tab=adv&view=sphere&pra=83.82&pdec=-5.39&slayer=spherex", (1600, 1000), SPHERE_READY, None),
    ("talasuri_aladin", "", f"tab=adv&{WISE}&view=aladin&hips=spherex", (1600, 1000), "document.querySelector('#hipsnote').textContent.length > 0", None),
    ("talasuri_embed", "?embed=1", f"{WISE}&mode=epoch&win=60&dets=5,6", (640, 720), FRAMES_READY, None),
    ("talasuri_mobile_sheet", "", f"tab=adv&{WISE}&mode=epoch&win=60&dets=5,6", (390, 844), FRAMES_READY,
     "document.querySelector('#sheetbar button').click()"),
]


async def shoot(p, name, query, hash_, size, ready, script, timeout_s=900) -> list[str]:
    errors: list[str] = []
    b = await p.chromium.launch(args=["--use-gl=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
    page = await b.new_page(viewport={"width": size[0], "height": size[1]})
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    await page.goto(f"{BASE}{query}#{hash_}")
    await page.evaluate("document.getElementById('title')?.click()")   # dismiss the title screen
    await page.wait_for_function(ready, timeout=timeout_s * 1000)
    if script:
        await page.evaluate(script)
    await page.wait_for_timeout(5000)   # images, plots, textures, map tiles, transitions
    await page.screenshot(path=str(OUT / f"{name}.png"))
    await b.close()
    return errors


async def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    shots = SHOTS
    if len(sys.argv) == 3:
        shots = [(sys.argv[1], "", sys.argv[2], (1600, 1000), FRAMES_READY, None)]
    elif len(sys.argv) == 2:
        shots = [s for s in SHOTS if sys.argv[1] in s[0]]
    async with async_playwright() as p:
        for s in shots:
            try:
                errs = await shoot(p, *s)
                print(f"{s[0]}: console errors: {errs or 'none'}")
            except Exception as e:  # noqa: BLE001 - report and continue with the next shot
                print(f"{s[0]}: FAILED {type(e).__name__}: {str(e)[:200]}")


if __name__ == "__main__":
    asyncio.run(main())
