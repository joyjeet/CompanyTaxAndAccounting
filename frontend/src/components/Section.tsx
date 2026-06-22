import {
  makeStyles,
  shorthands,
  Text,
  tokens,
  type SlotClassNames,
} from "@fluentui/react-components";
import { type ReactNode } from "react";

import InfoHint from "./InfoHint";

const useStyles = makeStyles({
  root: {
    backgroundColor: tokens.colorNeutralBackground1,
    ...shorthands.borderRadius(tokens.borderRadiusLarge),
    ...shorthands.padding("20px"),
    ...shorthands.border("1px", "solid", tokens.colorNeutralStroke2),
    boxShadow: tokens.shadow2,
  },
  header: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: "16px",
  },
  titleRow: {
    display: "flex",
    alignItems: "center",
    gap: "4px",
  },
  title: {
    fontSize: tokens.fontSizeBase400,
    fontWeight: tokens.fontWeightSemibold,
  },
  subtitle: {
    color: tokens.colorNeutralForeground3,
    fontSize: tokens.fontSizeBase200,
    marginTop: "2px",
  },
});

export type SectionSlots = SlotClassNames<"root">;

interface SectionProps {
  title?: ReactNode;
  subtitle?: ReactNode;
  toolbar?: ReactNode;
  children: ReactNode;
  className?: string;
  /**
   * Optional explainer. Renders a small "i" icon next to the title that
   * opens a Popover with the supplied body.
   */
  help?: { title?: string; body: ReactNode };
}

export default function Section({
  title,
  subtitle,
  toolbar,
  children,
  className,
  help,
}: SectionProps) {
  const styles = useStyles();
  return (
    <section className={`${styles.root} ${className ?? ""}`.trim()}>
      {(title || toolbar) && (
        <div className={styles.header}>
          <div>
            {title && (
              <div className={styles.titleRow}>
                <Text className={styles.title}>{title}</Text>
                {help && <InfoHint title={help.title} body={help.body} />}
              </div>
            )}
            {subtitle && (
              <div className={styles.subtitle}>
                {typeof subtitle === "string" ? subtitle : subtitle}
              </div>
            )}
          </div>
          {toolbar}
        </div>
      )}
      {children}
    </section>
  );
}
