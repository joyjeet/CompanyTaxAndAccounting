import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./index.css";
import { siteConfig } from "./siteConfig";

/**
 * Push brand colors from siteConfig.ts onto :root CSS variables before
 * the first paint. Keeps siteConfig as the single source of truth for
 * brand identity (Tailwind utilities read these vars).
 */
function applyBrandColors(): void {
  const root = document.documentElement;
  const c = siteConfig.colors;
  root.style.setProperty("--brand-primary", c.primary);
  root.style.setProperty("--brand-primary-dark", c.primaryDark);
  root.style.setProperty("--brand-accent", c.accent);
  root.style.setProperty("--brand-accent-dark", c.accentDark);
  root.style.setProperty("--brand-surface", c.surface);
  root.style.setProperty("--brand-surface-alt", c.surfaceAlt);
  root.style.setProperty("--brand-ink", c.ink);
  root.style.setProperty("--brand-ink-soft", c.inkSoft);
  root.style.setProperty("--brand-ink-muted", c.inkMuted);
  root.style.setProperty("--brand-border", c.border);
}

function setDocumentTitle(): void {
  document.title = `${siteConfig.firm.name} — ${siteConfig.firm.tagline}`;
}

applyBrandColors();
setDocumentTitle();

const rootEl = document.getElementById("root");
if (!rootEl) throw new Error("Missing #root element in index.html");

createRoot(rootEl).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
