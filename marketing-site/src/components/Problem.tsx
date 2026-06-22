import { siteConfig } from "../siteConfig";

export default function Problem() {
  const { problem } = siteConfig;
  return (
    <section id="problem" className="section bg-white">
      <div className="container-page">
        <div className="mx-auto max-w-3xl text-center">
          <span className="eyebrow">{problem.eyebrow}</span>
          <h2 className="mt-4 text-3xl font-semibold sm:text-4xl">
            {problem.headline}
          </h2>
          <p className="mt-5 text-lg text-brand-ink-soft">{problem.intro}</p>
        </div>

        <ul className="mt-14 grid gap-6 sm:grid-cols-2">
          {problem.pains.map((p) => (
            <li key={p.title} className="card">
              <h3 className="font-serif text-lg font-semibold text-brand-primary">
                {p.title}
              </h3>
              <p className="mt-3 text-brand-ink-soft">{p.body}</p>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
