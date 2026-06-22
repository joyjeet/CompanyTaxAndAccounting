import type { PricingPlan } from "../siteConfig";
import { handleSignup } from "../handlers/signup";

type Props = {
  plan: PricingPlan;
};

export default function PricingCard({ plan }: Props) {
  const featured = !!plan.featured;
  return (
    <div
      className={`relative flex h-full flex-col rounded-2xl border bg-white p-7 transition-shadow ${
        featured
          ? "border-brand-primary shadow-card-lg ring-1 ring-brand-primary/20"
          : "border-brand-border shadow-card hover:shadow-card-lg"
      }`}
      aria-label={`${plan.name} plan`}
    >
      {featured && (
        <span className="absolute -top-3 left-1/2 -translate-x-1/2 rounded-full bg-brand-accent px-3 py-1 text-[11px] font-semibold uppercase tracking-wider text-brand-primary shadow-sm">
          Most popular
        </span>
      )}

      <div>
        <h3 className="font-serif text-xl font-semibold text-brand-primary">
          {plan.name}
        </h3>
        <p className="mt-1 text-sm text-brand-ink-muted">{plan.audience}</p>
      </div>

      <div className="mt-6 flex items-baseline gap-1">
        <span className="font-serif text-4xl font-semibold text-brand-primary">
          {plan.price}
        </span>
        {plan.priceSuffix && (
          <span className="text-sm font-medium text-brand-ink-muted">
            {plan.priceSuffix}
          </span>
        )}
      </div>

      <ul className="mt-6 flex-1 space-y-3 text-sm text-brand-ink-soft">
        {plan.features.map((f) => (
          <li key={f} className="flex items-start gap-3">
            <span
              aria-hidden="true"
              className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-brand-primary/10 text-brand-primary"
            >
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
            </span>
            <span>{f}</span>
          </li>
        ))}
      </ul>

      <button
        type="button"
        onClick={() => handleSignup(plan.id)}
        className={`${
          featured ? "btn-accent" : "btn-primary"
        } mt-8 w-full`}
      >
        {plan.ctaLabel}
      </button>
    </div>
  );
}
