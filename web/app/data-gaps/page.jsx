// Server component: renders FROM the authoritative docs/DATA_GAPS.md so the
// published argument can never drift from the one in the repo. Read at request
// time, same pattern as /methodology.
import fs from "node:fs";
import path from "node:path";

import MarkdownDoc from "../../components/MarkdownDoc";

export const dynamic = "force-dynamic";

// Authoritative path first (repo docs/), then a synced fallback for hosts where
// the build root is web/ (a prebuild copy into content/ — see package.json).
const CANDIDATES = [
  path.join(process.cwd(), "..", "docs", "DATA_GAPS.md"),
  path.join(process.cwd(), "content", "DATA_GAPS.md"),
];

function loadMarkdown() {
  for (const p of CANDIDATES) {
    try {
      return fs.readFileSync(p, "utf8");
    } catch {
      /* try next */
    }
  }
  return "# Data gaps\n\nDATA_GAPS.md could not be loaded on this host.";
}

export const metadata = {
  title: "Data gaps — India Electricity Data",
  description:
    "Where India's public electricity record thins out, and the measurement that would close each gap.",
};

export default function DataGapsPage() {
  const markdown = loadMarkdown();
  return (
    <main className="doc-page">
      <div className="doc-nav">
        <a href="/">← map</a>
        <a href="/methodology">methodology →</a>
      </div>
      <MarkdownDoc markdown={markdown} />
    </main>
  );
}
