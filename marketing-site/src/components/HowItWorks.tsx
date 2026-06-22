import { siteConfig } from "../siteConfig";

export default function HowItWorks() {
  const { howItWorks } = siteConfig;
  return (
    <section id="how-it-works" className="section bg-brand-surface-alt">
      <div className="container-page">
        <div className="mx-auto max-w-3xl text-center">
          <span className="eyebrow">{howItWorks.eyebrow}</span>
          <h2 className="mt-4 text-3xl font-semibold sm:text-4xl">
            {howItWorks.headline}
          </h2>
          <p className="mt-5 text-lg text-brand-ink-soft">{howItWorks.intro}</p>
        </div>

        <ol className="mt-14 grid gap-6 md:grid-cols-3">
          {howItWorks.steps.map((s) => (
            <li
              key={s.number}
              className="relative flex flex-col rounded-xl border border-brand-border bg-white p-7 shadow-card"
            >
              <span
                aria-hidden="true"
                className="font-serif text-5xl font-semibold text-brand-accent"
              >
                {s.number}
              </span>
              <h3 className="mt-3 font-serif text-xl font-semibold text-brand-primary">
                {s.title}
              </h3>
              <p className="mt-3 text-brand-ink-soft">{s.body}</p>
            </li>
          ))}
        </ol>

        <p className="mx-auto mt-12 max-w-3xl rounded-xl border border-brand-primary/15 bg-brand-primary/5 p-6 text-center text-brand-ink-soft">
          <strong className="text-brand-primary">Human oversight built in. </strong>
          {howItWorks.footnote}
        </p>
      </div>
    </section>
  );
}
