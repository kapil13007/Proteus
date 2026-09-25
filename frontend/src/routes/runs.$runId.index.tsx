import { Link, createFileRoute } from "@tanstack/react-router";
import { ArrowRight } from "lucide-react";
import { ActivityFeed } from "@/components/ActivityFeed";
import { FindingsList } from "@/components/FindingsList";
import { RunMetricsStrip } from "@/components/RunMetricsStrip";
import { Skeleton } from "@/components/Skeleton";
import { StatusPill } from "@/components/StatusPill";
import { Stepper } from "@/components/Stepper";
import { useLiveRun } from "@/hooks/use-live-run";

export const Route = createFileRoute("/runs/$runId/")({
  head: () => ({
    meta: [
      { title: "Run Status — Mapfl0w" },
      {
        name: "description",
        content: "Live view of the agent planning, generating and verifying.",
      },
      { name: "robots", content: "noindex" },
    ],
  }),
  component: RunStatusPage,
});

function Banner({
  tone,
  text,
  to,
  label,
  runId,
}: {
  tone: string;
  text: string;
  to?: "/runs/$runId/review" | "/runs/$runId/result";
  label?: string;
  runId: string;
}) {
  return (
    <div
      className={`feed-enter flex flex-wrap items-center justify-between gap-3 rounded-lg border px-5 py-3.5 ${tone}`}
    >
      <p className="text-sm text-foreground">{text}</p>
      {to && (
        <Link
          to={to}
          params={{ runId }}
          className="inline-flex items-center gap-1.5 rounded-md bg-primary px-4 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90"
        >
          {label}
          <ArrowRight className="size-3.5" />
        </Link>
      )}
    </div>
  );
}

function RunStatusPage() {
  const { runId } = Route.useParams();
  const run = useLiveRun(runId);

  if (!run) {
    return (
      <div className="mx-auto grid max-w-6xl gap-6 lg:grid-cols-[35%_1fr]">
        <Skeleton className="h-96" />
        <Skeleton className="h-96" />
      </div>
    );
  }

  const live = run.status === "running";
  const needsHuman = run.decisions.filter((d) => d.status === "failed").length;

  return (
    <div className="mx-auto max-w-6xl space-y-5">
      {run.status === "awaiting_review" && (
        <Banner
          runId={run.id}
          tone="border-info/50 bg-info/10"
          text={
            needsHuman
              ? `The agent has paused for review — ${needsHuman} column(s) need a human decision`
              : "Every column passed the sandbox dry run — the agent has paused for your review"
          }
          to="/runs/$runId/review"
          label="Review now"
        />
      )}
      {run.status === "succeeded" && (
        <Banner
          runId={run.id}
          tone="border-success/50 bg-success/10"
          text="Run completed — data written and every audit check passed"
          to="/runs/$runId/result"
          label="View result"
        />
      )}
      {run.status === "failed" && (
        <Banner
          runId={run.id}
          tone="border-destructive/50 bg-destructive/10"
          text={
            run.error ??
            (run.audit?.failedCheck
              ? `Audit failed — ${run.audit.failedCheck}`
              : "The run stopped — see the findings below")
          }
          to={run.audit ? "/runs/$runId/result" : undefined}
          label="View result"
        />
      )}
      {run.status === "rejected" && (
        <Banner
          runId={run.id}
          tone="border-border bg-card"
          text={`Rejected by the reviewer${run.meta.rejectFeedback ? `: “${run.meta.rejectFeedback}”` : ""}`}
        />
      )}

      <header className="flex flex-wrap items-center gap-3">
        <h2 className="font-mono text-base text-foreground">{run.id}</h2>
        <span className="font-mono text-sm text-muted-foreground">
          {run.targetTable ? `${run.targetTable} ← ${run.sourceTable}` : "reading inputs…"}
        </span>
        <StatusPill status={run.status} />
      </header>

      {run.metrics.rows && <RunMetricsStrip metrics={run.metrics} />}

      <div className="grid gap-6 lg:grid-cols-[minmax(240px,35%)_1fr]">
        <div className="rounded-lg border bg-card p-6">
          <h3 className="mb-5 text-xs font-medium tracking-wide text-muted-foreground uppercase">
            Pipeline
          </h3>
          <Stepper run={run} />
        </div>
        <ActivityFeed entries={run.feed} live={live} maxHeight="34rem" />
      </div>

      {run.status === "failed" && run.findings.length > 0 && (
        <section className="space-y-3">
          <h3 className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
            Findings
          </h3>
          <FindingsList findings={run.findings} />
        </section>
      )}
    </div>
  );
}
