import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/settings")({
  head: () => ({
    meta: [
      { title: "Settings — Mapfl0w" },
      { name: "description", content: "Workspace defaults for Mapfl0w runs." },
    ],
  }),
  component: SettingsPage,
});

const ROWS: [string, string][] = [
  ["Workspace", "mapflow-dev"],
  ["Default branch prefix", "mapflow/"],
  ["Dry-run retry limit", "3"],
  ["Max scan budget per run", "10 GB"],
  ["Review required", "always"],
  ["Model", "gemini-2.5-pro"],
];

function SettingsPage() {
  return (
    <div className="mx-auto max-w-2xl">
      <p className="mb-6 text-sm text-muted-foreground">
        Agent defaults for this workspace. Editing is disabled in the demo.
      </p>
      <div className="divide-y rounded-lg border bg-card">
        {ROWS.map(([k, v]) => (
          <div key={k} className="flex items-center justify-between px-5 py-3.5">
            <span className="text-sm text-muted-foreground">{k}</span>
            <span className="font-mono text-sm text-foreground">{v}</span>
          </div>
        ))}
      </div>
    </div>
  );
}