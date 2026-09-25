import type { Conventions, UdfEntry } from "@/lib/types";

/** How the folder structure and functions.js were understood — the evidence behind every path. */
export function ConventionsPanel({
  conventions,
  udfs,
}: {
  conventions: Conventions;
  udfs: UdfEntry[];
}) {
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <div className="rounded-lg border bg-card p-4">
        <h4 className="mb-3 text-xs font-medium tracking-wide text-muted-foreground uppercase">
          Folder conventions (inferred, no LLM)
        </h4>
        <ul className="space-y-2">
          {(conventions.evidence ?? []).map((e) => (
            <li key={e} className="font-mono text-[11px] leading-5 text-foreground">
              {e}
            </li>
          ))}
        </ul>
      </div>
      <div className="rounded-lg border bg-card p-4">
        <h4 className="mb-3 text-xs font-medium tracking-wide text-muted-foreground uppercase">
          UDF catalog from {conventions.functionsPath ?? "functions.js"}
        </h4>
        {udfs.length === 0 ? (
          <p className="text-xs text-muted-foreground">No functions.js uploaded.</p>
        ) : (
          <ul className="space-y-2.5">
            {udfs.map((u) => (
              <li key={u.name} className="font-mono text-[11px] leading-5">
                <span className={u.kind === "column" ? "text-success" : "text-muted-foreground"}>
                  {u.name}(
                  {u.params.map((p) => p.name + (p.default ? `=${p.default}` : "")).join(", ")})
                </span>
                {u.kind === "column" ? (
                  <span className="block text-foreground">→ {u.example}</span>
                ) : (
                  <span className="block text-muted-foreground">
                    table-level helper — not used for columns
                  </span>
                )}
                {u.description && (
                  <span className="block text-muted-foreground">{u.description}</span>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
