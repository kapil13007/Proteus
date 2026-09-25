import { cn } from "@/lib/utils";
import type { Finding } from "@/lib/types";

const ORDER = { error: 0, warning: 1, info: 2 } as const;

const TONE: Record<Finding["severity"], string> = {
  error: "border-destructive/50 bg-destructive/10 text-destructive",
  warning: "border-warning/50 bg-warning/10 text-warning",
  info: "border-info/50 bg-info/10 text-info",
};

export function FindingsList({ findings }: { findings: Finding[] }) {
  if (findings.length === 0) {
    return (
      <div className="rounded-lg border bg-card p-4">
        <p className="text-xs text-muted-foreground">
          No findings — the mapping translated cleanly.
        </p>
      </div>
    );
  }
  const sorted = [...findings].sort((a, b) => ORDER[a.severity] - ORDER[b.severity]);
  return (
    <div className="space-y-2">
      {sorted.map((f) => (
        <div key={f.id} className="rounded-lg border bg-card p-3.5">
          <div className="flex items-center gap-2">
            <span
              className={cn("rounded border px-1.5 py-0.5 font-mono text-[10px]", TONE[f.severity])}
            >
              {f.severity.toUpperCase()}
            </span>
            <span className="font-mono text-xs text-muted-foreground">
              {f.rows === "-" ? "sheet" : `row ${f.rows}`}
            </span>
          </div>
          <p className="mt-2 text-xs leading-5 text-foreground">{f.message}</p>
        </div>
      ))}
    </div>
  );
}
