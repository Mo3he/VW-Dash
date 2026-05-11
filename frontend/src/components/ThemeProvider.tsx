"use client";
import { createContext, useContext, useEffect, useState } from "react";

type Theme = "dark" | "light";

export interface ColorSet {
  accent: string;
  pageBg: string;
  cardBg: string;
}

export interface ThemeColors {
  dark: ColorSet;
  light: ColorSet;
}

export const COLOR_DEFAULTS: ThemeColors = {
  dark:  { accent: "#00B0F0", pageBg: "#0f1117", cardBg: "#161b27" },
  light: { accent: "#00B0F0", pageBg: "#f4f5f7", cardBg: "#ffffff" },
};

function applyVars(theme: Theme, colors: ThemeColors) {
  const c = colors[theme];
  const root = document.documentElement;
  root.style.setProperty("--accent",  c.accent);
  root.style.setProperty("--page-bg", c.pageBg);
  root.style.setProperty("--card-bg", c.cardBg);
  // Derived variables that shift with the theme but aren't user-customisable
  if (theme === "dark") {
    root.style.setProperty("--card-bg-dark", "#0d1117");
    root.style.setProperty("--card-bg-alt",  "#1e2535");
    root.style.setProperty("--nav-bg",       "#0a0d14");
  } else {
    root.style.setProperty("--card-bg-dark", "#f1f3f5");
    root.style.setProperty("--card-bg-alt",  "#eef0f4");
    root.style.setProperty("--nav-bg",       "#e8eaed");
  }
}

interface ThemeContextValue {
  theme: Theme;
  toggleTheme: () => void;
  colors: ThemeColors;
  setColors: (colors: ThemeColors) => void;
}

const ThemeContext = createContext<ThemeContextValue>({
  theme: "dark",
  toggleTheme: () => {},
  colors: COLOR_DEFAULTS,
  setColors: () => {},
});

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setTheme] = useState<Theme>("dark");
  const [colors, setColorsState] = useState<ThemeColors>(COLOR_DEFAULTS);

  useEffect(() => {
    const savedTheme = localStorage.getItem("vwdash-theme") as Theme | null;
    const savedColors = (() => {
      try {
        const raw = localStorage.getItem("vwdash-colors");
        if (!raw) return COLOR_DEFAULTS;
        const parsed = JSON.parse(raw) as Partial<ThemeColors>;
        return {
          dark:  { ...COLOR_DEFAULTS.dark,  ...parsed.dark },
          light: { ...COLOR_DEFAULTS.light, ...parsed.light },
        };
      } catch { return COLOR_DEFAULTS; }
    })();

    const t: Theme = savedTheme === "light" ? "light" : "dark";
    setTheme(t);
    setColorsState(savedColors);
    if (t === "light") document.documentElement.classList.add("light");
    applyVars(t, savedColors);
  }, []);

  function toggleTheme() {
    const next: Theme = theme === "dark" ? "light" : "dark";
    setTheme(next);
    if (next === "light") {
      document.documentElement.classList.add("light");
    } else {
      document.documentElement.classList.remove("light");
    }
    localStorage.setItem("vwdash-theme", next);
    applyVars(next, colors);
  }

  function setColors(newColors: ThemeColors) {
    setColorsState(newColors);
    localStorage.setItem("vwdash-colors", JSON.stringify(newColors));
    applyVars(theme, newColors);
  }

  return (
    <ThemeContext.Provider value={{ theme, toggleTheme, colors, setColors }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme(): Theme {
  return useContext(ThemeContext).theme;
}

export function useToggleTheme(): () => void {
  return useContext(ThemeContext).toggleTheme;
}

/** Returns the hex accent colour for the current theme. */
export function useAccentColor(): string {
  const { theme, colors } = useContext(ThemeContext);
  return colors[theme].accent;
}

export function useColors(): ThemeColors {
  return useContext(ThemeContext).colors;
}

export function useSetColors(): (colors: ThemeColors) => void {
  return useContext(ThemeContext).setColors;
}
