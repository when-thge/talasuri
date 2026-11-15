// esbuild: bundles src/main.ts (+ CSS) into dist/assets and copies index.html and the
// static assets (logo, symbol, sky textures). The Sky Sphere (Three.js) and Aladin code are
// split into their own chunks, which the browser only fetches when that view opens.
import * as esbuild from "esbuild";
import { createHash } from "node:crypto";
import { cpSync, existsSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";

const watch = process.argv.includes("--watch");
const tests = process.argv.includes("--tests");
const sky = JSON.parse(readFileSync("sky.config.json", "utf8"));
// Sky layers whose texture has been built (scripts/build_sky_textures.py); others are not offered.
const define = { __SKY_AVAILABLE__: JSON.stringify(sky.layers.map((l) => l.id).filter((id) => existsSync(`assets/sky/${id}.jpg`))) };

if (tests) {
  const entries = readdirSync("tests").filter((f) => f.endsWith(".test.ts")).map((f) => `tests/${f}`);
  await esbuild.build({ entryPoints: entries, outdir: "dist-tests", bundle: true, platform: "node",
    format: "esm", outExtension: { ".js": ".mjs" }, logLevel: "warning", define });
} else {
  rmSync("dist", { recursive: true, force: true });
  mkdirSync("dist/assets", { recursive: true });
  cpSync("assets", "dist/assets", { recursive: true });
  // index.html references assets with ?v=<content hash> so browsers never pair a new page
  // with a stale cached script/stylesheet (chunks carry a hash in their file name).
  const writeIndex = () => {
    const v = (f) => createHash("sha1").update(readFileSync(`dist/assets/${f}`)).digest("hex").slice(0, 10);
    const html = readFileSync("index.html", "utf8")
      .replace('href="assets/main.css"', `href="assets/main.css?v=${v("main.css")}"`)
      .replace('src="assets/main.js"', `src="assets/main.js?v=${v("main.js")}"`);
    writeFileSync("dist/index.html", html);
  };
  const opts = { entryPoints: ["src/main.ts"], outdir: "dist/assets", bundle: true, format: "esm",
    splitting: true, chunkNames: "chunk-[name]-[hash]", minify: !watch, sourcemap: true,
    target: "es2022", logLevel: "info", define, metafile: true,
    plugins: [{ name: "index-html", setup(b) { b.onEnd((r) => { if (!r.errors.length) writeIndex(); }); } }] };
  if (watch) await (await esbuild.context(opts)).watch();
  else await esbuild.build(opts);
}
