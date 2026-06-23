import {
  Caption1,
  makeStyles,
  shorthands,
  Text,
  tokens,
} from "@fluentui/react-components";
import type { CSSProperties, ReactNode } from "react";

/**
 * Card primitive matching the dashboard reference UI (QuickBooks-style):
 *   • white background, soft border, generous rounded corners
 *   • header with an UPPERCASE OVERLINE label and optional right-side
 *     toolbar (date filter, "i" info, etc.)
 *   • body slot — fully owned by the caller
 *
 * Use this for every tile on the portal home page. For the firm-side, the
 * same primitive works but tone down the header overline.
 */

const useStyles = makeStyles({
  root: {
    backgroundColor: tokens.colorNeutralBackground1,
    ...shorthands.borderRadius("12px"),
    ...shorthands.border("1px", "solid", tokens.colorNeutralStroke2),
    ...shorthands.padding("18px", "20px"),
    boxShadow: tokens.shadow2,
    display: "flex",
    flexDirection: "column",
    minHeight: "120px",
  },
  header: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "flex-start",
    rowGap: "4px",
    marginBottom: "12px",
  },
  overline: {
    color: tokens.colorNeutralForeground3,
    textTransform: "uppercase",
    letterSpacing: "0.08em",
    fontWeight: tokens.fontWeightSemibold,
  },
  subtitle: {
    color: tokens.colorNeutralForeground3,
    marginTop: "2px",
  },
  body: { flex: 1, minWidth: 0 },
  footer: {
    marginTop: "12px",
    paddingTop: "12px",
    ...shorthands.borderTop("1px", "solid", tokens.colorNeutralStroke2),
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
  },
});

export default function DashboardCard({
  overline,
  subtitle,
  toolbar,
  footer,
  children,
  style,
  className,
}: {
  overline?: ReactNode;
  subtitle?: ReactNode;
  /** Right-aligned slot in the header — e.g. a date-range dropdown. */
  toolbar?: ReactNode;
  /** Bottom strip with a divider — e.g. a "View details" link. */
  footer?: ReactNode;
  children: ReactNode;
  style?: CSSProperties;
  className?: string;
}) {
  const styles = useStyles();
  return (
    <div className={`${styles.root} ${className ?? ""}`.trim()} style={style}>
      {(overline || toolbar) && (
        <div className={styles.header}>
          <div>
            {overline && (
              <Caption1 className={styles.overline} block>
                {overline}
              </Caption1>
            )}
            {subtitle && (
              <Text className={styles.subtitle} size={200} block>
                {subtitle}
              </Text>
            )}
          </div>
          {toolbar}
        </div>
      )}
      <div className={styles.body}>{children}</div>
      {footer && <div className={styles.footer}>{footer}</div>}
    </div>
  );
}
