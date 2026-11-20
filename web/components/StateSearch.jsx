"use client";

import { useMemo, useRef, useState } from "react";
import { ZONE_TO_NAME } from "../lib/zones";

const STATES = Object.entries(ZONE_TO_NAME)
  .map(([zone, name]) => ({ zone, name }))
  .sort((a, b) => a.name.localeCompare(b.name));

// Find a state by typing. Selecting one does the same as clicking it on the map.
export default function StateSearch({ selectedZone, onSelect }) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const inputRef = useRef(null);

  const matches = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? STATES.filter((s) => s.name.toLowerCase().includes(q)) : STATES;
  }, [query]);

  const choose = (zone) => {
    onSelect(zone);
    setQuery("");
    setOpen(false);
    inputRef.current?.blur();
  };

  const onKeyDown = (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setOpen(true); setActive((a) => Math.min(a + 1, matches.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
    else if (e.key === "Enter" && matches[active]) { e.preventDefault(); choose(matches[active].zone); }
    else if (e.key === "Escape") { setOpen(false); inputRef.current?.blur(); }
  };

  const selectedName = selectedZone !== "IN" ? ZONE_TO_NAME[selectedZone] : null;

  return (
    <div className="search">
      <svg className="search-icon" viewBox="0 0 16 16" aria-hidden="true">
        <circle cx="7" cy="7" r="4.5" fill="none" stroke="currentColor" strokeWidth="1.5" />
        <path d="M10.5 10.5 14 14" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
      {selectedName && !query && (
        <span className="chip">
          {selectedName}
          <button aria-label={`Clear ${selectedName}`} onClick={() => onSelect("IN")}>×</button>
        </span>
      )}
      <input
        ref={inputRef}
        role="combobox"
        aria-expanded={open}
        aria-controls="state-options"
        aria-label="Find a state"
        placeholder={selectedName ? "" : "Find a state"}
        value={query}
        onChange={(e) => { setQuery(e.target.value); setActive(0); setOpen(true); }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 120)}
        onKeyDown={onKeyDown}
      />
      {open && matches.length > 0 && (
        <ul className="search-list" id="state-options" role="listbox">
          {matches.map((s, i) => (
            <li key={s.zone} role="option" aria-selected={i === active}
                className={i === active ? "active" : ""}
                onMouseDown={(e) => { e.preventDefault(); choose(s.zone); }}
                onMouseEnter={() => setActive(i)}>
              {s.name}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
