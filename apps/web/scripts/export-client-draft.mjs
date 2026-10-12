import { createRequire } from "node:module";
import { readFile, writeFile, mkdir, readdir } from "node:fs/promises";
import { dirname, resolve, relative, extname, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { Script } from "node:vm";
import postcss from "postcss";
import tailwind from "@tailwindcss/postcss";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
// Reuse the compiler already locked and installed by the project's Vitest/Vite
// toolchain. No unpinned npx download or additional build dependency is needed.
const require = createRequire(import.meta.url);
const viteRequire = createRequire(createRequire(require.resolve("vitest/package.json")).resolve("vite/package.json"));
const { build } = viteRequire("esbuild");
const adapters = {
  "next/link": "navigation.tsx", "next/navigation": "navigation.tsx",
  "next/image": "image.tsx", "next/dynamic": "dynamic.tsx",
  "nuqs/adapters/next/app": "navigation.tsx",
  "@/lib/api/server": "api.ts", "@/lib/api/client": "api.ts",
  "@/lib/site": "site.ts",
};
const result = await build({
  absWorkingDir: root, entryPoints: ["client-draft/entry.tsx"], bundle: true,
  platform: "browser", format: "iife", target: "es2022", jsx: "automatic",
  write: false, minify: true, metafile: true, sourcemap: false,
  define: {
    // Deliberately do not load .env files or inherit deployment/account data.
    "process.env": JSON.stringify({ NODE_ENV: "production", NEXT_PUBLIC_ENV: "production" }),
  },
  plugins: [{ name: "offline-public-adapters", setup(builder) {
    builder.onResolve({ filter: /^(next\/|nuqs\/adapters\/next\/app$|@\/lib\/(api\/(server|client)|site)$)|calculator-hero-art$/ }, args => {
      if (args.path.endsWith("/calculator-hero-art")) return { path: resolve(root, "client-draft/calculator-art.tsx") };
      if (adapters[args.path]) return { path: resolve(root, "client-draft", adapters[args.path]) };
      return undefined;
    });
  } }],
});
const code = result.outputFiles[0].text;
const inputs = Object.keys(result.metafile.inputs);
if (inputs.some(path => /lib\/api\/(server|client)\.ts$|app\/\(app\)|app\/\(auth\)/.test(path.replaceAll("\\", "/")))) {
  throw new Error("Private routes or a live API client entered the offline export.");
}

async function filesIn(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const groups = await Promise.all(entries.map(entry => entry.isDirectory() ? filesIn(resolve(directory, entry.name)) : [resolve(directory, entry.name)]));
  return groups.flat();
}
const mime = { ".png": "image/png", ".webp": "image/webp", ".svg": "image/svg+xml", ".woff2": "font/woff2" };
const assets = {};
const publicDirectory = resolve(root, "public");
for (const file of await filesIn(publicDirectory)) {
  if (!mime[extname(file)]) continue;
  const path = `/${relative(publicDirectory, file).split(sep).join("/")}`;
  if (!code.includes(path) && !path.startsWith("/illustrations/calculators/") && path !== "/brand/icon-32.png") continue;
  assets[path] = `data:${mime[extname(file)]};base64,${(await readFile(file)).toString("base64")}`;
}

const cssSource = await readFile(resolve(root, "app/globals.css"), "utf8");
let { css } = await postcss([tailwind({ base: root, optimize: true })]).process(cssSource, { from: resolve(root, "app/globals.css") });
const font = (await readFile(resolve(root, "brand/space-grotesk-latin.woff2"))).toString("base64");
css += `\n@font-face{font-family:"Space Grotesk";font-style:normal;font-weight:300 700;font-display:swap;src:url(data:font/woff2;base64,${font}) format("woff2")}\n:root{--font-heading:"Space Grotesk",sans-serif;--font-geist:"Space Grotesk",sans-serif}html{scroll-behavior:auto}body{margin:0}#main-content:focus{outline:none}`;
// Reuse the exact Geist faces from an existing Next build when available.
const nextStatic = resolve(root, ".next/static");
let geistFaces = [];
try {
  for (const file of (await filesIn(nextStatic)).filter(path => path.endsWith(".css"))) {
    const compiled = await readFile(file, "utf8");
    for (const face of compiled.match(/@font-face\s*\{[^}]*\}/g) ?? []) {
      if (!/font-family:\s*['"]?Geist['"]?\s*;/.test(face)) continue;
      let embedded = face;
      for (const match of face.matchAll(/url\(['"]?([^)'"\s]+)['"]?\)/g)) {
        const name = match[1].split("/").pop();
        if (!name.endsWith(".woff2")) continue;
        const bytes = await readFile(resolve(nextStatic, "media", name));
        embedded = embedded.replace(match[0], `url(data:font/woff2;base64,${bytes.toString("base64")})`);
      }
      geistFaces.push(embedded);
    }
  }
} catch (error) { if (error.code !== "ENOENT") throw error; }
geistFaces = [...new Set(geistFaces)];
if (geistFaces.length) css += `\n${geistFaces.join("\n")}\n:root{--font-geist:Geist,"Space Grotesk",sans-serif}`;
// Fail closed if CSS acquired an external or unembedded resource.
if (/url\(\s*['"]?(?!data:|#)/i.test(css)) throw new Error("Unembedded CSS resource in draft.");

const escapeScript = value => value.replace(/<\/script/gi, "<\\/script");
// Compile without executing to catch serialization errors before delivery.
new Script(escapeScript(code));
const html = `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow"><meta name="referrer" content="no-referrer"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; font-src data:; connect-src data:; media-src data: blob:; form-action 'none'; base-uri 'none'; object-src 'none'"><title>Dhanadhara | Client draft</title><style>${css.replace(/<\/style/gi, "<\\/style")}</style></head><body class="antialiased min-h-screen bg-background text-text-primary"><noscript>This interactive client draft needs JavaScript enabled. No server or internet connection is required.</noscript><div id="draft-root"></div><script>window.__DRAFT_ASSETS__=${escapeScript(JSON.stringify(assets))};${escapeScript(code)}</script></body></html>`;
const output = resolve(root, "../../build/client-draft");
const fontLicenses = [await readFile(resolve(root, "brand/OFL.txt"), "utf8"), ...(geistFaces.length ? [await readFile(resolve(root, "client-draft/GEIST-OFL.txt"), "utf8")] : [])].join("\n\n");
const licensedHtml = html.replace("</head>", `<link rel="icon" href="${assets["/brand/icon-32.png"]}"></head>`).replace("</body>", `<script type="text/plain" id="font-licenses">${escapeScript(fontLicenses)}</script></body>`);
await mkdir(output, { recursive: true });
await writeFile(resolve(output, "Dhanadhara-Client-Draft.html"), licensedHtml);
await writeFile(resolve(output, "export-report.json"), JSON.stringify({ bytes: Buffer.byteLength(licensedHtml), embeddedAssets: Object.keys(assets).length, geistEmbedded: geistFaces.length > 0, liveApiIncluded: false, inputs }, null, 2));
console.log(`Client draft: ${resolve(output, "Dhanadhara-Client-Draft.html")} (${(Buffer.byteLength(licensedHtml) / 1024 / 1024).toFixed(1)} MiB, ${Object.keys(assets).length} embedded assets)`);
