import { Link, createFileRoute } from "@tanstack/react-router";
import { ArrowRight } from "lucide-react";
import { ActivityFeed } from "@/components/ActivityFeed";
import { Skeleton } from "@/components/Skeleton";
import { StatusPill } from "@/components/StatusPill";
import { Stepper } from "@/components/Stepper";
import { useLiveRun } from "@/hooks/use-live-run";

export const Route = createFileRoute("/runs/$runId/")({
  head: () => ({
    meta: [
      { title: "Run Status — Mapfl0w" },
      { name: "description", content: "Live view of the agent generating and validating SQLX." },
      { name: "robots", content: "noindex" },
    ],
  }),
  component: RunStatusPage,
});

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

  return (
    <div className="mx-auto max-w-6xl space-y-5">
      {run.status === "awaiting_review" && (
        <div className="feed-enter flex flex-wrap items-center justify-between gap-3 rounded-lg border border-info/50 bg-info/10 px-5 py-3.5">
          <p className="text-sm text-foreground">The agent has paused for your review</p>
          <Link
            to="/runs/$runId/review"
            params={{ runId: run.id }}
            className="inline-flex items-center gap-1.5 rounded-md bg-primary px-4 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90"
          >
            Review now
            <ArrowRight className="size-3.5" />
          </Link>
        </div>
      )}
      {run.status === "succeeded" && (
        <div className="feed-enter flex flex-wrap items-center justify-between gap-3 rounded-lg border border-success/50 bg-success/10 px-5 py-3.5">
          <p className="text-sm text-foreground">Run completed — audit passed all checks</p>
          <Link
            to="/runs/$runId/result"
            params={{ runId: run.id }}
            className="inline-flex items-center gap-1.5 rounded-md border px-4 py-1.5 text-sm text-foreground hover:bg-elevated"
          >
            View result
            <ArrowRight className="size-3.5" />
          </Link>
        </div>
      )}
      {run.status === "rejected" && (
        <div className="rounded-lg border bg-card px-5 py-3.5">
          <p className="text-sm text-muted-foreground">
            This run was sent back to the agent with reviewer feedback.
          </p>
        </div>
      )}

      <header className="flex flex-wrap items-center gap-3">
        <h2 className="font-mono text-base text-foreground">{run.id}</h2>
        <span className="font-mono text-sm text-muted-foreground">{run.targetTable}</span>
        <StatusPill status={run.status} />
      </header>

      <div className="grid gap-6 lg:grid-cols-[minmax(240px,35%)_1fr]">
        <div className="rounded-lg border bg-card p-6">
          <h3 className="mb-5 text-xs font-medium tracking-wide text-muted-foreground uppercase">
            Pipeline
          </h3>
          <Stepper run={run} />
        </div>
        <ActivityFeed entries={run.feed} live={live} maxHeight="34rem" />
      </div>
    </div>
  );
}