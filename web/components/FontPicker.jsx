"use client";

// Review-only: flip the whole site between candidate typefaces. Remove once
// one is chosen (and drop the unused faces from app/layout.jsx).
import { useEffect, useState } from "react";

const FONTS = [
  ["host", "Host Grotesk"],
  ["instrument", "Instrument Sans"],
  ["sora", "Sora"],
  ["schibsted", "Schibsted Grotesk"],
];

export default function FontPicker() {
  const [font, setFont] = useState("host");

  useEffect(() => {
    const fromUrl = new URLSearchParams(location.search).get("font");
    if (fromUrl && FONTS.some(([k]) => k === fromUrl)) setFont(fromUrl);
  }, []);

  useEffect(() => {
    document.documentElement.style.setProperty("--font-sans", `var(--f-${font})`);
    const url = new URL(location.href);
    url.searchParams.set("font", font);
    history.replaceState(null, "", url);
  }, [font]);

  return (
    <div className="font-picker" role="group" aria-label="Typeface (review only)">
      <span>Font</span>
      {FONTS.map(([key, label]) => (
        <button key={key} className={font === key ? "on" : ""} onClick={() => setFont(key)}
                style={{ fontFamily: `var(--f-${key})` }}>
          {label}
        </button>
      ))}
    </div>
  );
}
