import { useQuery } from "@tanstack/react-query";
import { Link, createFileRoute, useNavigate } from "@tanstack/react-router";
import { listRuns } from "@/lib/api";
import { formatDuration, timeAgo } from "@/lib/format";
import type { Run } from "@/lib/types";
import { StatusPill } from "@/components/StatusPill";
import { Skeleton } from "@/components/Skeleton";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/")({
  component: RunsPage,
});

function runDestination(run: Run): string {
  return run.status === "running" || run.status === "awaiting_review"
    ? `/runs/${run.id}`
    : `/runs/${run.id}/result`;
}

function StatCard({
  label,
  value,
  highlight,
}: {
  label: string;
  value: string;
  highlight?: boolean;
}) {
  return (
    <div
      className={cn(
        "rounded-lg border bg-card p-5",
        highlight && "border-info/50 bg-info/5",
      )}
    >
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={cn("mt-2 font-mono text-2xl text-foreground", highlight && "text-info")}>
        {value}
      </p>
    </div>
  );
}

function RunsPage() {
  const navigate = useNavigate();
  const { data: runs, isLoading } = useQuery({ queryKey: ["runs"], queryFn: listRuns });

  if (isLoading || !runs) {
    return (
      <div className="mx-auto max-w-6xl space-y-6">
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-24" />
          ))}
        </div>
        <Skeleton className="h-96" />
      </div>
    );
  }

  if (runs.length === 0) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <div className="text-center">
          <p className="text-sm text-muted-foreground">
            No runs yet. Upload your mapping files to start your first run.
          </p>
          <Link
            to="/new-run"
            className="mt-4 inline-flex items-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
          >
            New Run
          </Link>
        </div>
      </div>
    );
  }

  const total = runs.length;
  const awaiting = runs.filter((r) => r.status === "awaiting_review").length;
  const finished = runs.filter((r) => r.status === "succeeded" || r.status === "failed");
  const successRate = finished.length
    ? Math.round((runs.filter((r) => r.status === "succeeded").length / finished.length) * 100)
    : 0;
  const durations = runs.filter((r) => r.durationSec !== null).map((r) => r.durationSec!);
  const avgGen = durations.length
    ? formatDuration(Math.round(durations.reduce((a, b) => a + b, 0) / durations.length))
    : "—";

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="Total runs" value={String(total)} />
        <StatCard label="Awaiting review" value={String(awaiting)} highlight={awaiting > 0} />
        <StatCard label="Success rate" value={`${successRate}%`} />
        <StatCard label="Avg. generation time" value={avgGen} />
      </div>

      <div className="overflow-x-auto rounded-lg border bg-card">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b text-xs text-muted-foreground">
              <th className="px-4 py-3 font-medium">Run</th>
              <th className="px-4 py-3 font-medium">Status</th>
              <th className="hidden px-4 py-3 font-medium md:table-cell">Mappings</th>
              <th className="hidden px-4 py-3 font-medium md:table-cell">Cost</th>
              <th className="px-4 py-3 font-medium">Started</th>
              <th className="hidden px-4 py-3 font-medium sm:table-cell">Duration</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((run) => (
              <tr
                key={run.id}
                onClick={() => navigate({ to: runDestination(run) })}
                onKeyDown={(e) => {
                  if (e.key === "Enter") navigate({ to: runDestination(run) });
                }}
                tabIndex={0}
                className="cursor-pointer border-b transition-colors last:border-0 hover:bg-elevated/60 focus-visible:bg-elevated/60"
              >
                <td className="px-4 py-3">
                  <p className="font-mono text-foreground">{run.id}</p>
                  <p className="mt-0.5 font-mono text-xs text-muted-foreground">
                    {run.targetTable}
                  </p>
                </td>
                <td className="px-4 py-3">
                  <StatusPill status={run.status} />
                </td>
                <td className="hidden px-4 py-3 text-muted-foreground md:table-cell">
                  <span className="font-mono text-xs">
                    {run.mappingsValidated} validated · {run.mappingsExcluded} excluded
                  </span>
                </td>
                <td className="hidden px-4 py-3 md:table-cell">
                  <span className="font-mono text-xs text-muted-foreground">
                    {run.costGb !== null ? `${run.costGb} GB scanned` : "—"}
                  </span>
                </td>
                <td className="px-4 py-3 text-xs text-muted-foreground">
                  {timeAgo(run.startedAt)}
                </td>
                <td className="hidden px-4 py-3 sm:table-cell">
                  <span className="font-mono text-xs text-muted-foreground">
                    {formatDuration(run.durationSec)}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
