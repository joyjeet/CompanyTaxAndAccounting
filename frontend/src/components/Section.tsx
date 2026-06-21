import {
  makeStyles,
  shorthands,
  Text,
  tokens,
  type SlotClassNames,
} from "@fluentui/react-components";
import { type ReactNode } from "react";

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
}

export default function Section({
  title,
  subtitle,
  toolbar,
  children,
  className,
}: SectionProps) {
  const styles = useStyles();
  return (
    <section className={`${styles.root} ${className ?? ""}`.trim()}>
      {(title || toolbar) && (
        <div className={styles.header}>
          <div>
            {title && <Text className={styles.title}>{title}</Text>}
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
