import { ChevronRight, Pencil, Undo2 } from "lucide-react";
import { Fragment, useState } from "react";
import { MethodBadge } from "@/components/MethodBadge";
import { cn } from "@/lib/utils";
import type { Decision, Example } from "@/lib/types";

function show(v: string | null | undefined): string {
  return v === null || v === undefined ? "NULL" : JSON.stringify(v);
}

function ExampleLine({ ex }: { ex: Example }) {
  const inputs = Object.values(ex.in);
  return (
    <span className="font-mono text-[11px] leading-5">
      <span className="text-muted-foreground">
        {inputs.length ? inputs.map(show).join(", ") : "—"}
      </span>
      <span className="px-1 text-muted-foreground/60">→</span>
      <span className={ex.out === null ? "text-warning" : "text-success"}>{show(ex.out)}</span>
    </span>
  );
}

/**
 * One row per STTM mapping row: how it was implemented, by whom, what it does to sample
 * data, and why. With `editable`, a reviewer can override any row's expression.
 */
export function DecisionsTable({
  decisions,
  editable = false,
  overrides = {},
  onOverride,
}: {
  decisions: Decision[];
  editable?: boolean;
  overrides?: Record<number, string>;
  onOverride?: (row: number, expression: string | null) => void;
}) {
  const [open, setOpen] = useState<Record<number, boolean>>({});

  return (
    <div className="overflow-x-auto rounded-lg border bg-card">
      <table className="w-full text-left text-xs">
        <thead>
          <tr className="border-b text-muted-foreground">
            <th className="w-8 px-3 py-2.5 font-medium" />
            <th className="px-3 py-2.5 font-medium">STTM row</th>
            <th className="px-3 py-2.5 font-medium">Target ← source</th>
            <th className="px-3 py-2.5 font-medium">How</th>
            <th className="px-3 py-2.5 font-medium">Expression (process step)</th>
            <th className="px-3 py-2.5 font-medium">Sample in → out</th>
            <th className="px-3 py-2.5 font-medium">Why</th>
            {editable && <th className="px-3 py-2.5" />}
          </tr>
        </thead>
        <tbody>
          {decisions.map((d) => {
            const failed = d.status === "failed";
            const overridden = overrides[d.row] !== undefined;
            const expanded = open[d.row] ?? false;
            return (
              <Fragment key={d.row}>
                <tr
                  className={cn(
                    "border-b align-top last:border-0",
                    failed && "bg-destructive/5",
                    overridden && "bg-primary/5",
                  )}
                >
                  <td className="px-3 py-3">
                    <button
                      onClick={() => setOpen((o) => ({ ...o, [d.row]: !expanded }))}
                      aria-label={expanded ? "Hide details" : "Show details"}
                      className="text-muted-foreground hover:text-foreground"
                    >
                      <ChevronRight
                        className={cn("size-3.5 transition-transform", expanded && "rotate-90")}
                      />
                    </button>
                  </td>
                  <td className="px-3 py-3 font-mono text-muted-foreground">{d.row}</td>
                  <td className="px-3 py-3">
                    <p className="font-mono text-foreground">{d.targetField}</p>
                    <p className="mt-0.5 font-mono text-[11px] text-muted-foreground">
                      {d.targetType} ← {d.sourceField || "—"}
                    </p>
                  </td>
                  <td className="px-3 py-3">
                    <MethodBadge decision={d} />
                    {d.attempts > 1 && (
                      <p className="mt-1 font-mono text-[10px] text-muted-foreground">
                        {d.attempts} LLM attempts
                      </p>
                    )}
                  </td>
                  <td className="max-w-[340px] px-3 py-3">
                    {overridden ? (
                      <textarea
                        value={overrides[d.row]}
                        onChange={(e) => onOverride?.(d.row, e.target.value)}
                        rows={Math.min(6, overrides[d.row].split("\n").length + 1)}
                        spellCheck={false}
                        aria-label={`Override expression for ${d.targetField}`}
                        className="w-full rounded-md border border-primary/50 bg-terminal p-2 font-mono text-[11px] text-foreground"
                      />
                    ) : (
                      <code className="block font-mono text-[11px] leading-5 break-words whitespace-pre-wrap text-foreground">
                        {d.expression || d.template || "—"}
                      </code>
                    )}
                    {failed && d.error && (
                      <p className="mt-1.5 font-mono text-[11px] leading-4 text-destructive">
                        {d.error}
                      </p>
                    )}
                  </td>
                  <td className="px-3 py-3">
                    {d.examples[0] ? (
                      <ExampleLine ex={d.examples[0]} />
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
                    {d.nullsIntroduced && (
                      <p className="mt-1 font-mono text-[10px] text-warning">
                        {d.nullsIntroduced.count}/{d.nullsIntroduced.of} values → NULL
                      </p>
                    )}
                  </td>
                  <td className="max-w-[260px] px-3 py-3 leading-5 text-muted-foreground">
                    {d.rationale}
                  </td>
                  {editable && (
                    <td className="px-3 py-3">
                      {overridden ? (
                        <button
                          onClick={() => onOverride?.(d.row, null)}
                          className="inline-flex items-center gap-1 rounded-md border px-2 py-1 text-[11px] text-muted-foreground hover:text-foreground"
                        >
                          <Undo2 className="size-3" /> Undo
                        </button>
                      ) : (
                        <button
                          onClick={() => onOverride?.(d.row, d.template || d.expression || "")}
                          className={cn(
                            "inline-flex items-center gap-1 rounded-md border px-2 py-1 text-[11px]",
                            failed
                              ? "border-destructive/50 text-destructive"
                              : "text-muted-foreground hover:text-foreground",
                          )}
                        >
                          <Pencil className="size-3" /> {failed ? "Fix" : "Override"}
                        </button>
                      )}
                    </td>
                  )}
                </tr>
                {expanded && (
                  <tr className="border-b bg-terminal/60">
                    <td />
                    <td colSpan={editable ? 7 : 6} className="px-3 py-3">
                      <dl className="grid gap-x-6 gap-y-2 font-mono text-[11px] sm:grid-cols-[140px_1fr]">
                        <dt className="text-muted-foreground">STTM rule</dt>
                        <dd className="text-foreground">{d.rule || "—"}</dd>
                        {d.sqlLogic && (
                          <>
                            <dt className="text-muted-foreground">STTM sql_logic</dt>
                            <dd className="break-words text-foreground">{d.sqlLogic}</dd>
                          </>
                        )}
                        {d.default && (
                          <>
                            <dt className="text-muted-foreground">default value</dt>
                            <dd className="text-foreground">{d.default}</dd>
                          </>
                        )}
                        <dt className="text-muted-foreground">compiled (UDFs expanded)</dt>
                        <dd className="break-words text-foreground">{d.compiled || "—"}</dd>
                        <dt className="text-muted-foreground">result type in sandbox</dt>
                        <dd className="text-foreground">
                          {d.outputType ?? "—"} → cast to {d.targetType} in the write step
                        </dd>
                        <dt className="text-muted-foreground">examples</dt>
                        <dd className="space-y-0.5">
                          {d.examples.length ? (
                            d.examples.map((ex, i) => (
                              <div key={i}>
                                <ExampleLine ex={ex} />
                              </div>
                            ))
                          ) : (
                            <span className="text-muted-foreground">—</span>
                          )}
                        </dd>
                        {d.nullsIntroduced && (
                          <>
                            <dt className="text-muted-foreground">became NULL</dt>
                            <dd className="text-warning">
                              {d.nullsIntroduced.count} of {d.nullsIntroduced.of} sampled values
                              (e.g.{" "}
                              {d.nullsIntroduced.examples.map((v) => JSON.stringify(v)).join(", ")})
                            </dd>
                          </>
                        )}
                      </dl>
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
