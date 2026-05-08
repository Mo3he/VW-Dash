import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        vw: {
          blue: "#001E50",
          teal: "#00B0F0",
          light: "#DFE4E8",
        },
      },
    },
  },
  plugins: [],
};

export default config;
