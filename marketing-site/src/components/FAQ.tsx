import { siteConfig } from "../siteConfig";

export default function FAQ() {
  const { faq } = siteConfig;
  return (
    <section id="faq" className="section bg-white">
      <div className="container-page">
        <div className="mx-auto max-w-3xl text-center">
          <span className="eyebrow">{faq.eyebrow}</span>
          <h2 className="mt-4 text-3xl font-semibold sm:text-4xl">
            {faq.headline}
          </h2>
        </div>

        <div className="mx-auto mt-12 max-w-3xl divide-y divide-brand-border rounded-2xl border border-brand-border bg-white">
          {faq.items.map((item, idx) => (
            <details
              key={item.question}
              className="group p-6 open:bg-brand-surface-alt"
              {...(idx === 0 ? { open: true } : {})}
            >
              <summary className="flex cursor-pointer list-none items-center justify-between gap-4 text-left font-serif text-lg font-semibold text-brand-primary outline-none">
                <span>{item.question}</span>
                <span
                  aria-hidden="true"
                  className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-brand-border text-brand-primary transition-transform group-open:rotate-45"
                >
                  <svg
                    xmlns="http://www.w3.org/2000/svg"
                    viewBox="0 0 20 20"
                    fill="currentColor"
                    className="h-4 w-4"
                  >
                    <path d="M10 4a.75.75 0 01.75.75v4.5h4.5a.75.75 0 010 1.5h-4.5v4.5a.75.75 0 01-1.5 0v-4.5h-4.5a.75.75 0 010-1.5h4.5v-4.5A.75.75 0 0110 4z" />
                  </svg>
                </span>
              </summary>
              <p className="mt-3 text-brand-ink-soft">{item.answer}</p>
            </details>
          ))}
        </div>
      </div>
    </section>
  );
}
