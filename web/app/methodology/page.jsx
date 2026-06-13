// Server component: renders the page FROM the authoritative docs/METHODOLOGY.md
// so it can never drift from the real calculation. Read at request time.
import fs from "node:fs";
import path from "node:path";

import MarkdownDoc from "../../components/MarkdownDoc";
import AccuracyLive from "../../components/AccuracyLive";

export const dynamic = "force-dynamic";

// Authoritative path first (repo docs/), then a synced fallback for hosts where
// the build root is web/ (a prebuild copy into content/ — see package.json).
const CANDIDATES = [
  path.join(process.cwd(), "..", "docs", "METHODOLOGY.md"),
  path.join(process.cwd(), "content", "METHODOLOGY.md"),
];

function loadMarkdown() {
  for (const p of CANDIDATES) {
    try {
      return fs.readFileSync(p, "utf8");
    } catch {
      /* try next */
    }
  }
  return "# Methodology\n\nMETHODOLOGY.md could not be loaded on this host.";
}

export const metadata = {
  title: "Methodology — India Electricity Data",
};

export default function MethodologyPage() {
  const markdown = loadMarkdown();
  return (
    <main className="doc-page">
      <div className="doc-nav">
        <a href="/">← map</a>
        <a href="/status">data quality →</a>
      </div>
      <MarkdownDoc markdown={markdown} />
      <AccuracyLive />
    </main>
  );
}
