import type { Run } from "@/lib/types";

/** Output of the compiled read → process → write pipeline on sampled source rows. */
export function PreviewTable({ preview }: { preview: Run["preview"] }) {
  const columns = preview.columns ?? [];
  const rows = preview.rows ?? [];
  if (columns.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">No preview — the pipeline did not compile.</p>
    );
  }
  return (
    <div className="overflow-x-auto rounded-lg border bg-terminal">
      <table className="w-full text-left font-mono text-[11px]">
        <thead>
          <tr className="border-b">
            {columns.map((c, i) => (
              <th key={c} className="px-3 py-2 font-medium whitespace-nowrap text-foreground">
                {c}
                <span className="ml-1.5 text-[10px] font-normal text-muted-foreground">
                  {preview.types?.[i]}
                </span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-b last:border-0">
              {r.map((v, j) => (
                <td
                  key={j}
                  className={
                    v === null
                      ? "px-3 py-1.5 whitespace-nowrap text-muted-foreground/60 italic"
                      : "px-3 py-1.5 whitespace-nowrap text-foreground"
                  }
                >
                  {v === null ? "NULL" : v}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
