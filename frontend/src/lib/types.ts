export type RunStatus = "running" | "awaiting_review" | "succeeded" | "failed" | "rejected";

export type EntryKind = "thought" | "tool_call" | "tool_result" | "tool_error";

export interface ActivityEntry {
  id: string;
  ts: string; // HH:MM:SS
  kind: EntryKind;
  text: string;
}

export interface Finding {
  id: string;
  severity: "warning" | "info";
  rows: string;
  message: string;
}

export interface RunAudit {
  rowsWritten: number;
  countsMatch: boolean;
  nullsCheck: boolean;
  failedCheck?: string;
}

export interface RunMeta {
  files: string[];
  llmAttempts: number;
  approvedBy?: string;
  workflowId?: string;
}

export interface Run {
  id: string;
  targetTable: string;
  status: RunStatus;
  mappingsValidated: number;
  mappingsExcluded: number;
  costGb: number | null;
  costUsd: number | null;
  startedAt: number; // epoch ms
  durationSec: number | null;
  /** Index into STEP_LABELS (0–7) of the current/last step. */
  currentStep: number;
  /** Whether the current step failed. */
  stepFailed?: boolean;
  attempt?: { step: number; current: number; max: number };
  feed: ActivityEntry[];
  findings: Finding[];
  sqlx: string;
  sqlxPath: string;
  audit?: RunAudit;
  meta: RunMeta;
}

export const STEP_LABELS = [
  "Parsing inputs",
  "Validating mappings",
  "Generating .sqlx",
  "Verifying (dry run)",
  "Human review",
  "Pushing to GitHub",
  "Executing transformation",
  "Auditing results",
] as const;