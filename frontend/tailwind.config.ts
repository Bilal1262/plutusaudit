import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          900: "#0b1020",
          800: "#0f172a",
          700: "#1e293b",
          600: "#334155",
        },
        veridian: {
          50: "#eafff7",
          100: "#c8fbe7",
          300: "#5eead4",
          500: "#14b8a6",
          600: "#0d9488",
          700: "#0f766e",
          900: "#134e4a",
        },
        amber: {
          400: "#fbbf24",
          500: "#f59e0b",
          600: "#d97706",
        },
      },
      boxShadow: {
        glow: "0 0 0 1px rgba(20,184,166,0.35), 0 8px 30px -10px rgba(20,184,166,0.45)",
      },
      animation: {
        "spin-slow": "spin 2s linear infinite",
        "pulse-fast": "pulse 1.2s cubic-bezier(0.4, 0, 0.6, 1) infinite",
      },
    },
  },
  plugins: [],
} satisfies Config;
