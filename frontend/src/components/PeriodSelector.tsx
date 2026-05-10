"use client";
import { useState } from "react";
import clsx from "clsx";

export interface DateRange {
  start: string; // YYYY-MM-DD
  end: string;   // YYYY-MM-DD
  preset?: number; // days, set for preset buttons
}

const PRESETS = [
  { label: "1d", days: 1 },
  { label: "7d", days: 7 },
  { label: "30d", days: 30 },
  { label: "90d", days: 90 },
  { label: "1y", days: 365 },
  { label: "All", days: 3650 },
];

function today() {
  return new Date().toISOString().split("T")[0];
}

function daysAgo(n: number) {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().split("T")[0];
}

export function defaultRange(days = 30): DateRange {
  return { start: daysAgo(days), end: today(), preset: days };
}

interface Props {
  value: DateRange;
  onChange: (range: DateRange) => void;
}

export default function PeriodSelector({ value, onChange }: Props) {
  const [showCustom, setShowCustom] = useState(false);
  const [customStart, setCustomStart] = useState("");
  const [customEnd, setCustomEnd] = useState("");

  function openCustom() {
    setCustomStart(value.start);
    setCustomEnd(value.end);
    setShowCustom(true);
  }

  function commitCustom() {
    if (customStart && customEnd) {
      onChange({ start: customStart, end: customEnd });
    }
    setShowCustom(false);
  }

  const isCustom = !value.preset;

  if (showCustom) {
    return (
      <div className="flex items-center gap-1.5">
        <input
          type="date"
          value={customStart}
          max={customEnd || today()}
          onChange={(e) => setCustomStart(e.target.value)}
          className="text-xs px-2 py-1 rounded-lg bg-[#1e2535] border border-[#00B0F0]/50 text-white focus:outline-none"
        />
        <span className="text-xs text-gray-500">–</span>
        <input
          type="date"
          value={customEnd}
          min={customStart}
          max={today()}
          onChange={(e) => setCustomEnd(e.target.value)}
          className="text-xs px-2 py-1 rounded-lg bg-[#1e2535] border border-[#00B0F0]/50 text-white focus:outline-none"
        />
        <button
          onClick={commitCustom}
          className="text-xs px-2 py-1 rounded-lg bg-[#00B0F0]/20 text-[#00B0F0] font-medium hover:bg-[#00B0F0]/30 transition"
        >
          Apply
        </button>
        <button
          onClick={() => setShowCustom(false)}
          className="text-xs px-2 py-1 rounded-lg text-gray-500 hover:text-gray-300 transition"
        >
          ✕
        </button>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-1">
      {PRESETS.map((opt) => (
        <button
          key={opt.days}
          onClick={() => onChange({ start: daysAgo(opt.days), end: today(), preset: opt.days })}
          className={clsx(
            "text-xs px-2.5 py-1 rounded-lg transition",
            value.preset === opt.days
              ? "bg-[#00B0F0]/20 text-[#00B0F0] font-medium"
              : "text-gray-500 hover:text-gray-300"
          )}
        >
          {opt.label}
        </button>
      ))}
      <button
        onClick={openCustom}
        className={clsx(
          "text-xs px-2.5 py-1 rounded-lg transition",
          isCustom
            ? "bg-[#00B0F0]/20 text-[#00B0F0] font-medium"
            : "text-gray-500 hover:text-gray-300"
        )}
      >
        {isCustom ? `${value.start} – ${value.end}` : "…"}
      </button>
    </div>
  );
}
