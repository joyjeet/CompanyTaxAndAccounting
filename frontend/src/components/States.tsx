import { Body1, Body1Strong, makeStyles, Spinner, tokens } from "@fluentui/react-components";
import { type ReactNode } from "react";

import { ApiError } from "../api/ApiClient";

const useStyles = makeStyles({
  state: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    justifyContent: "center",
    rowGap: "8px",
    padding: "32px",
    color: tokens.colorNeutralForeground3,
    textAlign: "center",
  },
  error: {
    color: tokens.colorPaletteRedForeground1,
    backgroundColor: tokens.colorPaletteRedBackground1,
    padding: "12px 16px",
    borderRadius: tokens.borderRadiusMedium,
    fontFamily: tokens.fontFamilyMonospace,
    fontSize: tokens.fontSizeBase200,
  },
});

export function LoadingState({ label = "Loading…" }: { label?: string }) {
  const styles = useStyles();
  return (
    <div className={styles.state}>
      <Spinner size="medium" label={label} />
    </div>
  );
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  const styles = useStyles();
  return (
    <div className={styles.state}>
      <Body1Strong>{title}</Body1Strong>
      {description && <Body1>{description}</Body1>}
      {action}
    </div>
  );
}

export function ErrorState({ error }: { error: unknown }) {
  const styles = useStyles();
  const msg =
    error instanceof ApiError
      ? `HTTP ${error.status}: ${error.message}`
      : error instanceof Error
        ? error.message
        : String(error);
  return <div className={styles.error}>⚠ {msg}</div>;
}
