"use client";
import { useColors, useSetColors, COLOR_DEFAULTS, type ThemeColors, type ColorSet } from "@/components/ThemeProvider";

type ThemeKey = "dark" | "light";

function ColorRow({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-sm text-gray-400">{label}</span>
      <div className="flex items-center gap-2">
        <span className="text-xs text-gray-600 font-mono">{value}</span>
        <input
          type="color"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="w-8 h-8 rounded-lg cursor-pointer border border-white/10 bg-transparent p-0.5"
        />
      </div>
    </div>
  );
}

function ThemeSection({ themeKey, label }: { themeKey: ThemeKey; label: string }) {
  const colors = useColors();
  const setColors = useSetColors();
  const c: ColorSet = colors[themeKey];

  function update(key: keyof ColorSet, val: string) {
    const updated: ThemeColors = {
      ...colors,
      [themeKey]: { ...c, [key]: val },
    };
    setColors(updated);
  }

  function reset() {
    setColors({ ...colors, [themeKey]: COLOR_DEFAULTS[themeKey] });
  }

  const isDefault =
    c.accent === COLOR_DEFAULTS[themeKey].accent &&
    c.pageBg === COLOR_DEFAULTS[themeKey].pageBg &&
    c.cardBg === COLOR_DEFAULTS[themeKey].cardBg;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <span className="text-xs text-gray-400 uppercase tracking-wider font-medium">{label}</span>
        <button
          type="button"
          onClick={reset}
          disabled={isDefault}
          className="text-xs text-gray-600 hover:text-gray-400 transition-colors disabled:opacity-30"
        >
          Reset
        </button>
      </div>
      <ColorRow label="Accent"          value={c.accent} onChange={(v) => update("accent", v)} />
      <ColorRow label="Page background" value={c.pageBg} onChange={(v) => update("pageBg", v)} />
      <ColorRow label="Card background" value={c.cardBg} onChange={(v) => update("cardBg", v)} />
    </div>
  );
}

export default function AppearanceSettings() {
  return (
    <div className="rounded-2xl bg-[#161b27] border border-white/5 p-4 flex flex-col gap-5">
      <div className="text-xs text-gray-400 uppercase tracking-wider font-medium">Appearance</div>
      <ThemeSection themeKey="dark"  label="Dark mode" />
      <div className="border-t border-white/5" />
      <ThemeSection themeKey="light" label="Light mode" />
      <p className="text-[11px] text-gray-600 -mt-1">
        Changes apply instantly and are saved in your browser.
      </p>
    </div>
  );
}
