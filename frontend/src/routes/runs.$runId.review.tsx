import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { Check, Loader2, Pencil } from "lucide-react";
import { useState } from "react";
import { CodeBlock } from "@/components/CodeBlock";
import { Skeleton } from "@/components/Skeleton";
import { StatusPill } from "@/components/StatusPill";
import { approveRun, rejectRun } from "@/lib/api";
import { useLiveRun } from "@/hooks/use-live-run";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/runs/$runId/review")({
  head: () => ({
    meta: [
      { title: "Review — Mapfl0w" },
      { name: "description", content: "Review the generated SQLX before it ships." },
      { name: "robots", content: "noindex" },
    ],
  }),
  component: ReviewPage,
});

function ReviewPage() {
  const { runId } = Route.useParams();
  const navigate = useNavigate();
  const run = useLiveRun(runId);
  const [editing, setEditing] = useState(false);
  const [code, setCode] = useState<string | null>(null);
  const [rejectOpen, setRejectOpen] = useState(false);
  const [approveOpen, setApproveOpen] = useState(false);
  const [feedback, setFeedback] = useState("");
  const [busy, setBusy] = useState(false);

  if (!run) {
    return (
      <div className="mx-auto grid max-w-6xl gap-6 lg:grid-cols-[1fr_320px]">
        <Skeleton className="h-[480px]" />
        <Skeleton className="h-[480px]" />
      </div>
    );
  }

  const displayCode = code ?? run.sqlx;

  async function handleApprove() {
    setBusy(true);
    await approveRun(runId, code ?? undefined);
    navigate({ to: "/runs/$runId", params: { runId } });
  }

  async function handleReject() {
    if (!feedback.trim()) return;
    setBusy(true);
    await rejectRun(runId, feedback.trim());
    navigate({ to: "/runs/$runId", params: { runId } });
  }

  return (
    <div className="mx-auto max-w-6xl pb-24">
      <header className="mb-6 flex flex-wrap items-center gap-3">
        <h2 className="font-mono text-base text-foreground">{run.id}</h2>
        <span className="font-mono text-sm text-muted-foreground">{run.targetTable}</span>
        <StatusPill status={run.status} />
      </header>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
        <section className="min-w-0">
          <div className="mb-2 flex items-center justify-between">
            <p className="font-mono text-xs text-muted-foreground">{run.sqlxPath}</p>
            <button
              onClick={() => setEditing((v) => !v)}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-md border px-3 py-1 text-xs transition-colors",
                editing
                  ? "border-primary/50 text-primary"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              <Pencil className="size-3" />
              {editing ? "Editing" : "Edit"}
            </button>
          </div>
          <CodeBlock
            code={displayCode}
            editable={editing}
            onChange={setCode}
            className="max-h-[560px]"
          />
        </section>

        <aside className="space-y-3">
          <h3 className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
            Findings
          </h3>
          {run.findings.length === 0 ? (
            <div className="rounded-lg border bg-card p-4">
              <p className="text-xs text-muted-foreground">
                No findings — the mapping translated cleanly.
              </p>
            </div>
          ) : (
            run.findings.map((f) => (
              <div key={f.id} className="rounded-lg border bg-card p-4">
                <div className="flex items-center gap-2">
                  <span
                    className={cn(
                      "rounded border px-1.5 py-0.5 font-mono text-[10px]",
                      f.severity === "warning"
                        ? "border-warning/50 bg-warning/10 text-warning"
                        : "border-info/50 bg-info/10 text-info",
                    )}
                  >
                    {f.severity.toUpperCase()}
                  </span>
                  <span className="font-mono text-xs text-muted-foreground">{f.rows}</span>
                </div>
                <p className="mt-2 text-xs leading-5 text-foreground">{f.message}</p>
              </div>
            ))
          )}

          <div className="rounded-lg border border-success/40 bg-success/5 p-4">
            <div className="flex items-center gap-2">
              <Check className="size-4 text-success" />
              <span className="text-xs font-medium text-success">Dry run passed</span>
            </div>
            <p className="mt-2 font-mono text-xs text-muted-foreground">
              {run.costGb ?? 1.2} GB will be scanned · estimated ${run.costUsd ?? 0.006}
            </p>
          </div>
        </aside>
      </div>

      <div className="sticky bottom-0 z-30 -mx-6 mt-6 border-t bg-background">
        <div className="flex items-center justify-between px-6 py-3">
          <button
            onClick={() => setRejectOpen(true)}
            className="rounded-md border px-4 py-2 text-sm text-destructive transition-colors hover:bg-destructive/10"
          >
            Reject
          </button>
          <button
            onClick={() => setApproveOpen(true)}
            className="rounded-md bg-primary px-5 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
          >
            Approve &amp; execute
          </button>
        </div>
      </div>

      {rejectOpen && (
        <Modal onClose={() => setRejectOpen(false)} title="Send back to agent">
          <label className="mb-2 block text-xs text-muted-foreground" htmlFor="reject-feedback">
            Tell the agent what's wrong
          </label>
          <textarea
            id="reject-feedback"
            value={feedback}
            onChange={(e) => setFeedback(e.target.value)}
            rows={4}
            placeholder="e.g. Row 12 should use ROUND() before the cast, not truncate"
            className="w-full rounded-md border bg-terminal p-3 font-mono text-xs text-foreground placeholder:text-muted-foreground/50"
          />
          <div className="mt-4 flex justify-end gap-2">
            <button
              onClick={() => setRejectOpen(false)}
              className="rounded-md border px-4 py-2 text-sm text-muted-foreground hover:text-foreground"
            >
              Cancel
            </button>
            <button
              onClick={() => void handleReject()}
              disabled={!feedback.trim() || busy}
              className="inline-flex items-center gap-2 rounded-md bg-destructive px-4 py-2 text-sm font-medium text-destructive-foreground hover:bg-destructive/90 disabled:opacity-40"
            >
              {busy && <Loader2 className="size-4 animate-spin motion-reduce:animate-none" />}
              Send back to agent
            </button>
          </div>
        </Modal>
      )}

      {approveOpen && (
        <Modal onClose={() => setApproveOpen(false)} title="Approve &amp; execute">
          <p className="text-sm text-muted-foreground">This will push the generated code and run it:</p>
          <div className="mt-3 space-y-1.5 rounded-md border bg-terminal p-3 font-mono text-xs">
            <p className="text-foreground">target: {run.targetTable}</p>
            <p className="text-muted-foreground">
              cost: {run.costGb ?? 1.2} GB scanned · ~${run.costUsd ?? 0.006}
            </p>
            <p className="text-muted-foreground">repo: kapil13007/dataform-models</p>
          </div>
          <div className="mt-4 flex justify-end gap-2">
            <button
              onClick={() => setApproveOpen(false)}
              className="rounded-md border px-4 py-2 text-sm text-muted-foreground hover:text-foreground"
            >
              Cancel
            </button>
            <button
              onClick={() => void handleApprove()}
              disabled={busy}
              className="inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-40"
            >
              {busy && <Loader2 className="size-4 animate-spin motion-reduce:animate-none" />}
              Confirm &amp; execute
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}

function Modal({
  title,
  children,
  onClose,
}: {
  title: string;
  children: React.ReactNode;
  onClose: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" role="dialog" aria-label={title}>
      <button className="absolute inset-0 bg-background/70" aria-label="Close" onClick={onClose} />
      <div className="relative w-full max-w-md rounded-lg border bg-popover p-5">
        <h3 className="mb-4 text-sm font-medium text-foreground">{title}</h3>
        {children}
      </div>
    </div>
  );
}