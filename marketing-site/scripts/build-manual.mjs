// Renders docs/CUSTOMER_DEMO_GUIDE.md → public/demo-guide.html so the
// manual is shipped as a styled HTML page alongside the marketing site.
// Run via `npm run build:manual` (also chained from `npm run build`).
//
// Single source of truth for the manual remains docs/CUSTOMER_DEMO_GUIDE.md
// in the repo root — this script just produces a customer-friendly view.

import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { marked } from "marked";

const __dirname = dirname(fileURLToPath(import.meta.url));
const projectRoot = resolve(__dirname, "..");
const repoRoot = resolve(projectRoot, "..");

const SRC = resolve(repoRoot, "docs", "CUSTOMER_DEMO_GUIDE.md");
const OUT = resolve(projectRoot, "public", "demo-guide.html");

const md = readFileSync(SRC, "utf8");

marked.use({
  gfm: true,
  breaks: false,
});

const bodyHtml = marked.parse(md);

// Brand colors are duplicated here intentionally — this page is rendered
// at build time and must be self-contained (no JS). If the marketing site
// theme ever changes, update both src/siteConfig.ts and the values below.
const html = `<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <meta name="theme-color" content="#1E2761" />
    <title>CTAA Customer Demo Guide — MMFC LLC</title>
    <meta
      name="description"
      content="Step-by-step guide for testing the CTAA bookkeeping and tax-preparation demo from MMFC LLC."
    />
    <meta name="robots" content="noindex" />
    <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
    <link
      rel="preconnect"
      href="https://fonts.googleapis.com"
      crossorigin="anonymous"
    />
    <link
      rel="preconnect"
      href="https://fonts.gstatic.com"
      crossorigin="anonymous"
    />
    <link
      href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Source+Serif+4:wght@500;600;700&display=swap"
      rel="stylesheet"
    />
    <style>
      :root {
        --brand-primary: #1e2761;
        --brand-primary-dark: #151c47;
        --brand-accent: #c9a227;
        --brand-accent-dark: #a8861c;
        --brand-surface: #ffffff;
        --brand-surface-alt: #f7f8fb;
        --brand-ink: #1e293b;
        --brand-ink-soft: #334155;
        --brand-ink-muted: #64748b;
        --brand-border: #e2e8f0;
      }
      * { box-sizing: border-box; }
      html { scroll-behavior: smooth; }
      body {
        margin: 0;
        font-family:
          Inter,
          -apple-system,
          BlinkMacSystemFont,
          "Segoe UI",
          Roboto,
          sans-serif;
        color: var(--brand-ink);
        background: var(--brand-surface-alt);
        line-height: 1.65;
        -webkit-font-smoothing: antialiased;
      }
      a { color: var(--brand-primary); text-decoration: underline; text-underline-offset: 2px; }
      a:hover { color: var(--brand-accent-dark); }
      a:focus-visible {
        outline: 2px solid var(--brand-accent);
        outline-offset: 2px;
        border-radius: 3px;
      }
      .skip-link {
        position: absolute;
        left: -9999px;
      }
      .skip-link:focus {
        left: 1rem;
        top: 1rem;
        background: var(--brand-primary);
        color: #fff;
        padding: 0.5rem 0.9rem;
        border-radius: 0.375rem;
        z-index: 50;
      }
      header.site {
        background: var(--brand-primary);
        color: #fff;
        border-bottom: 4px solid var(--brand-accent);
      }
      header.site .inner {
        max-width: 920px;
        margin: 0 auto;
        padding: 1.25rem 1.5rem;
        display: flex;
        align-items: center;
        gap: 0.85rem;
        flex-wrap: wrap;
      }
      header.site img { height: 36px; width: 36px; }
      header.site .firm {
        font-family: "Source Serif 4", Georgia, serif;
        font-size: 1.15rem;
        font-weight: 600;
        letter-spacing: -0.01em;
      }
      header.site .sep {
        flex: 1;
      }
      header.site .home {
        color: #fff;
        font-size: 0.875rem;
        opacity: 0.85;
      }
      header.site .home:hover { opacity: 1; color: var(--brand-accent); }
      main {
        max-width: 920px;
        margin: 0 auto;
        padding: 2.5rem 1.5rem 4rem;
      }
      .doc {
        background: #fff;
        border: 1px solid var(--brand-border);
        border-radius: 1rem;
        padding: clamp(1.75rem, 4vw, 3rem);
        box-shadow:
          0 4px 14px -4px rgba(30, 39, 97, 0.1),
          0 2px 4px -2px rgba(30, 39, 97, 0.06);
      }
      h1, h2, h3, h4 {
        font-family: "Source Serif 4", Georgia, serif;
        color: var(--brand-primary);
        letter-spacing: -0.01em;
        line-height: 1.2;
      }
      h1 {
        font-size: clamp(2rem, 4vw, 2.6rem);
        margin: 0 0 1.25rem;
      }
      h2 {
        font-size: clamp(1.45rem, 3vw, 1.75rem);
        margin: 2.5rem 0 0.75rem;
        padding-top: 1rem;
        border-top: 1px solid var(--brand-border);
      }
      h3 {
        font-size: 1.2rem;
        margin: 1.75rem 0 0.5rem;
      }
      h4 {
        font-size: 1rem;
        margin: 1.25rem 0 0.4rem;
      }
      p { margin: 0 0 1rem; color: var(--brand-ink-soft); }
      strong { color: var(--brand-ink); font-weight: 600; }
      hr {
        border: 0;
        border-top: 1px solid var(--brand-border);
        margin: 2.25rem 0;
      }
      ul, ol { padding-left: 1.4rem; margin: 0 0 1rem; color: var(--brand-ink-soft); }
      li { margin: 0.3rem 0; }
      code {
        font-family:
          ui-monospace,
          SFMono-Regular,
          "SF Mono",
          Menlo,
          Consolas,
          monospace;
        font-size: 0.875em;
        background: var(--brand-surface-alt);
        border: 1px solid var(--brand-border);
        padding: 0.1em 0.4em;
        border-radius: 0.3em;
        color: var(--brand-primary);
        word-break: break-word;
      }
      pre {
        background: var(--brand-primary);
        color: #f0f4ff;
        border-radius: 0.6rem;
        padding: 1rem 1.1rem;
        overflow-x: auto;
        font-size: 0.85rem;
        line-height: 1.5;
        margin: 0 0 1.25rem;
      }
      pre code {
        background: transparent;
        border: 0;
        padding: 0;
        color: inherit;
      }
      blockquote {
        margin: 1.25rem 0;
        padding: 0.9rem 1.1rem;
        border-left: 4px solid var(--brand-accent);
        background: rgba(201, 162, 39, 0.08);
        color: var(--brand-ink);
        border-radius: 0 0.5rem 0.5rem 0;
      }
      blockquote p:last-child { margin-bottom: 0; }
      table {
        width: 100%;
        border-collapse: collapse;
        margin: 0 0 1.25rem;
        font-size: 0.93rem;
      }
      th, td {
        text-align: left;
        padding: 0.65rem 0.85rem;
        border-bottom: 1px solid var(--brand-border);
        vertical-align: top;
      }
      th {
        background: var(--brand-surface-alt);
        font-weight: 600;
        color: var(--brand-primary);
      }
      tr:last-child td { border-bottom: 0; }
      .cta-bar {
        margin-top: 2rem;
        padding: 1.25rem;
        background: var(--brand-primary);
        color: #fff;
        border-radius: 0.75rem;
        text-align: center;
      }
      .cta-bar a {
        color: #fff;
        font-weight: 600;
        text-decoration: underline;
      }
      .cta-bar a:hover { color: var(--brand-accent); }
      footer.site {
        max-width: 920px;
        margin: 0 auto;
        padding: 0 1.5rem 3rem;
        font-size: 0.825rem;
        color: var(--brand-ink-muted);
      }
      footer.site a { color: var(--brand-ink-muted); }
      @media print {
        body { background: #fff; }
        header.site, footer.site, .skip-link, .cta-bar { display: none; }
        main { padding: 0; }
        .doc { border: 0; box-shadow: none; padding: 0; }
        pre { background: #f6f7fb; color: #1e2761; border: 1px solid #e2e8f0; }
        a { color: inherit; text-decoration: none; }
        h2 { page-break-before: auto; }
        h1, h2, h3 { page-break-after: avoid; }
      }
    </style>
  </head>
  <body>
    <a class="skip-link" href="#content">Skip to main content</a>
    <header class="site">
      <div class="inner">
        <img src="/logo-placeholder.svg" alt="MMFC LLC logo" />
        <span class="firm">MMFC LLC</span>
        <span class="sep"></span>
        <a class="home" href="/">← Back to home</a>
      </div>
    </header>
    <main id="content">
      <article class="doc">
${bodyHtml}
        <div class="cta-bar">
          Questions or feedback? Email
          <a href="mailto:gaurav.malhotra@mmfcllc.com">gaurav.malhotra@mmfcllc.com</a>.
        </div>
      </article>
    </main>
    <footer class="site">
      <p>© ${new Date().getFullYear()} MMFC LLC. Tax-preparation support; not a substitute for individualized tax advice.</p>
    </footer>
  </body>
</html>
`;

mkdirSync(dirname(OUT), { recursive: true });
writeFileSync(OUT, html, "utf8");
console.log(`Rendered ${SRC} → ${OUT} (${(html.length / 1024).toFixed(1)} KB)`);
