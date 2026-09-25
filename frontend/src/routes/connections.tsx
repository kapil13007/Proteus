import { createFileRoute } from "@tanstack/react-router";
import { BrainCircuit, Database, GitBranch, HardDrive } from "lucide-react";
import { Skeleton } from "@/components/Skeleton";
import { useSystemStatus } from "@/hooks/use-system-status";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/connections")({
  head: () => ({
    meta: [
      { title: "Connections — Mapfl0w" },
      {
        name: "description",
        content: "What the agent is connected to, read live from the backend.",
      },
    ],
  }),
  component: ConnectionsPage,
});

function Card({
  name,
  icon: Icon,
  ok,
  okText,
  offText,
  detail,
  rows,
}: {
  name: string;
  icon: typeof Database;
  ok: boolean;
  okText: string;
  offText: string;
  detail: string;
  rows: [string, string][];
}) {
  return (
    <div className="rounded-lg border bg-card p-5">
      <div className="flex items-center justify-between">
        <Icon className="size-5 text-muted-foreground" />
        <span
          className={cn(
            "inline-flex items-center gap-1.5 font-mono text-xs",
            ok ? "text-success" : "text-muted-foreground",
          )}
        >
          <span
            className={cn("size-1.5 rounded-full", ok ? "bg-success" : "bg-muted-foreground")}
          />
          {ok ? okText : offText}
        </span>
      </div>
      <h2 className="mt-4 text-sm font-medium text-foreground">{name}</h2>
      <p className="mt-1 text-xs text-muted-foreground">{detail}</p>
      <dl className="mt-4 space-y-1 font-mono text-xs">
        {rows.map(([k, v]) => (
          <div key={k} className="flex justify-between gap-3">
            <dt className="text-muted-foreground">{k}</dt>
            <dd className="truncate text-right text-foreground" title={v}>
              {v}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function ConnectionsPage() {
  const { data: s, isLoading, isError } = useSystemStatus();

  if (isLoading) return <Skeleton className="mx-auto h-64 max-w-5xl" />;
  if (isError || !s) {
    return <p className="text-center text-sm text-muted-foreground">Couldn't reach the backend.</p>;
  }

  return (
    <div className="mx-auto max-w-5xl">
      <p className="mb-6 text-sm text-muted-foreground">
        Everything runs locally or on a free tier — no Docker, no database server, no billing
        account.
      </p>
      <div className="grid gap-4 md:grid-cols-2">
        <Card
          name="LLM"
          icon={BrainCircuit}
          ok={s.llm.configured}
          okText="configured"
          offText="no API key"
          detail="Translates natural-language STTM rules only; everything else is decided by rules."
          rows={[
            ["provider", s.llm.provider],
            ["model", s.llm.model],
            ["reasoning effort", s.llm.reasoningEffort],
          ]}
        />
        <Card
          name="Local warehouse"
          icon={Database}
          ok
          okText="embedded"
          offText=""
          detail={`Sandbox dry runs and execution. Generated code is ${s.warehouse.targetDialect}; it is transpiled for local runs.`}
          rows={[
            ["engine", s.warehouse.engine],
            ["tables", s.warehouse.tables.join(", ") || "none"],
            ["file", s.warehouse.path],
          ]}
        />
        <Card
          name="GitHub"
          icon={GitBranch}
          ok={s.github.configured}
          okText="configured"
          offText="not configured"
          detail="Approved files are published as one commit after the audit passes. Optional."
          rows={[
            ["repo", s.github.repo || "—"],
            ["branch", s.github.branch],
          ]}
        />
        <Card
          name="App database"
          icon={HardDrive}
          ok
          okText="embedded"
          offText=""
          detail="Users, runs, the activity log and the verified-answer LLM cache."
          rows={[
            ["engine", s.appDb.engine],
            ["cached answers", `${s.cache.entries} (${s.cache.hits} hits)`],
          ]}
        />
      </div>
    </div>
  );
}
