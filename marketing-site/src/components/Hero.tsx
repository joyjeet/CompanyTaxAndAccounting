import { siteConfig } from "../siteConfig";
import { handleSignup } from "../handlers/signup";

export default function Hero() {
  const { hero } = siteConfig;
  return (
    <section
      id="top"
      className="relative overflow-hidden bg-gradient-to-b from-brand-surface-alt to-white"
    >
      {/* Decorative accent bar */}
      <div
        aria-hidden="true"
        className="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-brand-primary via-brand-accent to-brand-primary"
      />
      <div className="container-page section grid items-center gap-12 lg:grid-cols-12 lg:gap-16">
        <div className="lg:col-span-7">
          <span className="eyebrow">{hero.eyebrow}</span>
          <h1 className="mt-5 text-4xl font-semibold leading-[1.08] sm:text-5xl lg:text-6xl">
            {hero.headline}
          </h1>
          <p className="mt-6 max-w-2xl text-lg leading-relaxed text-brand-ink-soft sm:text-xl">
            {hero.subhead}
          </p>
          <div className="mt-9 flex flex-col gap-3 sm:flex-row sm:items-center">
            <button
              type="button"
              onClick={() => handleSignup()}
              className="btn-primary text-base"
            >
              {hero.primaryCta}
              <svg
                xmlns="http://www.w3.org/2000/svg"
                viewBox="0 0 20 20"
                fill="currentColor"
                aria-hidden="true"
                className="h-4 w-4"
              >
                <path
                  fillRule="evenodd"
                  d="M3 10a.75.75 0 01.75-.75h10.638L10.23 5.29a.75.75 0 111.04-1.08l5.5 5.25a.75.75 0 010 1.08l-5.5 5.25a.75.75 0 11-1.04-1.08l4.158-3.96H3.75A.75.75 0 013 10z"
                  clipRule="evenodd"
                />
              </svg>
            </button>
            <a href="#how-it-works" className="btn-outline text-base">
              {hero.secondaryCta}
            </a>
          </div>

          <dl className="mt-12 grid max-w-xl grid-cols-3 gap-6 border-t border-brand-border pt-8">
            <div>
              <dt className="text-xs uppercase tracking-wider text-brand-ink-muted">
                CPA-led
              </dt>
              <dd className="mt-1 font-serif text-2xl font-semibold text-brand-primary">
                Every close
              </dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-wider text-brand-ink-muted">
                Security
              </dt>
              <dd className="mt-1 font-serif text-2xl font-semibold text-brand-primary">
                Bank-level
              </dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-wider text-brand-ink-muted">
                Records
              </dt>
              <dd className="mt-1 font-serif text-2xl font-semibold text-brand-primary">
                Audit-ready
              </dd>
            </div>
          </dl>
        </div>

        <div className="lg:col-span-5">
          <HeroCard />
        </div>
      </div>
    </section>
  );
}

/** Decorative "monthly summary" preview card. Pure presentation, no real data. */
function HeroCard() {
  return (
    <div className="relative">
      <div
        aria-hidden="true"
        className="absolute -inset-6 -z-10 rounded-3xl bg-brand-primary/5"
      />
      <div className="rounded-2xl border border-brand-border bg-white p-7 shadow-card-lg">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-xs uppercase tracking-wider text-brand-ink-muted">
              Monthly snapshot
            </p>
            <p className="mt-1 font-serif text-lg font-semibold text-brand-primary">
              Sample Business, LLC
            </p>
          </div>
          <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-3 py-1 text-xs font-semibold text-emerald-700">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
            Reviewed by CPA
          </span>
        </div>

        <div className="mt-6 grid grid-cols-3 gap-4">
          {[
            { label: "Revenue", value: "$48,210" },
            { label: "Expenses", value: "$31,490" },
            { label: "Net income", value: "$16,720", accent: true },
          ].map((m) => (
            <div
              key={m.label}
              className="rounded-lg border border-brand-border p-3"
            >
              <p className="text-[11px] uppercase tracking-wider text-brand-ink-muted">
                {m.label}
              </p>
              <p
                className={`mt-1 font-serif text-base font-semibold ${
                  m.accent ? "text-brand-accent-dark" : "text-brand-primary"
                }`}
              >
                {m.value}
              </p>
            </div>
          ))}
        </div>

        <div className="mt-6 space-y-3">
          {[
            { label: "Books closed for May", done: true },
            { label: "P&L and Balance Sheet delivered", done: true },
            { label: "Q2 tax estimates prepared", done: true },
            { label: "Q3 review call scheduled", done: false },
          ].map((row) => (
            <div
              key={row.label}
              className="flex items-center gap-3 text-sm text-brand-ink-soft"
            >
              <span
                className={`flex h-5 w-5 items-center justify-center rounded-full text-white ${
                  row.done ? "bg-brand-primary" : "bg-brand-border"
                }`}
                aria-hidden="true"
              >
                {row.done ? (
                  <svg
                    xmlns="http://www.w3.org/2000/svg"
                    viewBox="0 0 20 20"
                    fill="currentColor"
                    className="h-3 w-3"
                  >
                    <path
                      fillRule="evenodd"
                      d="M16.704 5.29a1 1 0 010 1.42l-7.5 7.5a1 1 0 01-1.42 0l-3.5-3.5a1 1 0 011.42-1.42L8.5 12.08l6.79-6.79a1 1 0 011.414 0z"
                      clipRule="evenodd"
                    />
                  </svg>
                ) : null}
              </span>
              <span>{row.label}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
