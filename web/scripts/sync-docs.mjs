// Copies the authoritative docs/*.md into web/content/ so the
// methodology route can render it on hosts whose build root is web/ (e.g.
// Vercel) where ../docs isn't present at runtime. Runs on predev/prebuild.
// The page still prefers ../docs at request time when available, so dev never
// drifts; this copy is only the deploy fallback.
import { copyFileSync, mkdirSync, existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const web = dirname(dirname(fileURLToPath(import.meta.url)));
const dstDir = join(web, "content");

// Every doc rendered by a route must be listed here, or that route falls back
// to the committed copy in content/ and silently serves a stale version.
const DOCS = ["METHODOLOGY.md", "DATA_GAPS.md"];

mkdirSync(dstDir, { recursive: true });
for (const name of DOCS) {
  const src = join(web, "..", "docs", name);
  if (existsSync(src)) {
    copyFileSync(src, join(dstDir, name));
    console.log(`synced ${name} → content/`);
  } else {
    console.log(`docs/${name} not found; using committed content/ copy`);
  }
}
