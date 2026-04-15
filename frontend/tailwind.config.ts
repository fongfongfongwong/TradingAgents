import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ["var(--font-sans)", "Inter", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "JetBrains Mono", "SF Mono", "Menlo", "monospace"],
      },
      colors: {
        brand: {
          50: "#eef7ff",
          100: "#d9edff",
          200: "#bce0ff",
          300: "#8ecdff",
          400: "#59b0ff",
          500: "#338dff",
          600: "#1b6df5",
          700: "#1457e1",
          800: "#1746b6",
          900: "#193e8f",
          950: "#142757",
        },
      },
    },
  },
  plugins: [],
};

export default config;
