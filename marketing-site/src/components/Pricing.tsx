import { siteConfig } from "../siteConfig";
import PricingCard from "./PricingCard";

export default function Pricing() {
  const { pricing } = siteConfig;
  return (
    <section id="pricing" className="section bg-brand-surface-alt">
      <div className="container-page">
        <div className="mx-auto max-w-3xl text-center">
          <span className="eyebrow">{pricing.eyebrow}</span>
          <h2 className="mt-4 text-3xl font-semibold sm:text-4xl">
            {pricing.headline}
          </h2>
          <p className="mt-5 text-lg text-brand-ink-soft">{pricing.intro}</p>
        </div>

        <div className="mt-14 grid items-stretch gap-6 sm:grid-cols-2 xl:grid-cols-4">
          {pricing.plans.map((plan) => (
            <PricingCard key={plan.id} plan={plan} />
          ))}
        </div>

        <p className="mx-auto mt-10 max-w-3xl text-center text-sm text-brand-ink-muted">
          {pricing.footnote}
        </p>
      </div>
    </section>
  );
}
