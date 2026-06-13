// Copies the authoritative docs/METHODOLOGY.md into web/content/ so the
// methodology route can render it on hosts whose build root is web/ (e.g.
// Vercel) where ../docs isn't present at runtime. Runs on predev/prebuild.
// The page still prefers ../docs at request time when available, so dev never
// drifts; this copy is only the deploy fallback.
import { copyFileSync, mkdirSync, existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const web = dirname(dirname(fileURLToPath(import.meta.url)));
const src = join(web, "..", "docs", "METHODOLOGY.md");
const dstDir = join(web, "content");
const dst = join(dstDir, "METHODOLOGY.md");

if (existsSync(src)) {
  mkdirSync(dstDir, { recursive: true });
  copyFileSync(src, dst);
  console.log("synced METHODOLOGY.md → content/");
} else {
  console.log("docs/METHODOLOGY.md not found; using committed content/ copy");
}
