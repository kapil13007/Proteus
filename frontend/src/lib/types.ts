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
  severity: "error" | "warning" | "info";
  rows: string;
  message: string;
}

/** How a target column is built. Everything but "llm" is decided without tokens. */
export type Method = "direct" | "cast" | "sql_logic" | "udf" | "llm" | "reviewer";
/** Who made the decision: the rule engine, the LLM, the verified-answer cache, or a human. */
export type Origin = "rule" | "llm" | "cache" | "reviewer";

export interface Example {
  in: Record<string, string | null>;
  out: string | null;
}

export interface Decision {
  row: number; // spreadsheet row in the STTM
  targetField: string;
  targetType: string;
  sourceField: string;
  sourceType: string;
  rule: string;
  sqlLogic: string;
  lookup: string;
  default: string;
  sample: string;
  method: Method;
  origin: Origin;
  udf: { name: string; args: string[] } | null;
  sql: string | null;
  rationale: string;
  status: "needs_llm" | "pending" | "ok" | "failed";
  error: string | null;
  attempts: number;
  repaired: boolean;
  template: string;
  expression: string; // what the process step contains (SQLX)
  compiled: string; // after expanding UDFs (BigQuery SQL)
  outputType: string | null;
  examples: Example[];
  nullsIntroduced: { count: number; of: number; examples: string[] } | null;
  udfsUsed: string[];
}

export type FileKind =
  "declaration" | "source_params" | "target_params" | "read" | "process" | "write";

export interface GeneratedFile {
  path: string;
  kind: FileKind;
  description: string;
  content: string;
}

export interface AuditCheck {
  name: string;
  ok: boolean;
  detail: string;
}

export interface RunAudit {
  rowsWritten: number;
  sourceRows: number;
  countsMatch: boolean;
  nullsCheck: boolean;
  failedCheck: string | null;
  checks: AuditCheck[];
}

export interface RunMetrics {
  timingsMs?: Record<string, number>;
  llm?: {
    calls: number;
    promptTokens: number;
    completionTokens: number;
    cachedTokens: number;
    reasoningTokens: number;
    latencyMs: number;
    costUsd: number;
    rowsSent: number;
  };
  scan?: { readBytes: number; fullBytes: number; readColumns: number; totalColumns: number };
  rows?: {
    total: number;
    deterministic: number;
    llm: number;
    cached: number;
    reviewer: number;
    failed: number;
    usingUdfs: number;
  };
}

export interface RunMeta {
  files: string[];
  createdBy?: string;
  approvedBy?: string;
  rejectFeedback?: string;
}

export interface PublishResult {
  pushed: boolean;
  skipped: boolean;
  reason?: string;
  sha?: string;
  url?: string;
  branch?: string;
  files?: number;
}

export interface Revision {
  by: string;
  at: number;
  feedback: string;
  overrides: number[];
  changedRows: number[];
}

export interface Conventions {
  layerDir?: string;
  functionsPath?: string;
  envVarsPath?: string;
  sourceParamsDir?: string;
  targetParamsDir?: string;
  declarationsDir?: string;
  evidence?: string[];
}

export interface UdfEntry {
  name: string;
  arity: number;
  params: { name: string; default: string | null }[];
  example: string | null;
  error: string | null;
  description: string;
  kind: "column" | "table";
}

export interface RunSummary {
  id: string;
  sourceTable: string;
  targetTable: string;
  status: RunStatus;
  mappingsValidated: number;
  mappingsExcluded: number;
  startedAt: number; // epoch ms
  durationSec: number | null;
  /** Index into STEP_LABELS (0–7) of the current/last step. */
  currentStep: number;
  stepFailed: boolean;
  metrics: RunMetrics;
  meta: RunMeta;
}

export interface Run extends RunSummary {
  error: string | null;
  attempt: { step: number; current: number; max: number } | null;
  feed: ActivityEntry[];
  findings: Finding[];
  decisions: Decision[];
  files: GeneratedFile[];
  preview: { columns?: string[]; types?: string[]; rows?: (string | null)[][] };
  conventions: Conventions;
  udfCatalog: UdfEntry[];
  audit: RunAudit | null;
  publish: PublishResult | null;
  revisions: Revision[];
}

export interface SystemStatus {
  llm: {
    provider: string;
    model: string;
    configured: boolean;
    reasoningEffort: string;
    rowsPerCall: number;
    cache: boolean;
    listPricePer1M: { input: number; cachedInput: number; output: number };
  };
  warehouse: {
    engine: string;
    path: string;
    tables: string[];
    targetDialect: string;
    sampleRows: number;
  };
  appDb: { engine: string };
  github: { configured: boolean; repo: string; branch: string };
  cache: { entries: number; hits: number };
  limits: { maxAttempts: number };
}

export const STEP_LABELS = [
  "Parsing inputs",
  "Validating mappings",
  "Generating code",
  "Verifying (sandbox dry run)",
  "Human review",
  "Executing (local warehouse)",
  "Auditing results",
  "Publishing",
] as const;
