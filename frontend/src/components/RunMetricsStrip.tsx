import { agentMs, formatBytes, formatMs, formatTokens, formatUsd } from "@/lib/format";
import type { RunMetrics } from "@/lib/types";

function Stat({ label, value, detail }: { label: string; value: string; detail?: string }) {
  return (
    <div className="rounded-lg border bg-card p-4">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1.5 font-mono text-lg text-foreground">{value}</p>
      {detail && (
        <p className="mt-1 font-mono text-[11px] leading-4 text-muted-foreground">{detail}</p>
      )}
    </div>
  );
}

/** The run's cost/latency story in five numbers. */
export function RunMetricsStrip({ metrics }: { metrics: RunMetrics }) {
  const rows = metrics.rows;
  const llm = metrics.llm;
  const scan = metrics.scan;
  const saved =
    scan && scan.fullBytes > 0
      ? Math.round((1 - scan.readBytes / scan.fullBytes) * 100)
      : undefined;
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
      <Stat
        label="Columns decided by rules (0 tokens)"
        value={rows ? `${rows.deterministic} / ${rows.total}` : "—"}
        detail={
          rows
            ? `${rows.llm} by LLM · ${rows.cached} from cache · ${rows.reviewer} by reviewer`
            : undefined
        }
      />
      <Stat
        label="Columns reusing team UDFs"
        value={rows ? `${rows.usingUdfs} / ${rows.total}` : "—"}
        detail="functions.js, verified in V8"
      />
      <Stat
        label="LLM usage"
        value={llm ? `${formatTokens(llm.promptTokens + llm.completionTokens)} tok` : "0 tok"}
        detail={
          llm
            ? `${llm.calls} call(s) · ${formatMs(llm.latencyMs)} · ${formatUsd(llm.costUsd)} list, $0 free tier`
            : "no LLM call needed"
        }
      />
      <Stat
        label="Source scan (BigQuery-equivalent)"
        value={scan ? formatBytes(scan.readBytes) : "—"}
        detail={
          scan
            ? `${scan.readColumns}/${scan.totalColumns} columns · ${saved}% less than SELECT *`
            : undefined
        }
      />
      <Stat
        label="Agent time"
        value={formatMs(agentMs(metrics))}
        detail={
          metrics.timingsMs
            ? Object.entries(metrics.timingsMs)
                .map(([k, v]) => `${k} ${v}`)
                .join(" · ")
            : undefined
        }
      />
    </div>
  );
}
