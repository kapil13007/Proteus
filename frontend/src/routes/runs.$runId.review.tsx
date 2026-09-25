import { Link, createFileRoute, useNavigate } from "@tanstack/react-router";
import { AlertTriangle, ArrowRight, Download, Loader2 } from "lucide-react";
import { useState } from "react";
import { ConventionsPanel } from "@/components/ConventionsPanel";
import { DecisionsTable } from "@/components/DecisionsTable";
import { FileViewer } from "@/components/FileViewer";
import { FindingsList } from "@/components/FindingsList";
import { Modal } from "@/components/Modal";
import { PreviewTable } from "@/components/PreviewTable";
import { RunMetricsStrip } from "@/components/RunMetricsStrip";
import { Skeleton } from "@/components/Skeleton";
import { StatusPill } from "@/components/StatusPill";
import { useLiveRun } from "@/hooks/use-live-run";
import { useSystemStatus } from "@/hooks/use-system-status";
import { approveRun, bundleUrl, rejectRun, reviseRun } from "@/lib/api";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/runs/$runId/review")({
  head: () => ({
    meta: [
      { title: "Review — Mapfl0w" },
      { name: "description", content: "Review every mapping decision before it runs." },
      { name: "robots", content: "noindex" },
    ],
  }),
  component: ReviewPage,
});

type Tab = "decisions" | "files" | "preview" | "conventions";

const TABS: { id: Tab; label: string }[] = [
  { id: "decisions", label: "Mapping decisions" },
  { id: "files", label: "Generated files" },
  { id: "preview", label: "Sandbox preview" },
  { id: "conventions", label: "Conventions & UDFs" },
];

