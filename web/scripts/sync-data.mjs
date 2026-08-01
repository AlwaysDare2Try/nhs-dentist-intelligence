// Copies the pipeline's published contract (analysis/build.py, schema v1) into
// the web app's static assets. The app reads these files and nothing else.
import { mkdirSync, copyFileSync, existsSync, statSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const src = join(here, "..", "..", "data", "dist", "site", "v1");
const dest = join(here, "..", "public", "data");

if (!existsSync(src)) {
  console.error(`No built data at ${src}\nRun:  uv run python analysis/build.py`);
  process.exit(1);
}
mkdirSync(dest, { recursive: true });
for (const f of ["practices.json", "meta.json", "changes.json"]) {
  const from = join(src, f);
  if (!existsSync(from)) { console.error(`missing ${f}`); process.exit(1); }
  copyFileSync(from, join(dest, f));
  console.log(`  ${f}  ${(statSync(from).size / 1e6).toFixed(2)} MB`);
}
