import { useEffect, useState } from "react";
import { siteConfig } from "../siteConfig";
import { handleSignup } from "../handlers/signup";

export default function Header() {
  const [open, setOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  // Close mobile menu when a link is clicked.
  const close = () => setOpen(false);

  return (
    <header
      className={`sticky top-0 z-40 w-full border-b transition-colors ${
        scrolled
          ? "border-brand-border bg-white/95 backdrop-blur"
          : "border-transparent bg-brand-surface"
      }`}
    >
      <div className="container-page flex h-16 items-center justify-between gap-6 sm:h-20">
        <a
          href="#top"
          className="flex items-center gap-3"
          aria-label={`${siteConfig.firm.name} home`}
        >
          <img
            src={siteConfig.firm.logoSrc}
            alt={siteConfig.firm.logoAlt}
            className="h-9 w-9 sm:h-10 sm:w-10"
            width={40}
            height={40}
          />
          <span className="font-serif text-lg font-semibold text-brand-primary sm:text-xl">
            {siteConfig.firm.name}
          </span>
        </a>

        <nav
          aria-label="Primary"
          className="hidden items-center gap-8 lg:flex"
        >
          {siteConfig.nav.map((item) => (
            <a
              key={item.href}
              href={item.href}
              className="text-sm font-medium text-brand-ink-soft hover:text-brand-primary"
            >
              {item.label}
            </a>
          ))}
        </nav>

        <div className="hidden items-center gap-3 lg:flex">
          <a href={siteConfig.loginUrl} className="btn-ghost">
            Log in
          </a>
          <button
            type="button"
            onClick={() => handleSignup()}
            className="btn-primary"
          >
            Get started
          </button>
        </div>

        <button
          type="button"
          className="inline-flex items-center justify-center rounded-md p-2 text-brand-primary lg:hidden"
          aria-expanded={open}
          aria-controls="mobile-nav"
          aria-label={open ? "Close menu" : "Open menu"}
          onClick={() => setOpen((v) => !v)}
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth={2}
            strokeLinecap="round"
            strokeLinejoin="round"
            className="h-6 w-6"
            aria-hidden="true"
          >
            {open ? (
              <>
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
              </>
            ) : (
              <>
                <line x1="3" y1="6" x2="21" y2="6" />
                <line x1="3" y1="12" x2="21" y2="12" />
                <line x1="3" y1="18" x2="21" y2="18" />
              </>
            )}
          </svg>
        </button>
      </div>

      {open && (
        <nav
          id="mobile-nav"
          aria-label="Mobile"
          className="border-t border-brand-border bg-white lg:hidden"
        >
          <ul className="container-page flex flex-col gap-1 py-3">
            {siteConfig.nav.map((item) => (
              <li key={item.href}>
                <a
                  href={item.href}
                  onClick={close}
                  className="block rounded-md px-3 py-3 text-base font-medium text-brand-ink-soft hover:bg-brand-surface-alt hover:text-brand-primary"
                >
                  {item.label}
                </a>
              </li>
            ))}
            <li className="mt-2 flex flex-col gap-2 border-t border-brand-border pt-3">
              <a
                href={siteConfig.loginUrl}
                onClick={close}
                className="btn-outline w-full"
              >
                Log in
              </a>
              <button
                type="button"
                onClick={() => {
                  close();
                  handleSignup();
                }}
                className="btn-primary w-full"
              >
                Get started
              </button>
            </li>
          </ul>
        </nav>
      )}
    </header>
  );
}
