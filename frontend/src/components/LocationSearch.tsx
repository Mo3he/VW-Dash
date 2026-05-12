"use client";
import { useState, useEffect, useRef } from "react";
import { api } from "@/lib/api";

interface LocationResult {
  display_name: string;
  lat: number;
  lon: number;
}

interface Props {
  value: string;
  /** Called on every keystroke (lat/lon undefined) and on result selection (lat/lon set). */
  onSelect: (name: string, lat?: number, lon?: number) => void;
  placeholder?: string;
  disabled?: boolean;
  className?: string;
}

export default function LocationSearch({ value, onSelect, placeholder, disabled, className }: Props) {
  const [query, setQuery] = useState(value);
  const [results, setResults] = useState<LocationResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  // sync if external value is cleared (e.g. form reset)
  useEffect(() => {
    if (!value) setQuery("");
  }, [value]);

  useEffect(() => {
    if (query.length < 3) {
      setResults([]);
      setOpen(false);
      return;
    }
    const t = setTimeout(async () => {
      setLoading(true);
      try {
        const data = await api.geocoder.search(query);
        setResults(data);
        setOpen(data.length > 0);
      } catch {
        setResults([]);
      } finally {
        setLoading(false);
      }
    }, 400);
    return () => clearTimeout(t);
  }, [query]);

  useEffect(() => {
    function handler(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  function handleSelect(r: LocationResult) {
    setQuery(r.display_name);
    setOpen(false);
    onSelect(r.display_name, r.lat, r.lon);
  }

  return (
    <div ref={containerRef} className="relative">
      <input
        type="text"
        value={query}
        disabled={disabled}
        placeholder={placeholder ?? "Search address…"}
        onChange={(e) => {
          setQuery(e.target.value);
          onSelect(e.target.value); // update name as typed, clear lat/lon
        }}
        className={className}
      />
      {loading && (
        <span className="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-gray-500 pointer-events-none">
          …
        </span>
      )}
      {open && results.length > 0 && (
        <ul className="absolute z-[200] mt-1 w-full rounded-xl bg-[#0d1117] border border-white/10 shadow-xl overflow-hidden max-h-52 overflow-y-auto">
          {results.map((r, i) => (
            <li
              key={i}
              onMouseDown={(e) => { e.preventDefault(); handleSelect(r); }}
              className="px-3 py-2 text-sm text-white hover:bg-white/5 cursor-pointer leading-snug"
            >
              {r.display_name}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
