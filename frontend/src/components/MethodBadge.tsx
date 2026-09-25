import { cn } from "@/lib/utils";
import type { Decision } from "@/lib/types";

const METHOD: Record<Decision["method"], { label: string; tone: string; hint: string }> = {
  direct: {
    label: "direct",
    tone: "border-border text-muted-foreground",
    hint: "Straight copy — no LLM",
  },
  cast: {
    label: "cast",
    tone: "border-warning/50 text-warning",
    hint: "Straight copy with a SAFE_CAST — no LLM",
  },
  sql_logic: {
    label: "sql_logic",
    tone: "border-info/50 text-info",
    hint: "The STTM's own SQL, verbatim — no LLM",
  },
  udf: {
    label: "team UDF",
    tone: "border-success/50 text-success",
    hint: "A team UDF, chosen by rules — no LLM",
  },
  llm: {
    label: "LLM",
    tone: "border-primary/50 text-primary",
    hint: "Translated from the natural-language rule",
  },
  reviewer: {
    label: "reviewer",
    tone: "border-foreground/40 text-foreground",
    hint: "Set by a human reviewer",
  },
};

export function MethodBadge({ decision }: { decision: Decision }) {
  const m = METHOD[decision.method];
  const cached = decision.origin === "cache";
  return (
    <span className="inline-flex flex-wrap items-center gap-1" title={m.hint}>
      <span
        className={cn(
          "rounded border px-1.5 py-0.5 font-mono text-[10px] whitespace-nowrap",
          m.tone,
        )}
      >
        {m.label}
      </span>
      {cached && (
        <span
          className="rounded border border-success/40 px-1.5 py-0.5 font-mono text-[10px] text-success"
          title="Answer reused from an earlier verified run — 0 tokens"
        >
          cached
        </span>
      )}
      {decision.udfsUsed.length > 0 && decision.method !== "udf" && (
        <span className="rounded border border-success/40 px-1.5 py-0.5 font-mono text-[10px] text-success">
          → {decision.udfsUsed.join(", ")}
        </span>
      )}
      {decision.repaired && (
        <span className="rounded border border-warning/50 px-1.5 py-0.5 font-mono text-[10px] text-warning">
          repaired
        </span>
      )}
    </span>
  );
}
