/**
 * Small inline "i" icon that opens a Popover with explainer copy.
 *
 * Use this anywhere we want a low-noise help affordance next to a section
 * title, form label, or column header.
 *
 *   <InfoHint
 *     title="What is this?"
 *     body={<>Free-form ReactNode. Keep it to 1–3 short paragraphs.</>}
 *   />
 *
 * Renders a 16px button-icon; the Popover anchors below it.
 */
import {
  Body2,
  Button,
  makeStyles,
  Popover,
  PopoverSurface,
  PopoverTrigger,
  Text,
  tokens,
} from "@fluentui/react-components";
import { InfoRegular } from "@fluentui/react-icons";
import { type ReactNode } from "react";

const useStyles = makeStyles({
  trigger: {
    minWidth: "auto",
    paddingTop: 0,
    paddingBottom: 0,
    paddingLeft: "2px",
    paddingRight: "2px",
    color: tokens.colorNeutralForeground3,
    verticalAlign: "middle",
  },
  surface: {
    maxWidth: "360px",
    padding: "12px 14px",
  },
  title: {
    display: "block",
    marginBottom: "4px",
    fontWeight: tokens.fontWeightSemibold,
  },
  body: {
    color: tokens.colorNeutralForeground2,
  },
});

export interface InfoHintProps {
  /** Short title shown at the top of the popover. */
  title?: string;
  /** Body content — string or ReactNode. Keep short. */
  body: ReactNode;
  /** Override the screen-reader label for the trigger button. */
  ariaLabel?: string;
}

export default function InfoHint({ title, body, ariaLabel }: InfoHintProps) {
  const styles = useStyles();
  const label = ariaLabel ?? (title ? `Help: ${title}` : "Help");
  return (
    <Popover withArrow positioning="below-start">
      <PopoverTrigger disableButtonEnhancement>
        <Button
          appearance="transparent"
          size="small"
          icon={<InfoRegular />}
          aria-label={label}
          className={styles.trigger}
        />
      </PopoverTrigger>
      <PopoverSurface className={styles.surface}>
        {title && <Text className={styles.title}>{title}</Text>}
        <Body2 className={styles.body}>{body}</Body2>
      </PopoverSurface>
    </Popover>
  );
}
