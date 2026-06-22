import { siteConfig } from "../siteConfig";

export default function WhatYouGet() {
  const { whatYouGet } = siteConfig;
  return (
    <section id="what-you-get" className="section bg-white">
      <div className="container-page">
        <div className="mx-auto max-w-3xl text-center">
          <span className="eyebrow">{whatYouGet.eyebrow}</span>
          <h2 className="mt-4 text-3xl font-semibold sm:text-4xl">
            {whatYouGet.headline}
          </h2>
          <p className="mt-5 text-lg text-brand-ink-soft">{whatYouGet.intro}</p>
        </div>

        <ul className="mt-14 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {whatYouGet.items.map((item) => (
            <li key={item.title} className="card">
              <div
                aria-hidden="true"
                className="flex h-10 w-10 items-center justify-center rounded-lg bg-brand-primary/10 text-brand-primary"
              >
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  viewBox="0 0 20 20"
                  fill="currentColor"
                  className="h-5 w-5"
                >
                  <path
                    fillRule="evenodd"
                    d="M16.704 5.29a1 1 0 010 1.42l-7.5 7.5a1 1 0 01-1.42 0l-3.5-3.5a1 1 0 011.42-1.42L8.5 12.08l6.79-6.79a1 1 0 011.414 0z"
                    clipRule="evenodd"
                  />
                </svg>
              </div>
              <h3 className="mt-4 font-serif text-lg font-semibold text-brand-primary">
                {item.title}
              </h3>
              <p className="mt-2 text-brand-ink-soft">{item.body}</p>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
