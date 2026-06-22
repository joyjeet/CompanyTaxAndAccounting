import { siteConfig } from "../siteConfig";

export default function Footer() {
  const { firm, contact, nav, footer } = siteConfig;
  const year = new Date().getFullYear();

  return (
    <footer
      id="contact"
      className="border-t border-brand-border bg-white"
      aria-labelledby="footer-heading"
    >
      <h2 id="footer-heading" className="sr-only">
        Footer
      </h2>
      <div className="container-page py-14">
        <div className="grid gap-10 lg:grid-cols-12">
          <div className="lg:col-span-5">
            <div className="flex items-center gap-3">
              <img
                src={firm.logoSrc}
                alt={firm.logoAlt}
                className="h-9 w-9"
                width={36}
                height={36}
              />
              <span className="font-serif text-lg font-semibold text-brand-primary">
                {firm.name}
              </span>
            </div>
            <p className="mt-4 max-w-md text-sm text-brand-ink-soft">
              {footer.blurb}
            </p>
          </div>

          <div className="lg:col-span-3">
            <h3 className="text-sm font-semibold uppercase tracking-wider text-brand-primary">
              Site
            </h3>
            <ul className="mt-4 space-y-2">
              {nav.map((item) => (
                <li key={item.href}>
                  <a
                    href={item.href}
                    className="text-sm text-brand-ink-soft hover:text-brand-primary"
                  >
                    {item.label}
                  </a>
                </li>
              ))}
            </ul>
          </div>

          <div className="lg:col-span-4">
            <h3 className="text-sm font-semibold uppercase tracking-wider text-brand-primary">
              Contact
            </h3>
            <address className="mt-4 not-italic">
              <ul className="space-y-2 text-sm text-brand-ink-soft">
                <li>
                  Email{" "}
                  <a
                    href={`mailto:${contact.email}`}
                    className="font-medium text-brand-primary hover:underline"
                  >
                    {contact.email}
                  </a>
                </li>
                <li>
                  Phone{" "}
                  <a
                    href={`tel:${contact.phone.replace(/[^0-9+]/g, "")}`}
                    className="font-medium text-brand-primary hover:underline"
                  >
                    {contact.phone}
                  </a>
                </li>
                <li>
                  Web{" "}
                  <span className="font-medium text-brand-primary">
                    {contact.website}
                  </span>
                </li>
                {contact.address && <li>{contact.address}</li>}
              </ul>
            </address>
          </div>
        </div>

        <div className="mt-12 border-t border-brand-border pt-6 text-xs text-brand-ink-muted">
          <p>
            &copy; {year} {firm.legalName}. All rights reserved.
          </p>
          <p className="mt-2 max-w-3xl">{footer.disclaimer}</p>
        </div>
      </div>
    </footer>
  );
}
