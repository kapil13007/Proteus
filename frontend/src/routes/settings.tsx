import { createFileRoute } from "@tanstack/react-router";
import { Skeleton } from "@/components/Skeleton";
import { useSystemStatus } from "@/hooks/use-system-status";

export const Route = createFileRoute("/settings")({
  head: () => ({
    meta: [
      { title: "Settings — Mapfl0w" },
      {
        name: "description",
        content: "The agent's live configuration (edit backend/.env to change it).",
      },
    ],
  }),
  component: SettingsPage,
});

function SettingsPage() {
  const { data: s, isLoading } = useSystemStatus();
  if (isLoading || !s) return <Skeleton className="mx-auto h-80 max-w-2xl" />;

  const p = s.llm.listPricePer1M;
  const rows: [string, string, string][] = [
    ["Model", s.llm.model, "Groq free tier: 30 requests / 8K tokens per minute"],
    [
      "Reasoning effort",
      s.llm.reasoningEffort,
      "low keeps hidden reasoning tokens (and latency) small",
    ],
    [
      "Rows per LLM call",
      String(s.llm.rowsPerCall),
      "rows are batched; the cache is checked first",
    ],
    [
      "LLM answer cache",
      s.llm.cache ? "on" : "off",
      "only answers that passed verification are cached",
    ],
    [
      "LLM attempts per row",
      String(s.limits.maxAttempts),
      "1 generation + repairs of failing rows only",
    ],
    ["Sandbox sample", `${s.warehouse.sampleRows} rows`, "plus the STTM's own sample row"],
    ["Generated dialect", s.warehouse.targetDialect, "transpiled to DuckDB for local runs"],
    [
      "List price / 1M tokens",
      `$${p.input} in · $${p.cachedInput} cached · $${p.output} out`,
      "shown as a reference; the free tier bills $0",
    ],
  ];

  return (
    <div className="mx-auto max-w-3xl">
      <p className="mb-6 text-sm text-muted-foreground">
        Live values from the backend. Change them in <span className="font-mono">backend/.env</span>{" "}
        and restart the API.
      </p>
      <div className="divide-y rounded-lg border bg-card">
        {rows.map(([k, v, hint]) => (
          <div key={k} className="flex flex-wrap items-center justify-between gap-2 px-5 py-3.5">
            <div>
              <p className="text-sm text-foreground">{k}</p>
              <p className="text-xs text-muted-foreground">{hint}</p>
            </div>
            <span className="font-mono text-sm text-foreground">{v}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
