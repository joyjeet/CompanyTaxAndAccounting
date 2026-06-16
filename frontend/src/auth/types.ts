/**
 * Shared types mirroring the backend's `AuthIdentity`. The frontend never
 * trusts these for security decisions — the backend re-validates the JWT
 * on every request — but uses them to render the right UI per role.
 */

export type Role = "firm_staff" | "client_portal";

export interface Identity {
  sub: string;
  firmId: string;
  clientId: string | null;
  role: Role;
  /** Epoch seconds. */
  expiresAt: number;
}

export interface DraftOut {
  id: string;
  source_document_id: string;
  kind: string;
  status: string;
  confidence: string;
  high_confidence: boolean;
  needs_review: boolean;
  model: string;
  prompt_version: string;
  payload: Record<string, unknown>;
}

export interface DocumentOut {
  id: string;
  client_id: string;
  kind: string;
  filename: string | null;
  content_type: string | null;
  sha256: string;
  ocr_status: string;
  ocr_completed_at: string | null;
  ocr_error: string | null;
  received_at: string;
}

export interface ClientOut {
  id: string;
  firm_id: string;
  name: string;
  external_code: string | null;
}

export interface UploadOut {
  source_document_id: string;
  storage_uri: string;
  sha256: string;
  deduped: boolean;
  job_id: string | null;
}
