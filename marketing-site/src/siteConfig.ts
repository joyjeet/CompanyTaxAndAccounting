/**
 * Single source of truth for the firm's brand, copy, contact details, and
 * pricing. ALL brand-specific values live here — components must not
 * hard-code firm name, colors, contact info, plans, etc.
 *
 * To re-skin this site for a different firm, edit only this file (and swap
 * the logo file in /public if needed).
 */

export type BrandColors = {
  /** Deep navy / primary surface for buttons, headings on light bg. */
  primary: string;
  /** Slightly deeper navy for hovers and dark surfaces. */
  primaryDark: string;
  /** Gold accent — sparingly, for highlights and the "featured" plan. */
  accent: string;
  accentDark: string;
  /** Page background. */
  surface: string;
  /** Subtle alt section background. */
  surfaceAlt: string;
  /** Default body text — dark slate. */
  ink: string;
  /** Slightly lighter body text. */
  inkSoft: string;
  /** Muted / caption text. */
  inkMuted: string;
  /** Default border color. */
  border: string;
};

export type PricingPlan = {
  id: string;
  name: string;
  /** Monthly price as a display string, e.g. "$150". Use "Custom" for enterprise. */
  price: string;
  priceSuffix?: string; // e.g. "/mo"
  /** One-line audience descriptor. */
  audience: string;
  /** Bulleted feature list. */
  features: string[];
  /** Render this card with the "Most popular" highlight. */
  featured?: boolean;
  /** Text on the CTA button. */
  ctaLabel: string;
};

export type FaqItem = {
  question: string;
  answer: string;
};

export type SiteConfig = {
  firm: {
    name: string;
    legalName: string;
    tagline: string;
    /** Path under /public — leave as placeholder for now. */
    logoSrc: string;
    /** Alt text for the logo image. */
    logoAlt: string;
  };
  contact: {
    /** TODO: replace with real email. */
    email: string;
    /** TODO: replace with real phone, in display format. */
    phone: string;
    /** TODO: replace with real public website URL. */
    website: string;
    /** Optional postal/mailing address — leave empty to hide. */
    address?: string;
  };
  /** Where the "Log in" link in the header should point. Wired later. */
  loginUrl: string;
  colors: BrandColors;
  nav: { label: string; href: string }[];
  hero: {
    eyebrow: string;
    headline: string;
    subhead: string;
    primaryCta: string;
    secondaryCta: string;
  };
  problem: {
    eyebrow: string;
    headline: string;
    intro: string;
    pains: { title: string; body: string }[];
  };
  howItWorks: {
    eyebrow: string;
    headline: string;
    intro: string;
    steps: { number: string; title: string; body: string }[];
    footnote: string;
  };
  whatYouGet: {
    eyebrow: string;
    headline: string;
    intro: string;
    items: { title: string; body: string }[];
  };
  trust: {
    eyebrow: string;
    headline: string;
    intro: string;
    pillars: { title: string; body: string }[];
  };
  pricing: {
    eyebrow: string;
    headline: string;
    intro: string;
    plans: PricingPlan[];
    footnote: string;
  };
  faq: {
    eyebrow: string;
    headline: string;
    items: FaqItem[];
  };
  finalCta: {
    headline: string;
    subhead: string;
    primaryCta: string;
  };
  footer: {
    /** Short blurb under the firm name in the footer. */
    blurb: string;
    /** Compliance / fine-print line. */
    disclaimer: string;
  };
};

