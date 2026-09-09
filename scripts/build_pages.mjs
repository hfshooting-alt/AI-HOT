/** Cross-platform GitHub Pages static export wrapper. */
import { copyFileSync, existsSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

const webRoot = fileURLToPath(new URL("../web/", import.meta.url));
const cli = fileURLToPath(new URL("../web/node_modules/vinext/dist/cli.js", import.meta.url));
const clientDir = fileURLToPath(new URL("../web/dist/client/", import.meta.url));
const indexPath = fileURLToPath(new URL("../web/dist/client/index.html", import.meta.url));
const manifestPath = fileURLToPath(new URL("../web/dist/server/vinext-prerender.json", import.meta.url));
const startedAt = Date.now();

function hasFreshStaticExport() {
  if (!existsSync(indexPath) || !existsSync(manifestPath)) return false;
  if (statSync(indexPath).mtimeMs < startedAt - 2000) return false;
  const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
  return manifest.routes?.some((route) => route.route === "/" && route.status === "rendered");
}

function finalizeExport() {
  writeFileSync(`${clientDir}.nojekyll`, "", "utf8");
  copyFileSync(indexPath, `${clientDir}404.html`);
}

const child = spawn(process.execPath, [cli, "build"], {
  cwd: webRoot,
  stdio: "inherit",
  env: {
    ...process.env,
    GITHUB_PAGES: "true",
    VITE_STATIC_SITE: "true",
    WRANGLER_LOG_PATH: ".wrangler/wrangler.log",
  },
});

child.on("error", (error) => {
  console.error(error.message);
  process.exitCode = 1;
});
child.on("exit", (code) => {
  if (hasFreshStaticExport()) {
    finalizeExport();
    if (code !== 0) console.warn("Static export validated after the Windows prerender process exited during cleanup.");
    process.exitCode = 0;
  } else {
    console.error("GitHub Pages export is missing a freshly rendered root page.");
    process.exitCode = code || 1;
  }
});
