# MMFC LLC — Marketing Site

The **public**, unauthenticated marketing site for MMFC LLC's AI-assisted
bookkeeping, financial-statement, and tax-preparation service. This is a
standalone static site — it does NOT depend on, link to, or share code
with the application in `../app/` or `../frontend/`.

> **Looking for the reviewer dashboard / client portal?** That's the
> authenticated app in [`../frontend/`](../frontend/). This folder is the
> public storefront only.

---

## Stack

- **React 18 + TypeScript**
- **Vite 5** — pure static build (no Node runtime in production)
- **Tailwind CSS 3** — utility styling, brand colors wired through CSS variables

### Why Vite, not Next.js?

A single-page landing site doesn't materially benefit from SSR — Google
renders JS-built SPAs fine when the meta tags are in `index.html` (which
they are). Vite gives us a smaller toolchain, a fully static `dist/`, and
free hosting on any CDN (Cloudflare Pages, S3 + CloudFront, Azure Static
Web Apps, Netlify, Vercel static). If SEO requirements grow — multiple
crawlable pages, dynamic OG images, etc. — the components are framework-
agnostic and lift straight into Next.

---

## Run

```bash
cd marketing-site
npm install
npm run dev        # http://localhost:4321
```

## Build a static bundle

```bash
npm run build      # type-checks + emits ./dist
npm run preview    # serves ./dist locally for a sanity check
```

The `dist/` folder is fully self-contained — copy it to any static host.

---

## Brand isolation: everything lives in one file

All firm-specific content — name, logo, colors, contact details, plan
names and prices, FAQ, every line of body copy — is centralized in
[`src/siteConfig.ts`](src/siteConfig.ts). Components read from it and
hard-code nothing about MMFC LLC.

To re-skin this site for another firm:

1. Edit `src/siteConfig.ts` (firm name, copy, plans, colors, contact).
2. Swap `public/logo-placeholder.svg`, `public/favicon.svg`,
   and `public/og-image.svg` for the new firm's assets.
3. Update the meta tags in `index.html` if the firm name / OG image
   paths change.

No component edits required.

### How colors flow

`siteConfig.ts` declares brand colors as plain RGB triples. At app start
(`src/main.tsx → applyBrandColors()`) those values are written onto
`:root` as CSS custom properties (`--brand-primary`, etc.). Tailwind's
config (`tailwind.config.ts`) maps utility classes like
`bg-brand-primary`, `text-brand-accent` to those variables. **One file
edited → entire site re-themed.**

---

## Sign-up wiring (single place to edit)

Every "Get started" / "Sign up" / "Talk to us" button on the page funnels
through one function:

[`src/handlers/signup.ts → handleSignup(planId?)`](src/handlers/signup.ts)

Today it opens a `mailto:` to `siteConfig.contact.email` with the plan
pre-filled in the subject line, so inbound interest is captured the
moment you ship. Replace the body of `handleSignup` with the real flow
when ready (hosted form, POST to back-end, scheduling link, etc.).

The "Log in" link points at `siteConfig.loginUrl` (currently `/login`
placeholder — update when the real authenticated app URL is decided).

---

## Placeholders to replace before launch

All marked with `TODO` in the source:

| What | Where |
|---|---|
| Real logo (replace placeholder SVG) | `public/logo-placeholder.svg` |
| Favicon (optional refresh) | `public/favicon.svg` |
| Open Graph image (optional refresh) | `public/og-image.svg` |
| Contact email | `src/siteConfig.ts` → `contact.email` |
| Contact phone | `src/siteConfig.ts` → `contact.phone` |
| Public website URL | `src/siteConfig.ts` → `contact.website` |
| (Optional) postal address | `src/siteConfig.ts` → `contact.address` |
| Real login URL | `src/siteConfig.ts` → `loginUrl` |
| Sign-up handler implementation | `src/handlers/signup.ts` |

---

## Accessibility & SEO checklist (already in place)

- Semantic landmarks: `<header>`, `<main>`, `<nav>`, `<section>`, `<footer>`.
- Skip-to-content link as the first focusable element.
- Visible focus rings on all interactive elements.
- All images have meaningful `alt` text; decorative SVGs are `aria-hidden`.
- Heading hierarchy is single-`<h1>` (hero) followed by `<h2>` per section.
- `<title>`, `<meta name="description">`, Open Graph, and Twitter card
  tags are set in `index.html`.
- Mobile-first responsive (tested at 375 / 768 / 1280 breakpoints).
- Strong contrast: navy text on white, white text on navy, gold accent
  sized large enough on white backgrounds to clear WCAG AA.

---

## Project layout

```
marketing-site/
├── index.html               # static shell + meta tags
├── public/
│   ├── logo-placeholder.svg # TODO: replace with real logo
│   ├── favicon.svg
│   └── og-image.svg
└── src/
    ├── main.tsx             # boot + applyBrandColors()
    ├── App.tsx              # page composition
    ├── index.css            # Tailwind + brand vars + component classes
    ├── siteConfig.ts        # SINGLE source of truth for the brand
    ├── handlers/
    │   └── signup.ts        # SINGLE sign-up handler — wire later
    └── components/
        ├── Header.tsx       # logo, nav, log in, get started (mobile menu)
        ├── Hero.tsx         # headline + sample-snapshot card
        ├── Problem.tsx      # four pain points
        ├── HowItWorks.tsx   # three steps + human-oversight callout
        ├── WhatYouGet.tsx   # six deliverables
        ├── Trust.tsx        # four trust pillars
        ├── Pricing.tsx      # four plan cards
        ├── PricingCard.tsx  # one plan card
        ├── FAQ.tsx          # accordion FAQ
        ├── CTA.tsx          # final conversion band
        └── Footer.tsx       # nav, contact, disclaimer
```
