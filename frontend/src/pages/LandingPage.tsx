/**
 * Public landing page — the front door for both audiences.
 *
 * The two buttons are a *routing* decision, not an authorization one: they
 * pick which identity authority to redirect to (workforce Entra ID for staff,
 * Entra External ID for clients). What you can actually see is decided by
 * your membership record, server-side, on every request. A client who clicks
 * "Firm sign-in" gets a client portal anyway.
 */
import {
  Body1,
  Button,
  Caption1,
  Link,
  Subtitle1,
  Text,
  Title1,
  makeStyles,
  shorthands,
  tokens,
} from "@fluentui/react-components";
import {
  BuildingBankRegular,
  CheckmarkCircleRegular,
  PersonRegular,
} from "@fluentui/react-icons";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";
import config, { type Audience } from "../config";

const useStyles = makeStyles({
  page: {
    minHeight: "100vh",
    display: "grid",
    gridTemplateRows: "auto 1fr auto",
    backgroundColor: tokens.colorNeutralBackground2,
  },
  header: {
    display: "flex",
    alignItems: "center",
    columnGap: "12px",
    ...shorthands.padding("20px", "32px"),
  },
  brandMark: {
    width: "36px",
    height: "36px",
    ...shorthands.borderRadius(tokens.borderRadiusMedium),
    backgroundColor: tokens.colorBrandBackground,
    color: tokens.colorNeutralForegroundOnBrand,
    display: "grid",
    placeItems: "center",
    fontWeight: tokens.fontWeightBold,
  },
  main: {
    display: "grid",
    placeItems: "center",
    ...shorthands.padding("16px", "32px", "48px"),
  },
  inner: {
    width: "100%",
    maxWidth: "980px",
    display: "grid",
    rowGap: "32px",
  },
  hero: {
    textAlign: "center",
    display: "grid",
    rowGap: "12px",
    justifyItems: "center",
  },
  heroText: {
    maxWidth: "620px",
    color: tokens.colorNeutralForeground2,
  },
  choices: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))",
    columnGap: "24px",
    rowGap: "24px",
  },
  card: {
    backgroundColor: tokens.colorNeutralBackground1,
    ...shorthands.padding("28px"),
    ...shorthands.borderRadius(tokens.borderRadiusLarge),
    ...shorthands.border("1px", "solid", tokens.colorNeutralStroke2),
    boxShadow: tokens.shadow8,
    display: "grid",
    rowGap: "12px",
    alignContent: "start",
  },
  icon: {
    width: "44px",
    height: "44px",
    ...shorthands.borderRadius(tokens.borderRadiusCircular),
    backgroundColor: tokens.colorBrandBackground2,
    color: tokens.colorBrandForeground2,
    display: "grid",
    placeItems: "center",
    fontSize: "22px",
  },
  bullets: {
    display: "grid",
    rowGap: "6px",
    ...shorthands.margin("4px", "0", "8px"),
  },
  bullet: {
    display: "flex",
    alignItems: "center",
    columnGap: "8px",
    color: tokens.colorNeutralForeground2,
  },
  tick: { color: tokens.colorPaletteGreenForeground1 },
  footer: {
    textAlign: "center",
    ...shorthands.padding("0", "32px", "24px"),
    color: tokens.colorNeutralForeground3,
  },
  error: {
    color: tokens.colorPaletteRedForeground1,
    fontSize: tokens.fontSizeBase200,
    textAlign: "center",
  },
});

interface Choice {
  audience: Audience;
  title: string;
  blurb: string;
  cta: string;
  icon: JSX.Element;
  bullets: string[];
}

const CHOICES: Choice[] = [
  {
    audience: "firm",
    title: "Accounting firm",
    blurb:
      "For CPAs, bookkeepers and firm staff. Work across your whole client book.",
    cta: "Sign in to your firm",
    icon: <BuildingBankRegular />,
    bullets: [
      "Review queue and bookkeeping drafts",
      "Financial statements and tax forms",
      "Team and client administration",
    ],
  },
  {
    audience: "client",
    title: "Client portal",
    blurb:
      "For business owners working with a firm. See only your own company.",
    cta: "Sign in to your portal",
    icon: <PersonRegular />,
    bullets: [
      "Upload receipts, bills and statements",
      "Track what your accountant still needs",
      "Download finished reports",
    ],
  },
];

export default function LandingPage() {
  const styles = useStyles();
  const navigate = useNavigate();
  const { signIn } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<Audience | null>(null);

  const start = async (audience: Audience) => {
    setError(null);
    setBusy(audience);
    try {
      await signIn(audience);
      // Dev mode has no external authority to redirect to; fall through to the
      // local sign-in form, which still needs a firm/client picked by hand.
      if (config.authMode !== "msal") {
        navigate(`/login?as=${audience}`, { replace: false });
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div className={styles.brandMark}>C</div>
        <div>
          <Text size={500} weight="semibold">
            CTAA
          </Text>
          <Caption1 block style={{ color: tokens.colorNeutralForeground3 }}>
            Company Tax &amp; Accounting
          </Caption1>
        </div>
      </header>

      <main className={styles.main}>
        <div className={styles.inner}>
          <div className={styles.hero}>
            <Title1>Welcome back</Title1>
            <Body1 className={styles.heroText}>
              One portal for your practice and the businesses you serve. Choose
              how you work with us — we&apos;ll take you to the right sign-in.
            </Body1>
          </div>

          <div className={styles.choices}>
            {CHOICES.map((choice) => (
              <section key={choice.audience} className={styles.card}>
                <div className={styles.icon}>{choice.icon}</div>
                <Subtitle1>{choice.title}</Subtitle1>
                <Body1 style={{ color: tokens.colorNeutralForeground2 }}>
                  {choice.blurb}
                </Body1>
                <div className={styles.bullets}>
                  {choice.bullets.map((b) => (
                    <div key={b} className={styles.bullet}>
                      <CheckmarkCircleRegular className={styles.tick} />
                      <Caption1>{b}</Caption1>
                    </div>
                  ))}
                </div>
                <Button
                  appearance={choice.audience === "firm" ? "primary" : "secondary"}
                  size="large"
                  disabled={busy !== null}
                  onClick={() => void start(choice.audience)}
                >
                  {busy === choice.audience ? "Redirecting…" : choice.cta}
                </Button>
              </section>
            ))}
          </div>

          {error && <p className={styles.error}>{error}</p>}
        </div>
      </main>

      <footer className={styles.footer}>
        <Caption1>
          Not sure which to pick? Your accountant sent your invite — use{" "}
          <strong>Client portal</strong>. Need help?{" "}
          <Link href="mailto:support@ctaa.example">Contact support</Link>.
        </Caption1>
      </footer>
    </div>
  );
}
