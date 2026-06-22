import { siteConfig } from "../siteConfig";

/**
 * Single sign-up / "Get started" handler used by every CTA on the site.
 *
 * Current wiring: most plans send the visitor straight to the live CTAA
 * demo login so they can try the product immediately using the firm /
 * client UUIDs from their welcome email. The Enterprise plan opens a
 * mailto: instead, because that flow needs a conversation first.
 *
 * To re-wire later (hosted form, POST to back-end, Calendly, etc.) just
 * edit this function — every CTA on the page funnels through it.
 */
export function handleSignup(planId?: string): void {
  // Enterprise = "Talk to us" — always goes to email.
  if (planId === "enterprise") {
    openEnquiryEmail(planId);
    return;
  }
  // Everyone else lands on the demo login.
  window.location.href = siteConfig.loginUrl;
}

function openEnquiryEmail(planId?: string): void {
  const email = siteConfig.contact.email;
  const subjectPlan = planId ? ` — ${planId} plan` : "";
  const subject = encodeURIComponent(`New enquiry${subjectPlan}`);
  const body = encodeURIComponent(
    [
      `Hi ${siteConfig.firm.name} team,`,
      "",
      "I'd like to learn more about your bookkeeping service.",
      planId ? `Plan: ${planId}` : "",
      "",
      "About my business:",
      "- Industry:",
      "- Approximate monthly transactions:",
      "- Number of entities:",
      "- Anything else you should know:",
      "",
      "Thanks!",
    ]
      .filter(Boolean)
      .join("\n"),
  );
  window.location.href = `mailto:${email}?subject=${subject}&body=${body}`;
}