export const siteConfig: SiteConfig = {
  firm: {
    name: "MMFC LLC",
    legalName: "MMFC LLC",
    tagline: "Bookkeeping, financial statements, and tax — done right.",
    // TODO: replace /logo-placeholder.svg with the real MMFC LLC logo.
    logoSrc: "/logo-placeholder.svg",
    logoAlt: "MMFC LLC logo",
  },
  contact: {
    email: "gaurav.malhotra@mmfcllc.com",
    // TODO: replace with the real phone number when available.
    phone: "(555) 123-4567",
    // TODO: replace with the real public website (e.g. www.mmfcllc.com) when ready.
    website: "www.mmfc.example",
    address: "",
  },
  // Live CTAA demo login. Customers should arrive here with the firm /
  // client UUIDs from the welcome email (see docs/CUSTOMER_DEMO_GUIDE.md).
  loginUrl:
    "https://ca-ctax-demo-cus-ui.thankfulmushroom-8b2bd8cf.centralus.azurecontainerapps.io/login",
  colors: {
    primary: "30 39 97", //   #1E2761  deep navy
    primaryDark: "21 28 71", // darker navy for hover / dark surfaces
    accent: "201 162 39", //  #C9A227  gold
    accentDark: "168 134 28",
    surface: "255 255 255", // white
    surfaceAlt: "247 248 251", // very light cool gray
    ink: "30 41 59", //       slate-800 — body text
    inkSoft: "51 65 85", //   slate-700
    inkMuted: "100 116 139", // slate-500
    border: "226 232 240", // slate-200
  },
  nav: [
    { label: "How it works", href: "#how-it-works" },
    { label: "What you get", href: "#what-you-get" },
    { label: "Pricing", href: "#pricing" },
    { label: "FAQ", href: "#faq" },
    { label: "Contact", href: "#contact" },
  ],
  hero: {
    eyebrow: "Bookkeeping · Financial statements · Tax preparation",
    headline: "Spend less time on the books. More time on your business.",
    subhead:
      "MMFC LLC pairs modern AI with experienced CPAs to give small businesses clean books, clear financial statements, and tax-ready records — every month, without the scramble.",
    primaryCta: "Get started",
    secondaryCta: "See how it works",
  },
  problem: {
    eyebrow: "The problem",
    headline: "Running a business is hard enough.",
    intro:
      "Most small-business owners we meet are stuck in the same loop. Sound familiar?",
    pains: [
      {
        title: "The end-of-month scramble",
        body: "Receipts in a shoebox, statements in three different inboxes, and a full evening of data entry before you can even start to think about the numbers.",
      },
      {
        title: "Scattered receipts and statements",
        body: "Cash transactions, card statements, invoicing apps, and a payroll provider — all in different places, none of them talking to each other.",
      },
      {
        title: "Tax-time stress",
        body: "Every spring, the same panic: tracking down a year's worth of records, hoping nothing was missed, and dreading the bill from the accountant.",
      },
      {
        title: "No clear picture of the business",
        body: "You know money came in and money went out, but you don't really know whether you're profitable this quarter — or where the cash actually went.",
      },
    ],
  },
  howItWorks: {
    eyebrow: "How it works",
    headline: "A clean, monthly rhythm — without the chaos.",
    intro:
      "We do the heavy lifting in the background so you get a clear picture every month, not a 12-month surprise at year-end.",
    steps: [
      {
        number: "01",
        title: "Share",
        body: "Upload your receipts, statements, and invoices through your secure client portal, or connect your bank and payroll accounts. Send things in as they arrive — no more end-of-month pile.",
      },
      {
        number: "02",
        title: "We process",
        body: "Our AI organises every document, classifies transactions, and builds up your books in real time. Bank feeds, expenses, invoices, and receipts all land in the right place automatically.",
      },
      {
        number: "03",
        title: "We review and deliver",
        body: "Every deliverable — monthly books, financial statements, tax filings — is reviewed and signed off by a CPA before it reaches you. You get clean results, not an AI experiment.",
      },
    ],
    footnote:
      "AI does the grunt work. A licensed CPA is on every account, reviews every close, and is the one who signs off. You always know a real human stands behind the numbers.",
  },
  whatYouGet: {
    eyebrow: "What you get",
    headline: "Every month, a clear picture of your business.",
    intro:
      "All the financial reports you need to run, finance, and file — delivered on a predictable schedule and ready when you are.",
    items: [
      {
        title: "Profit & Loss statement",
        body: "Know exactly what you earned, what you spent, and what's left — broken down the way that actually makes sense for your business.",
      },
      {
        title: "Balance Sheet",
        body: "A clean snapshot of what you own, what you owe, and the equity in your business — the report every lender and investor will ask for.",
      },
      {
        title: "Cash Flow statement",
        body: "See where your cash actually went each month. No more wondering why profit looks fine but the bank account doesn't.",
      },
      {
        title: "Tax-ready documents",
        body: "Year-end packages prepared for your tax filing, with the supporting schedules and reconciliations your filer needs.",
      },
      {
        title: "Audit-ready records",
        body: "Every transaction tied back to its source document, fully traceable. If you're ever audited or asked for backup, it's already there.",
      },
      {
        title: "Peace of mind",
        body: "No more spreadsheet panic. A CPA-led team owns your books, watches the close, and tells you the moment something needs attention.",
      },
    ],
  },
  trust: {
    eyebrow: "Why MMFC LLC",
    headline: "Modern tools. Human judgment. Real accountability.",
    intro:
      "We use technology where it makes you faster and more accurate — and people where it matters most.",
    pillars: [
      {
        title: "CPA review on every deliverable",
        body: "Nothing leaves our firm without a licensed CPA having reviewed and signed off. AI accelerates the work; CPAs are still accountable for it.",
      },
      {
        title: "Bank-level security & encryption",
        body: "Your documents and books are encrypted at rest and in transit. Access is role-based and every action is logged in a full audit trail.",
      },
      {
        title: "Audit-ready by default",
        body: "Every number on every statement traces back to the originating receipt, invoice, or bank transaction — automatically, all the time.",
      },
      {
        title: "Your data stays private",
        body: "Your records are yours. We never sell your data, and we never use your business records to train third-party AI models.",
      },
    ],
  },
  pricing: {
    eyebrow: "Pricing",
    headline: "Simple monthly plans. Cancel any time.",
    intro:
      "Straightforward pricing, no surprise add-ons. Start where you are today — move up (or down) as your business changes.",
    plans: [
      {
        id: "starter",
        name: "Starter",
        price: "$150",
        priceSuffix: "/mo",
        audience: "Sole proprietors and freelancers",
        features: [
          "Bank and receipt capture",
          "Monthly Profit & Loss statement",
          "Year-end tax documents",
          "Email support",
        ],
        ctaLabel: "Get started",
      },
      {
        id: "business",
        name: "Business",
        price: "$375",
        priceSuffix: "/mo",
        audience: "Growing small businesses",
        features: [
          "Everything in Starter",
          "Full financial statements (P&L, Balance Sheet, Cash Flow)",
          "Quarterly review call with your CPA",
          "Priority tax-season support",
        ],
        featured: true,
        ctaLabel: "Get started",
      },
      {
        id: "premium",
        name: "Premium",
        price: "$750",
        priceSuffix: "/mo",
        audience: "Established and multi-entity",
        features: [
          "Everything in Business",
          "Up to 3 entities consolidated",
          "Monthly review call",
          "Dedicated client specialist",
        ],
        ctaLabel: "Get started",
      },
      {
        id: "enterprise",
        name: "Enterprise",
        price: "Custom",
        audience: "Complex and high-volume",
        features: [
          "Everything in Premium",
          "Unlimited entities",
          "Advisory and tax strategy",
          "Custom SLA and onboarding",
        ],
        ctaLabel: "Talk to us",
      },
    ],
    footnote:
      "All plans include a secure client portal, bank-level encryption, CPA review and sign-off on every deliverable, and the option to save roughly two months by paying annually.",
  },
  faq: {
    eyebrow: "Frequently asked questions",
    headline: "Answers, before you ask.",
    items: [
      {
        question: "Is my data secure?",
        answer:
          "Yes. All documents and financial records are encrypted at rest and in transit, stored in a tenant-isolated environment, and accessible only to the staff assigned to your account. Every action is captured in an audit trail you can review at any time.",
      },
      {
        question: "Do real accountants review my books?",
        answer:
          "Always. Our AI tooling speeds up data capture and transaction classification, but a licensed CPA reviews and signs off on every monthly close, every financial statement, and every tax document before it reaches you. You can speak to a human any time you need to.",
      },
      {
        question: "What do I need to provide?",
        answer:
          "At minimum: read-only access to your business bank and credit-card accounts, your payroll provider details (if any), and the ability to forward receipts and invoices into your client portal. We'll walk you through onboarding step by step — most clients are fully set up in under a week.",
      },
      {
        question: "Can I switch plans?",
        answer:
          "Any time. Upgrade as you grow, or move down if the season is quieter. We don't lock you into long-term contracts, and plan changes take effect on your next billing cycle.",
      },
      {
        question: "How does billing work?",
        answer:
          "Plans are billed monthly to a card or bank account on file. You can switch to annual billing at any time and save roughly two months. Tax-preparation engagements outside your monthly plan are quoted up front before any work begins.",
      },
    ],
  },
  finalCta: {
    headline: "Ready to hand off the books?",
    subhead:
      "Start with a free, no-obligation conversation. We'll review what you have today and recommend the right plan for where your business is heading.",
    primaryCta: "Get started",
  },
  footer: {
    blurb:
      "MMFC LLC is the providing accounting firm. Modern tools, CPA-led service.",
    disclaimer:
      "Tax-preparation support; not a substitute for individualized tax advice. Please consult MMFC LLC about your specific situation.",
  },
};
