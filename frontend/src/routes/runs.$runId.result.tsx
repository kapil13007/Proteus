import { createFileRoute } from "@tanstack/react-router";
import { Check, ChevronDown, Download, ExternalLink, X } from "lucide-react";
import { useState } from "react";
import { ActivityFeed } from "@/components/ActivityFeed";
import { DecisionsTable } from "@/components/DecisionsTable";
import { FileViewer } from "@/components/FileViewer";
import { FindingsList } from "@/components/FindingsList";
import { RunMetricsStrip } from "@/components/RunMetricsStrip";
import { Skeleton } from "@/components/Skeleton";
import { StatusPill } from "@/components/StatusPill";
import { useLiveRun } from "@/hooks/use-live-run";
import { bundleUrl } from "@/lib/api";
import { formatDuration } from "@/lib/format";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/runs/$runId/result")({
  head: () => ({
    meta: [
      { title: "Run Result — Mapfl0w" },
      {
        name: "description",
        content: "Audit report, generated code and decision trail for a run.",
      },
      { name: "robots", content: "noindex" },
    ],
  }),
  component: RunResultPage,
});

function Section({
  title,
  defaultOpen = false,
  children,
}: {
  title: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="rounded-lg border bg-card">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-5 py-3.5 text-sm font-medium text-foreground"
        aria-expanded={open}
      >
        <ChevronDown
          className={cn("size-4 text-muted-foreground transition-transform", !open && "-rotate-90")}
        />
        {title}
      </button>
      {open && <div className="border-t px-5 py-4">{children}</div>}
    </div>
  );
}

function RunResultPage() {
  const { runId } = Route.useParams();
  const run = useLiveRun(runId);

  if (!run) {
    return (
      <div className="mx-auto max-w-6xl space-y-4">
        <Skeleton className="h-16" />
        <Skeleton className="h-40" />
        <Skeleton className="h-24" />
      </div>
    );
  }

  const audit = run.audit;
  const publish = run.publish;

  return (
    <div className="mx-auto max-w-6xl space-y-5">
      <header className="flex flex-wrap items-center gap-3">
        <h2 className="font-mono text-base text-foreground">{run.id}</h2>
        <span className="font-mono text-sm text-muted-foreground">
          {run.targetTable} ← {run.sourceTable}
        </span>
        <StatusPill status={run.status} />
        <span className="ml-auto font-mono text-xs text-muted-foreground">
          wall clock incl. review: {formatDuration(run.durationSec)}
        </span>
      </header>

      {audit ? (
        <div className="rounded-lg border bg-card p-5">
          <div className="mb-4 flex flex-wrap items-baseline justify-between gap-2">
            <h3 className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
              Audit — the generated Dataform assertions, run locally
            </h3>
            <span className="font-mono text-xs text-muted-foreground">
              {audit.rowsWritten.toLocaleString("en-US")} rows written
            </span>
          </div>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {audit.checks.map((c) => (
              <div key={c.name} className="rounded-lg border bg-terminal p-4">
                <p className="flex items-center gap-1.5 font-mono text-sm text-foreground">
                  {c.ok ? (
                    <Check className="size-4 text-success" />
                  ) : (
                    <X className="size-4 text-destructive" />
                  )}
                  {c.name}
                </p>
                <p
                  className={cn(
                    "mt-2 text-xs leading-5",
                    c.ok ? "text-muted-foreground" : "text-destructive",
                  )}
                >
                  {c.detail}
                </p>
              </div>
            ))}
          </div>
        </div>
      ) : (
        <div className="rounded-lg border bg-card p-5">
          <p className="text-sm text-muted-foreground">
            {run.status === "rejected"
              ? "No audit — this run was rejected before execution."
              : (run.error ?? "No audit report — the run stopped before execution.")}
          </p>
        </div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border bg-card px-5 py-4">
        <div className="text-sm">
          {publish?.pushed ? (
            <span className="text-foreground">
              Published {publish.files} files to <span className="font-mono">{publish.branch}</span>{" "}
              as commit <span className="font-mono">{publish.sha}</span>
            </span>
          ) : publish ? (
            <span className={publish.skipped ? "text-muted-foreground" : "text-destructive"}>
              {publish.skipped ? "Publish skipped: " : "Publish failed: "}
              {publish.reason}
            </span>
          ) : (
            <span className="text-muted-foreground">Not published.</span>
          )}
        </div>
        <div className="flex gap-2">
          {publish?.url && (
            <a
              href={publish.url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground"
            >
              View commit <ExternalLink className="size-3" />
            </a>
          )}
          {run.files.length > 0 && (
            <a
              href={bundleUrl(run.id)}
              className="inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground"
            >
              <Download className="size-3.5" /> Download files (.zip)
            </a>
          )}
        </div>
      </div>

      {run.metrics.rows && <RunMetricsStrip metrics={run.metrics} />}

      <Section title="Generated files" defaultOpen>
        <FileViewer files={run.files} />
      </Section>

      <Section title={`Mapping decisions (${run.decisions.length})`}>
        <DecisionsTable decisions={run.decisions} />
      </Section>

      <Section title={`Findings (${run.findings.length})`}>
        <FindingsList findings={run.findings} />
      </Section>

      <Section title="Timeline">
        <ActivityFeed entries={run.feed} maxHeight="26rem" />
      </Section>

      <div className="rounded-lg border bg-card p-5">
        <h3 className="mb-4 text-xs font-medium tracking-wide text-muted-foreground uppercase">
          Run metadata
        </h3>
        <dl className="grid gap-x-8 gap-y-3 font-mono text-xs sm:grid-cols-2">
          {[
            ["created by", run.meta.createdBy ?? "—"],
            ["approved by", run.meta.approvedBy ?? "—"],
            ["mappings", `${run.mappingsValidated} validated · ${run.mappingsExcluded} excluded`],
            ["revisions", String(run.revisions.length)],
            ["uploads", run.meta.files.join(", ") || "—"],
          ].map(([k, v]) => (
            <div key={k} className="flex justify-between gap-4">
              <dt className="text-muted-foreground">{k}</dt>
              <dd className="truncate text-right text-foreground">{v}</dd>
            </div>
          ))}
        </dl>
      </div>
    </div>
  );
}
