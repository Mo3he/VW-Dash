"use client";
import { useState, useRef, useEffect } from "react";
import clsx from "clsx";

const PRESETS = [
  { label: "7d", days: 7 },
  { label: "30d", days: 30 },
  { label: "90d", days: 90 },
  { label: "1y", days: 365 },
  { label: "All", days: 3650 },
];

interface Props {
  value: number;
  onChange: (days: number) => void;
}

export default function PeriodSelector({ value, onChange }: Props) {
  const [showCustom, setShowCustom] = useState(false);
  const [customInput, setCustomInput] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  const isPreset = PRESETS.some((p) => p.days === value);

  useEffect(() => {
    if (showCustom) inputRef.current?.focus();
  }, [showCustom]);

  function commitCustom() {
    const n = parseInt(customInput, 10);
    if (n > 0) onChange(n);
    setShowCustom(false);
    setCustomInput("");
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter") commitCustom();
    if (e.key === "Escape") { setShowCustom(false); setCustomInput(""); }
  }

  return (
    <div className="flex items-center gap-1">
      {PRESETS.map((opt) => (
        <button
          key={opt.days}
          onClick={() => { onChange(opt.days); setShowCustom(false); }}
          className={clsx(
            "text-xs px-2.5 py-1 rounded-lg transition",
            value === opt.days && !showCustom
              ? "bg-[#00B0F0]/20 text-[#00B0F0] font-medium"
              : "text-gray-500 hover:text-gray-300"
          )}
        >
          {opt.label}
        </button>
      ))}

      {showCustom ? (
        <input
          ref={inputRef}
          type="number"
          min={1}
          value={customInput}
          onChange={(e) => setCustomInput(e.target.value)}
          onBlur={commitCustom}
          onKeyDown={handleKeyDown}
          placeholder="days"
          className="w-16 text-xs px-2 py-1 rounded-lg bg-[#1e2535] border border-[#00B0F0]/50 text-white focus:outline-none"
        />
      ) : (
        <button
          onClick={() => { setShowCustom(true); setCustomInput(isPreset ? "" : String(value)); }}
          className={clsx(
            "text-xs px-2.5 py-1 rounded-lg transition",
            !isPreset
              ? "bg-[#00B0F0]/20 text-[#00B0F0] font-medium"
              : "text-gray-500 hover:text-gray-300"
          )}
        >
          {!isPreset ? `${value}d` : "…"}
        </button>
      )}
    </div>
  );
}
