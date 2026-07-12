import { useMemo } from "react";
import { cn } from "@/lib/utils";

const KEYWORDS =
  /\b(SELECT|FROM|WHERE|CASE|WHEN|THEN|ELSE|END|AS|AND|OR|NOT|CAST|SAFE_CAST|COALESCE|LOWER|UPPER|TRIM|INITCAP|ROUND|PARSE_DATE|TIMESTAMP|CURRENT_TIMESTAMP|config|js|post_operations|require|const|type|schema|name|uniqueKey|bigquery|partitionBy|tags|incremental|when|self|ref)\b/g;

function highlightLine(line: string): string {
  const escaped = line.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  // comments
  const commentIdx = escaped.indexOf("--");
  let code = escaped;
  let comment = "";
  if (commentIdx >= 0) {
    code = escaped.slice(0, commentIdx);
    comment = escaped.slice(commentIdx);
  }
  code = code
    .replace(/('[^']*'|"[^"]*")/g, '<span class="tok-str">$1</span>')
    .replace(KEYWORDS, '<span class="tok-kw">$1</span>');
  if (comment) code += `<span class="tok-com">${comment}</span>`;
  return code;
}

export function CodeBlock({
  code,
  editable = false,
  onChange,
  className,
}: {
  code: string;
  editable?: boolean;
  onChange?: (v: string) => void;
  className?: string;
}) {
  const lines = useMemo(() => code.split("\n"), [code]);
  const html = useMemo(() => lines.map(highlightLine), [lines]);

  if (editable) {
    return (
      <textarea
        value={code}
        onChange={(e) => onChange?.(e.target.value)}
        spellCheck={false}
        className={cn(
          "w-full resize-y rounded-lg border border-primary/40 bg-terminal p-4 font-mono text-[13px] leading-6 text-foreground",
          className,
        )}
        rows={Math.min(lines.length + 2, 34)}
      />
    );
  }

  return (
    <div
      className={cn(
        "overflow-auto rounded-lg border bg-terminal font-mono text-[13px] leading-6",
        className,
      )}
    >
      <style>{`.tok-kw{color:var(--color-primary)}.tok-str{color:var(--color-success)}.tok-com{color:var(--color-muted-foreground);font-style:italic}`}</style>
      <table className="w-full border-collapse">
        <tbody>
          {lines.map((_, i) => (
            <tr key={i}>
              <td className="w-10 select-none border-r px-2 text-right align-top text-muted-foreground/50">
                {i + 1}
              </td>
              <td
                className="whitespace-pre px-4 text-foreground"
                dangerouslySetInnerHTML={{ __html: html[i] || "\u00a0" }}
              />
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}