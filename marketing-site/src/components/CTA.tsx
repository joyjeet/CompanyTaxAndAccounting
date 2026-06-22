import { siteConfig } from "../siteConfig";
import { handleSignup } from "../handlers/signup";

export default function CTA() {
  const { finalCta } = siteConfig;
  return (
    <section className="section bg-brand-surface-alt">
      <div className="container-page">
        <div className="overflow-hidden rounded-3xl bg-brand-primary px-8 py-14 text-center text-white shadow-card-lg sm:px-14 sm:py-20">
          <h2 className="text-3xl font-semibold text-white sm:text-4xl">
            {finalCta.headline}
          </h2>
          <p className="mx-auto mt-5 max-w-2xl text-lg text-white/80">
            {finalCta.subhead}
          </p>
          <div className="mt-8 flex justify-center">
            <button
              type="button"
              onClick={() => handleSignup()}
              className="btn-accent text-base"
            >
              {finalCta.primaryCta}
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
          </div>
        </div>
      </div>
    </section>
  );
}
