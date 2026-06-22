import type { Config } from "tailwindcss";

// Brand colors are exposed as CSS variables (see src/index.css), so the
// single source of truth for the firm's identity stays in src/siteConfig.ts.
// Tailwind classes like `bg-brand-primary` resolve through those vars.
const config: Config = {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          primary: "rgb(var(--brand-primary) / <alpha-value>)",
          "primary-dark": "rgb(var(--brand-primary-dark) / <alpha-value>)",
          accent: "rgb(var(--brand-accent) / <alpha-value>)",
          "accent-dark": "rgb(var(--brand-accent-dark) / <alpha-value>)",
          surface: "rgb(var(--brand-surface) / <alpha-value>)",
          "surface-alt": "rgb(var(--brand-surface-alt) / <alpha-value>)",
          ink: "rgb(var(--brand-ink) / <alpha-value>)",
          "ink-soft": "rgb(var(--brand-ink-soft) / <alpha-value>)",
          "ink-muted": "rgb(var(--brand-ink-muted) / <alpha-value>)",
          border: "rgb(var(--brand-border) / <alpha-value>)",
        },
      },
      fontFamily: {
        serif: ['"Source Serif 4"', '"Source Serif Pro"', "Georgia", "serif"],
        sans: [
          "Inter",
          "-apple-system",
          "BlinkMacSystemFont",
          '"Segoe UI"',
          "Roboto",
          "sans-serif",
        ],
      },
      maxWidth: {
        container: "1200px",
      },
      boxShadow: {
        card: "0 4px 14px -4px rgb(30 39 97 / 0.10), 0 2px 4px -2px rgb(30 39 97 / 0.06)",
        "card-lg":
          "0 12px 32px -8px rgb(30 39 97 / 0.18), 0 4px 8px -2px rgb(30 39 97 / 0.08)",
      },
    },
  },
  plugins: [],
};

export default config;
