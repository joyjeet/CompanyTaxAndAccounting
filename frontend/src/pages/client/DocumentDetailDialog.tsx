/**
 * Read-only "view what's in this upload" dialog so reviewers can cross-check
 * the numbers the classifier extracted against the original file. Surfaces:
 *   - File metadata (name, size, sha, content-type, OCR status)
 *   - OCR text + extracted fields with per-field confidence
 *   - The drafts and journal entries derived from this document
 *   - "Open original" — opens the raw file bytes in a new tab
 *
 * Reads-only: this component never mutates server state.
 */
import {
  Badge,
  Body1,
  Button,
  Caption1,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  makeStyles,
  Spinner,
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableHeaderCell,
  TableRow,
  tokens,
} from "@fluentui/react-components";
import { OpenRegular } from "@fluentui/react-icons";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { useApi } from "../../api/useApi";
import { ErrorState, LoadingState } from "../../components/States";
import { fmtBytes, fmtDateTime, shortId } from "../../lib/format";

const useStyles = makeStyles({
  ocrText: {
    backgroundColor: tokens.colorNeutralBackground2,
    padding: "10px 12px",
    borderRadius: tokens.borderRadiusMedium,
    fontFamily: tokens.fontFamilyMonospace,
    fontSize: tokens.fontSizeBase200,
    maxHeight: "180px",
    overflow: "auto",
    whiteSpace: "pre-wrap",
  },
  meta: {
    display: "grid",
    gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
    columnGap: "16px",
    rowGap: "4px",
    fontSize: tokens.fontSizeBase200,
  },
  sectionLabel: {
    marginTop: "12px",
    marginBottom: "4px",
    fontWeight: 600,
  },
});

const OCR_COLORS: Record<
  string,
  "success" | "warning" | "danger" | "informative"
> = {
  complete: "success",
  failed: "danger",
  in_progress: "warning",
  pending: "informative",
};

interface Props {
  documentId: string | null;
  onClose: () => void;
}

