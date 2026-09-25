import { FileCode2 } from "lucide-react";
import { useState } from "react";
import { CodeBlock } from "@/components/CodeBlock";
import { cn } from "@/lib/utils";
import type { GeneratedFile } from "@/lib/types";

const ORDER: GeneratedFile["kind"][] = [
  "read",
  "process",
  "write",
  "source_params",
  "target_params",
  "declaration",
];

/** The generated Dataform files at their repo paths. */
export function FileViewer({ files }: { files: GeneratedFile[] }) {
  const sorted = [...files].sort((a, b) => ORDER.indexOf(a.kind) - ORDER.indexOf(b.kind));
  const [selected, setSelected] = useState(sorted.find((f) => f.kind === "process")?.path);
  const current = sorted.find((f) => f.path === selected) ?? sorted[0];

  if (!current) {
    return <p className="text-sm text-muted-foreground">No files generated.</p>;
  }
  return (
    <div className="grid gap-4 lg:grid-cols-[260px_minmax(0,1fr)]">
      <ul className="space-y-1">
        {sorted.map((f) => (
          <li key={f.path}>
            <button
              onClick={() => setSelected(f.path)}
              className={cn(
                "w-full rounded-md border px-3 py-2 text-left transition-colors",
                f.path === current.path
                  ? "border-primary/50 bg-primary/5"
                  : "border-transparent hover:bg-elevated/60",
              )}
            >
              <span className="flex items-center gap-2 font-mono text-xs text-foreground">
                <FileCode2 className="size-3.5 shrink-0 text-muted-foreground" />
                {f.path.split("/").pop()}
              </span>
              <span className="mt-0.5 block text-[11px] leading-4 text-muted-foreground">
                {f.description}
              </span>
            </button>
          </li>
        ))}
      </ul>
      <div className="min-w-0">
        <p className="mb-2 font-mono text-xs text-muted-foreground">{current.path}</p>
        <CodeBlock code={current.content} className="max-h-[560px]" />
      </div>
    </div>
  );
}
