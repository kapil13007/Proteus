import { createFileRoute } from "@tanstack/react-router";
import { Check, ChevronDown, ExternalLink, X } from "lucide-react";
import { useState } from "react";
import { ActivityFeed } from "@/components/ActivityFeed";
import { CodeBlock } from "@/components/CodeBlock";
import { Skeleton } from "@/components/Skeleton";
import { StatusPill } from "@/components/StatusPill";
import { formatDuration } from "@/lib/format";
import { useLiveRun } from "@/hooks/use-live-run";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/runs/$runId/result")({
  head: () => ({
    meta: [
      { title: "Run Result — Mapfl0w" },
      { name: "description", content: "Audit report and generated code for a finished run." },
      { name: "robots", content: "noindex" },
    ],
  }),
  component: RunResultPage,
});

function Section({
  title,
  action,
  defaultOpen = false,
  children,
}: {
  title: string;
  action?: React.ReactNode;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="rounded-lg border bg-card">
      <div className="flex items-center justify-between px-5 py-3.5">
        <button
          onClick={() => setOpen((v) => !v)}
          className="flex items-center gap-2 text-sm font-medium text-foreground"
          aria-expanded={open}
        >
          <ChevronDown
            className={cn("size-4 text-muted-foreground transition-transform", !open && "-rotate-90")}
          />
          {title}
        </button>
        {action}
      </div>
      {open && <div className="border-t px-5 py-4">{children}</div>}
    </div>
  );
}

function AuditStat({
  value,
  label,
  ok,
  failText,
}: {
  value: string;
  label: string;
  ok: boolean;
  failText?: string;
}) {
  return (
    <div className="rounded-lg border bg-terminal p-5">
      <p className={cn("font-mono text-2xl", ok ? "text-foreground" : "text-destructive")}>{value}</p>
      <p className="mt-2 flex items-center gap-1.5 text-xs text-muted-foreground">
        {ok ? <Check className="size-3.5 text-success" /> : <X className="size-3.5 text-destructive" />}
        {label}
      </p>
      {!ok && failText && <p className="mt-2 text-xs leading-5 text-destructive">{failText}</p>}
    </div>
  );
}

function RunResultPage() {
  const { runId } = Route.useParams();
  const run = useLiveRun(runId);

  if (!run) {
    return (
      <div className="mx-auto max-w-4xl space-y-4">
        <Skeleton className="h-16" />
        <Skeleton className="h-40" />
        <Skeleton className="h-24" />
      </div>
    );
  }

  const audit = run.audit;

  return (
    <div className="mx-auto max-w-4xl space-y-5">
      <header className="flex flex-wrap items-center gap-3">
        <h2 className="font-mono text-base text-foreground">{run.id}</h2>
        <span className="font-mono text-sm text-muted-foreground">{run.targetTable}</span>
        <StatusPill status={run.status} />
        <span className="ml-auto font-mono text-xs text-muted-foreground">
          duration: {formatDuration(run.durationSec)}
        </span>
      </header>

      {audit ? (
        <div className="rounded-lg border bg-card p-5">
          <h3 className="mb-4 text-xs font-medium tracking-wide text-muted-foreground uppercase">
            Audit report
          </h3>
          <div className="grid gap-4 sm:grid-cols-3">
            <AuditStat
              value={audit.rowsWritten.toLocaleString("en-US")}
              label="rows written"
              ok
            />
            <AuditStat
              value={audit.countsMatch ? "match" : "mismatch"}
              label="row counts"
              ok={audit.countsMatch}
              failText={!audit.countsMatch ? audit.failedCheck : undefined}
            />
            <AuditStat
              value={audit.nullsCheck ? "0 nulls" : "nulls found"}
              label="required columns"
              ok={audit.nullsCheck}
              failText={audit.nullsCheck ? undefined : audit.failedCheck}
            />
          </div>
        </div>
      ) : (
        <div className="rounded-lg border bg-card p-5">
          <p className="text-sm text-muted-foreground">
            {run.status === "rejected"
              ? "No audit — this run was sent back to the agent before execution."
              : "No audit report — the run stopped before the audit step."}
          </p>
        </div>
      )}

      <Section
        title="Generated code"
        action={
          <a
            href="https://github.com/kapil13007/dataform-models"
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground"
          >
            View on GitHub
            <ExternalLink className="size-3" />
          </a>
        }
      >
        <p className="mb-2 font-mono text-xs text-muted-foreground">{run.sqlxPath}</p>
        <CodeBlock code={run.sqlx} className="max-h-[480px]" />
      </Section>

      <Section title="Timeline">
        <ActivityFeed entries={run.feed} maxHeight="26rem" />
      </Section>

      <div className="rounded-lg border bg-card p-5">
        <h3 className="mb-4 text-xs font-medium tracking-wide text-muted-foreground uppercase">
          Run metadata
        </h3>
        <dl className="grid gap-x-8 gap-y-3 font-mono text-xs sm:grid-cols-2">
          <div className="flex justify-between gap-4">
            <dt className="text-muted-foreground">files uploaded</dt>
            <dd className="text-right text-foreground">{run.meta.files.length}</dd>
          </div>
          <div className="flex justify-between gap-4">
            <dt className="text-muted-foreground">LLM attempts</dt>
            <dd className="text-foreground">{run.meta.llmAttempts}</dd>
          </div>
          <div className="flex justify-between gap-4">
            <dt className="text-muted-foreground">dry-run cost</dt>
            <dd className="text-foreground">
              {run.costGb !== null ? `${run.costGb} GB · $${run.costUsd}` : "—"}
            </dd>
          </div>
          <div className="flex justify-between gap-4">
            <dt className="text-muted-foreground">LLM cost</dt>
            <dd className="text-foreground">
              {((run.meta.llmPromptTokens ?? 0) + (run.meta.llmCompletionTokens ?? 0)).toLocaleString("en-US")} tokens
              {" · $"}
              {(run.meta.llmCostUsd ?? 0).toFixed(4)}
            </dd>
          </div>
          <div className="flex justify-between gap-4">
            <dt className="text-muted-foreground">created by</dt>
            <dd className="text-foreground">{run.meta.createdBy ?? "—"}</dd>
          </div>
          <div className="flex justify-between gap-4">
            <dt className="text-muted-foreground">approved by</dt>
            <dd className="text-foreground">{run.meta.approvedBy ?? "—"}</dd>
          </div>
          <div className="flex justify-between gap-4">
            <dt className="text-muted-foreground">Dataform workflow</dt>
            <dd className="text-foreground">{run.meta.workflowId ?? "—"}</dd>
          </div>
          <div className="flex justify-between gap-4">
            <dt className="text-muted-foreground">uploads</dt>
            <dd className="truncate text-right text-foreground">{run.meta.files.join(", ")}</dd>
          </div>
        </dl>
      </div>
    </div>
  );
}