export default function DocumentDetailDialog({ documentId, onClose }: Props) {
  const styles = useStyles();
  const api = useApi();
  const navigate = useNavigate();
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);

  const detail = useQuery({
    queryKey: ["document-detail", documentId],
    queryFn: () => api.getDocument(documentId!),
    enabled: !!documentId,
    // Poll while OCR is still running so the fields show up automatically.
    refetchInterval: (q) => {
      const s = q.state.data?.ocr_status;
      return s === "pending" || s === "in_progress" ? 2000 : false;
    },
  });

  // Free the object URL when the dialog closes or the doc changes.
  useEffect(() => {
    return () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl);
    };
  }, [previewUrl]);

  useEffect(() => {
    // Reset preview when switching docs.
    setPreviewUrl((u) => {
      if (u) URL.revokeObjectURL(u);
      return null;
    });
    setPreviewError(null);
  }, [documentId]);

  const openOriginal = async () => {
    if (!documentId) return;
    setPreviewLoading(true);
    setPreviewError(null);
    try {
      const blob = await api.downloadDocumentBlob(documentId);
      const url = URL.createObjectURL(blob);
      setPreviewUrl(url);
      window.open(url, "_blank", "noopener,noreferrer");
    } catch (e) {
      setPreviewError(e instanceof Error ? e.message : String(e));
    } finally {
      setPreviewLoading(false);
    }
  };

  const open = documentId !== null;

  return (
    <Dialog open={open} onOpenChange={(_, d) => !d.open && onClose()}>
      <DialogSurface style={{ maxWidth: 880 }}>
        <DialogBody>
          <DialogTitle>Document detail</DialogTitle>
          <DialogContent>
            {detail.isLoading && <LoadingState />}
            {detail.error && <ErrorState error={detail.error} />}
            {detail.data && (
              <div>
                <div className={styles.meta}>
                  <div>
                    <Caption1>Filename</Caption1>
                    <Body1 block>{detail.data.filename ?? "(no name)"}</Body1>
                  </div>
                  <div>
                    <Caption1>Kind</Caption1>
                    <Body1 block>{detail.data.kind}</Body1>
                  </div>
                  <div>
                    <Caption1>Content type</Caption1>
                    <Body1 block>{detail.data.content_type ?? "—"}</Body1>
                  </div>
                  <div>
                    <Caption1>Size</Caption1>
                    <Body1 block>
                      {detail.data.size_bytes != null
                        ? fmtBytes(detail.data.size_bytes)
                        : "—"}
                    </Body1>
                  </div>
                  <div>
                    <Caption1>SHA-256</Caption1>
                    <Body1 block>
                      <code>{shortId(detail.data.sha256)}</code>
                    </Body1>
                  </div>
                  <div>
                    <Caption1>OCR</Caption1>
                    <Body1 block>
                      <Badge
                        appearance="tint"
                        color={OCR_COLORS[detail.data.ocr_status] ?? "informative"}
                      >
                        {detail.data.ocr_status}
                      </Badge>
                      {detail.data.ocr_error && (
                        <span style={{ marginLeft: 8, color: tokens.colorPaletteRedForeground1 }}>
                          {detail.data.ocr_error}
                        </span>
                      )}
                    </Body1>
                  </div>
                  <div>
                    <Caption1>Received</Caption1>
                    <Body1 block>{fmtDateTime(detail.data.received_at)}</Body1>
                  </div>
                  <div>
                    <Caption1>Uploaded by</Caption1>
                    <Body1 block>{detail.data.uploaded_by ?? "—"}</Body1>
                  </div>
                </div>

                <div className={styles.sectionLabel}>OCR extracted fields</div>
                {detail.data.extracted?.fields && detail.data.extracted.fields.length > 0 ? (
                  <Table size="extra-small">
                    <TableHeader>
                      <TableRow>
                        <TableHeaderCell>Field</TableHeaderCell>
                        <TableHeaderCell>Value</TableHeaderCell>
                        <TableHeaderCell>OCR conf.</TableHeaderCell>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {detail.data.extracted.fields.map((f, i) => (
                        <TableRow key={i}>
                          <TableCell><code>{f.name}</code></TableCell>
                          <TableCell>{f.value}</TableCell>
                          <TableCell>
                            {typeof f.confidence === "number"
                              ? `${(f.confidence * 100).toFixed(0)}%`
                              : "—"}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                ) : (
                  <Caption1 style={{ color: tokens.colorNeutralForeground3 }}>
                    No structured fields extracted.
                  </Caption1>
                )}

                <div className={styles.sectionLabel}>OCR text</div>
                {detail.data.extracted?.text ? (
                  <div className={styles.ocrText}>{detail.data.extracted.text}</div>
                ) : (
                  <Caption1 style={{ color: tokens.colorNeutralForeground3 }}>
                    No text extracted yet.
                  </Caption1>
                )}

                <div className={styles.sectionLabel}>
                  Drafts derived from this document ({detail.data.drafts.length})
                </div>
                {detail.data.drafts.length === 0 ? (
                  <Caption1 style={{ color: tokens.colorNeutralForeground3 }}>
                    None yet.
                  </Caption1>
                ) : (
                  <Table size="extra-small">
                    <TableHeader>
                      <TableRow>
                        <TableHeaderCell>Draft</TableHeaderCell>
                        <TableHeaderCell>Kind</TableHeaderCell>
                        <TableHeaderCell>Status</TableHeaderCell>
                        <TableHeaderCell>Conf.</TableHeaderCell>
                        <TableHeaderCell></TableHeaderCell>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {detail.data.drafts.map((d) => (
                        <TableRow key={d.id}>
                          <TableCell><code>{shortId(d.id)}</code></TableCell>
                          <TableCell>{d.kind}</TableCell>
                          <TableCell>{d.status}</TableCell>
                          <TableCell>
                            {(Number.parseFloat(d.confidence) * 100).toFixed(0)}%
                          </TableCell>
                          <TableCell>
                            <Button
                              size="small"
                              appearance="subtle"
                              onClick={() => {
                                onClose();
                                navigate(`/review/${d.id}`);
                              }}
                            >
                              Open
                            </Button>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                )}

                <div className={styles.sectionLabel}>
                  Journal entries posted from this document ({detail.data.journal_entries.length})
                </div>
                {detail.data.journal_entries.length === 0 ? (
                  <Caption1 style={{ color: tokens.colorNeutralForeground3 }}>
                    None yet.
                  </Caption1>
                ) : (
                  <Table size="extra-small">
                    <TableHeader>
                      <TableRow>
                        <TableHeaderCell>Entry</TableHeaderCell>
                        <TableHeaderCell>Date</TableHeaderCell>
                        <TableHeaderCell>Memo</TableHeaderCell>
                        <TableHeaderCell>Status</TableHeaderCell>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {detail.data.journal_entries.map((e) => (
                        <TableRow key={e.id}>
                          <TableCell><code>{shortId(e.id)}</code></TableCell>
                          <TableCell>{e.entry_date}</TableCell>
                          <TableCell>{e.memo ?? "—"}</TableCell>
                          <TableCell>{e.status}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                )}

                {previewError && (
                  <div
                    style={{
                      marginTop: 12,
                      color: tokens.colorPaletteRedForeground1,
                    }}
                  >
                    {previewError}
                  </div>
                )}
              </div>
            )}
          </DialogContent>
          <DialogActions>
            <Button
              appearance="secondary"
              icon={previewLoading ? <Spinner size="tiny" /> : <OpenRegular />}
              disabled={previewLoading || !detail.data}
              onClick={openOriginal}
            >
              Open original file
            </Button>
            <Button appearance="primary" onClick={onClose}>
              Close
            </Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}
