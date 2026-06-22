import { siteConfig } from "../siteConfig";

export default function Trust() {
  const { trust } = siteConfig;
  return (
    <section id="trust" className="section bg-brand-primary text-white">
      <div className="container-page">
        <div className="mx-auto max-w-3xl text-center">
          <span className="inline-block text-xs font-semibold uppercase tracking-[0.18em] text-brand-accent">
            {trust.eyebrow}
          </span>
          <h2 className="mt-4 text-3xl font-semibold text-white sm:text-4xl">
            {trust.headline}
          </h2>
          <p className="mt-5 text-lg text-white/80">{trust.intro}</p>
        </div>

        <ul className="mt-14 grid gap-6 sm:grid-cols-2">
          {trust.pillars.map((p) => (
            <li
              key={p.title}
              className="rounded-xl border border-white/10 bg-white/5 p-7 backdrop-blur-sm"
            >
              <h3 className="font-serif text-lg font-semibold text-white">
                {p.title}
              </h3>
              <p className="mt-3 text-white/80">{p.body}</p>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
