"use client";

import { useEffect, useState } from "react";
import AccuracyTable from "./AccuracyTable";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// Live CI-accuracy results for the methodology /#accuracy section. The
// explanatory text is rendered from METHODOLOGY.md; these numbers are data.
export default function AccuracyLive() {
  const [ci, setCi] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    fetch(`${API}/v1/status`, { cache: "no-store" })
      .then((r) => r.json())
      .then((d) => setCi(d.ci_accuracy))
      .catch((e) => setErr(String(e)));
  }, []);

  if (err) return <p className="sub">Live accuracy results unavailable ({err}).</p>;
  if (!ci) return <p className="sub">Loading live results…</p>;
  return <div className="accuracy-live"><AccuracyTable ci={ci} /></div>;
}