function ReviewPage() {
  const { runId } = Route.useParams();
  const navigate = useNavigate();
  const run = useLiveRun(runId);
  const system = useSystemStatus();
  const [tab, setTab] = useState<Tab>("decisions");
  const [overrides, setOverrides] = useState<Record<number, string>>({});
  const [modal, setModal] = useState<"approve" | "revise" | "reject" | null>(null);
  const [feedback, setFeedback] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!run) {
    return (
      <div className="mx-auto max-w-7xl space-y-4">
        <Skeleton className="h-24" />
        <Skeleton className="h-[480px]" />
      </div>
    );
  }

  if (run.status !== "awaiting_review") {
    return (
      <div className="mx-auto max-w-2xl rounded-lg border bg-card p-6">
        <p className="text-sm text-foreground">
          This run is <span className="font-mono">{run.status.replace("_", " ")}</span> — there is
          nothing to review right now.
        </p>
        <Link
          to={run.status === "running" ? "/runs/$runId" : "/runs/$runId/result"}
          params={{ runId }}
          className="mt-4 inline-flex items-center gap-1.5 text-sm text-primary hover:underline"
        >
          {run.status === "running" ? "Watch the agent" : "See the result"}
          <ArrowRight className="size-3.5" />
        </Link>
      </div>
    );
  }

  const blocked = run.decisions.filter((d) => d.status !== "ok");
  const pending = Object.entries(overrides)
    .filter(([, v]) => v.trim())
    .map(([row, expression]) => ({ row: Number(row), expression }));

  function setOverride(row: number, expression: string | null) {
    setOverrides((prev) => {
      const next = { ...prev };
      if (expression === null) delete next[row];
      else next[row] = expression;
      return next;
    });
  }

  async function act(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      navigate({ to: "/runs/$runId", params: { runId } });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  }

  const github = system.data?.github;

  return (
    <div className="mx-auto max-w-7xl space-y-5 pb-24">
      <header className="flex flex-wrap items-center gap-3">
        <h2 className="font-mono text-base text-foreground">{run.id}</h2>
        <span className="font-mono text-sm text-muted-foreground">
          {run.targetTable} ← {run.sourceTable}
        </span>
        <StatusPill status={run.status} />
        <a
          href={bundleUrl(run.id)}
          className="ml-auto inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground"
        >
          <Download className="size-3.5" /> Download files (.zip)
        </a>
      </header>

      {blocked.length > 0 && (
        <div className="flex items-start gap-3 rounded-lg border border-destructive/50 bg-destructive/10 px-4 py-3">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-destructive" />
          <p className="text-sm text-foreground">
            {blocked.length} column(s) could not be generated automatically (STTM row
            {blocked.length > 1 ? "s" : ""} {blocked.map((d) => d.row).join(", ")}). Use{" "}
            <span className="font-medium">Fix</span> to write the expression yourself, or{" "}
            <span className="font-medium">Revise</span> with feedback for the agent. Approval
            unlocks once every column passes the sandbox.
          </p>
        </div>
      )}

      <RunMetricsStrip metrics={run.metrics} />

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_320px]">
        <section className="min-w-0">
          <div className="mb-4 flex flex-wrap gap-1 border-b">
            {TABS.map((t) => (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                className={cn(
                  "-mb-px border-b-2 px-3 py-2 text-sm transition-colors",
                  tab === t.id
                    ? "border-primary text-foreground"
                    : "border-transparent text-muted-foreground hover:text-foreground",
                )}
              >
                {t.label}
              </button>
            ))}
          </div>
          {tab === "decisions" && (
            <DecisionsTable
              decisions={run.decisions}
              editable
              overrides={overrides}
              onOverride={setOverride}
            />
          )}
          {tab === "files" && <FileViewer files={run.files} />}
          {tab === "preview" && (
            <div className="space-y-2">
              <p className="text-xs text-muted-foreground">
                The compiled read → process → write pipeline, run on sampled source rows in the
                local DuckDB sandbox. Nothing has been written yet.
              </p>
              <PreviewTable preview={run.preview} />
            </div>
          )}
          {tab === "conventions" && (
            <ConventionsPanel conventions={run.conventions} udfs={run.udfCatalog} />
          )}
        </section>

        <aside className="space-y-3">
          <h3 className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
            Findings
          </h3>
          <FindingsList findings={run.findings} />
          {run.revisions.length > 0 && (
            <>
              <h3 className="pt-3 text-xs font-medium tracking-wide text-muted-foreground uppercase">
                Revisions
              </h3>
              {run.revisions.map((r) => (
                <div key={r.at} className="rounded-lg border bg-card p-3 text-xs">
                  <p className="font-mono text-muted-foreground">
                    {r.by} · {new Date(r.at).toLocaleTimeString()}
                  </p>
                  {r.feedback && <p className="mt-1 text-foreground">“{r.feedback}”</p>}
                  <p className="mt-1 font-mono text-muted-foreground">
                    rows changed: {r.changedRows.length ? r.changedRows.join(", ") : "none"}
                  </p>
                </div>
              ))}
            </>
          )}
        </aside>
      </div>

      <div className="sticky bottom-0 z-30 -mx-6 border-t bg-background">
        <div className="flex flex-wrap items-center justify-between gap-3 px-6 py-3">
          <button
            onClick={() => setModal("reject")}
            className="rounded-md border px-4 py-2 text-sm text-destructive transition-colors hover:bg-destructive/10"
          >
            Reject
          </button>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setModal("revise")}
              className="rounded-md border px-4 py-2 text-sm text-foreground transition-colors hover:bg-elevated"
            >
              Revise
              {pending.length > 0
                ? ` (${pending.length} override${pending.length > 1 ? "s" : ""})`
                : ""}
            </button>
            <button
              onClick={() => setModal("approve")}
              disabled={blocked.length > 0 || pending.length > 0}
              title={
                blocked.length > 0
                  ? "Every column must pass the sandbox first"
                  : pending.length > 0
                    ? "Send your overrides with Revise first"
                    : undefined
              }
              className="rounded-md bg-primary px-5 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-40"
            >
              Approve &amp; execute
            </button>
          </div>
        </div>
      </div>

      {modal === "revise" && (
        <Modal title="Send back to the agent" onClose={() => setModal(null)} wide>
          {pending.length > 0 && (
            <div className="mb-4 rounded-md border bg-terminal p-3 font-mono text-xs">
              <p className="mb-1.5 text-muted-foreground">
                Your overrides (verified before review resumes):
              </p>
              {pending.map((o) => (
                <p key={o.row} className="text-foreground">
                  row {o.row}: {o.expression}
                </p>
              ))}
            </div>
          )}
          <label className="mb-2 block text-xs text-muted-foreground" htmlFor="revise-feedback">
            Feedback for the agent (optional) — name the columns or rows it should change
          </label>
          <textarea
            id="revise-feedback"
            value={feedback}
            onChange={(e) => setFeedback(e.target.value)}
            rows={4}
            placeholder="e.g. is_enrolled should use the ynToBool UDF so 'y ' counts as enrolled"
            className="w-full rounded-md border bg-terminal p-3 font-mono text-xs text-foreground placeholder:text-muted-foreground/50"
          />
          {error && <p className="mt-2 text-xs text-destructive">{error}</p>}
          <div className="mt-4 flex justify-end gap-2">
            <button
              onClick={() => setModal(null)}
              className="rounded-md border px-4 py-2 text-sm text-muted-foreground hover:text-foreground"
            >
              Cancel
            </button>
            <button
              onClick={() => void act(() => reviseRun(runId, pending, feedback.trim()))}
              disabled={busy || (pending.length === 0 && !feedback.trim())}
              className="inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-40"
            >
              {busy && <Loader2 className="size-4 animate-spin motion-reduce:animate-none" />}
              Send to agent
            </button>
          </div>
        </Modal>
      )}

      {modal === "approve" && (
        <Modal title="Approve & execute" onClose={() => setModal(null)}>
          <ol className="list-decimal space-y-1.5 pl-4 text-sm text-muted-foreground">
            <li>
              Build <span className="font-mono text-foreground">{run.targetTable}</span> in the
              local warehouse (CREATE OR REPLACE TABLE … AS SELECT).
            </li>
            <li>Audit it: row count, nonNull, uniqueKey and the schema contract.</li>
            <li>
              {github?.configured ? (
                <>
                  Publish {run.files.length} files to{" "}
                  <span className="font-mono text-foreground">
                    {github.repo}@{github.branch}
                  </span>{" "}
                  in one commit — only if the audit passes.
                </>
              ) : (
                <>GitHub is not configured, so the files stay available as a zip download.</>
              )}
            </li>
          </ol>
          {error && <p className="mt-3 text-xs text-destructive">{error}</p>}
          <div className="mt-5 flex justify-end gap-2">
            <button
              onClick={() => setModal(null)}
              className="rounded-md border px-4 py-2 text-sm text-muted-foreground hover:text-foreground"
            >
              Cancel
            </button>
            <button
              onClick={() => void act(() => approveRun(runId))}
              disabled={busy}
              className="inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-40"
            >
              {busy && <Loader2 className="size-4 animate-spin motion-reduce:animate-none" />}
              Confirm &amp; execute
            </button>
          </div>
        </Modal>
      )}

      {modal === "reject" && (
        <Modal title="Reject this run" onClose={() => setModal(null)}>
          <p className="mb-3 text-sm text-muted-foreground">
            Rejecting ends the run. To have the agent try again instead, use Revise.
          </p>
          <label className="mb-2 block text-xs text-muted-foreground" htmlFor="reject-feedback">
            Reason (kept in the run's audit trail)
          </label>
          <textarea
            id="reject-feedback"
            value={feedback}
            onChange={(e) => setFeedback(e.target.value)}
            rows={3}
            className="w-full rounded-md border bg-terminal p-3 font-mono text-xs text-foreground"
          />
          {error && <p className="mt-2 text-xs text-destructive">{error}</p>}
          <div className="mt-4 flex justify-end gap-2">
            <button
              onClick={() => setModal(null)}
              className="rounded-md border px-4 py-2 text-sm text-muted-foreground hover:text-foreground"
            >
              Cancel
            </button>
            <button
              onClick={() => void act(() => rejectRun(runId, feedback.trim()))}
              disabled={busy}
              className="inline-flex items-center gap-2 rounded-md bg-destructive px-4 py-2 text-sm font-medium text-destructive-foreground hover:bg-destructive/90 disabled:opacity-40"
            >
              {busy && <Loader2 className="size-4 animate-spin motion-reduce:animate-none" />}
              Reject run
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}
