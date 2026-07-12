import { createFileRoute } from "@tanstack/react-router";
import { Database, GitBranch, Workflow } from "lucide-react";

export const Route = createFileRoute("/connections")({
  head: () => ({
    meta: [
      { title: "Connections — Mapfl0w" },
      { name: "description", content: "BigQuery, GitHub, and Dataform connection status." },
    ],
  }),
  component: ConnectionsPage,
});

const CONNECTIONS = [
  {
    name: "BigQuery",
    icon: Database,
    resourceLabel: "project",
    resource: "mapflow-dev",
    detail: "Dry-run validation and audit queries",
  },
  {
    name: "GitHub",
    icon: GitBranch,
    resourceLabel: "repo",
    resource: "kapil13007/dataform-models",
    detail: "Approved .sqlx files are pushed here",
  },
  {
    name: "Dataform",
    icon: Workflow,
    resourceLabel: "workspace",
    resource: "production",
    detail: "Executes compiled transformations",
  },
];

function ConnectionsPage() {
  return (
    <div className="mx-auto max-w-4xl">
      <p className="mb-6 text-sm text-muted-foreground">
        Services the agent uses during a run. Managed by your workspace admin.
      </p>
      <div className="grid gap-4 md:grid-cols-3">
        {CONNECTIONS.map((c) => (
          <div key={c.name} className="rounded-lg border bg-card p-5">
            <div className="flex items-center justify-between">
              <c.icon className="size-5 text-muted-foreground" />
              <span className="inline-flex items-center gap-1.5 font-mono text-xs text-success">
                <span className="size-1.5 rounded-full bg-success" />
                connected
              </span>
            </div>
            <h2 className="mt-4 text-sm font-medium text-foreground">{c.name}</h2>
            <p className="mt-1 text-xs text-muted-foreground">{c.detail}</p>
            <p className="mt-4 font-mono text-xs text-muted-foreground">
              {c.resourceLabel}: <span className="text-foreground">{c.resource}</span>
            </p>
            <button
              disabled
              className="mt-4 w-full rounded-md border px-3 py-1.5 text-xs text-muted-foreground opacity-50"
            >
              Reconnect
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}