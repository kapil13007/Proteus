import { createFileRoute, useNavigate } from "@tanstack/react-router";
import {
  Check,
  Database,
  FileText,
  FolderTree,
  FunctionSquare,
  Loader2,
  Table2,
  X,
} from "lucide-react";
import { useRef, useState } from "react";
import { createRun, FILE_PREVIEW_FALLBACK } from "@/lib/api";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/new-run")({
  head: () => ({
    meta: [
      { title: "New Run — Mapfl0w" },
      { name: "description", content: "Upload your mapping context to start an agent run." },
    ],
  }),
  component: NewRunPage,
});

type SlotId = "source" | "target" | "sttm" | "repo" | "udf";

interface Slot {
  id: SlotId;
  title: string;
  description: string;
  ext: string;
  extras?: string[];
  hint: string;
  optional?: boolean;
  icon: typeof FileText;
}

const SLOTS: Slot[] = [
  {
    id: "source",
    title: "Source schema",
    description: "Column definitions for your source table(s)",
    ext: ".md",
    hint: "source_schema.md",
    icon: Database,
  },
  {
    id: "target",
    title: "Target schema",
    description: "Column definitions for your target table(s)",
    ext: ".md",
    hint: "target_schema.md",
    icon: Table2,
  },
  {
    id: "sttm",
    title: "STTM sheet",
    description: "The mapping: source → transformation → target",
    ext: ".csv",
    extras: [".xlsx", ".xls"],
    hint: "sttm_mapping.csv / .xlsx",
    icon: FileText,
  },
  {
    id: "repo",
    title: "Repo structure",
    description: "Folder conventions, naming, config defaults",
    ext: ".md",
    hint: "repo_structure.md",
    icon: FolderTree,
  },
  {
    id: "udf",
    title: "UDF definitions",
    description: "Your team's custom functions (scd1Load, factLoad…)",
    ext: ".md",
    hint: "udf_definitions.md",
    optional: true,
    icon: FunctionSquare,
  },
];

const MAX_BYTES = 5 * 1024 * 1024;

interface Uploaded {
  name: string;
  size: number;
  content: string;
  file: File;
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function UploadCard({
  slot,
  file,
  error,
  onFile,
  onClear,
  onPreview,
  className,
}: {
  slot: Slot;
  file?: Uploaded;
  error?: string;
  onFile: (f: File) => void;
  onClear: () => void;
  onPreview: () => void;
  className?: string;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  return (
    <div className={cn("rounded-lg border bg-card p-5", className)}>
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-2.5">
          <slot.icon className="size-4 text-muted-foreground" />
          <h2 className="text-sm font-medium text-foreground">{slot.title}</h2>
          {slot.optional && (
            <span className="rounded-full border px-2 py-0.5 font-mono text-[10px] text-muted-foreground">
              optional
            </span>
          )}
        </div>
        <span className="font-mono text-xs text-muted-foreground">{slot.ext}</span>
      </div>
      <p className="mt-1 text-xs text-muted-foreground">{slot.description}</p>

      {file ? (
        <div className="mt-4 flex items-center justify-between rounded-md border border-success/40 bg-success/5 px-3 py-2.5">
          <div className="flex min-w-0 items-center gap-2.5">
            <Check className="size-4 shrink-0 text-success" />
            <span className="truncate font-mono text-xs text-foreground">{file.name}</span>
            <span className="shrink-0 font-mono text-xs text-muted-foreground">
              {formatSize(file.size)}
            </span>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <button
              onClick={onPreview}
              className="text-xs text-info underline-offset-2 hover:underline"
            >
              Preview
            </button>
            <button
              onClick={onClear}
              aria-label={`Remove ${file.name}`}
              className="rounded text-muted-foreground hover:text-foreground"
            >
              <X className="size-3.5" />
            </button>
          </div>
        </div>
      ) : (
        <button
          onClick={() => inputRef.current?.click()}
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            const f = e.dataTransfer.files[0];
            if (f) onFile(f);
          }}
          className={cn(
            "mt-4 w-full rounded-md border border-dashed px-3 py-5 text-center transition-colors",
            dragging ? "border-primary bg-primary/5" : "hover:border-muted-foreground/50",
            error && "border-destructive",
          )}
        >
          <p className="text-xs text-muted-foreground">Drop file here or click to browse</p>
          <p className="mt-1 font-mono text-[11px] text-muted-foreground/60">
            expected: {slot.hint}
          </p>
        </button>
      )}
      {error && <p className="mt-2 text-xs text-destructive">{error}</p>}
      <input
        ref={inputRef}
        type="file"
        className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) onFile(f);
          e.target.value = "";
        }}
      />
    </div>
  );
}

function NewRunPage() {
  const navigate = useNavigate();
  const [files, setFiles] = useState<Partial<Record<SlotId, Uploaded>>>({});
  const [errors, setErrors] = useState<Partial<Record<SlotId, string>>>({});
  const [preview, setPreview] = useState<SlotId | null>(null);
  const [starting, setStarting] = useState(false);

  async function handleFile(slot: Slot, f: File) {
    setErrors((prev) => ({ ...prev, [slot.id]: undefined }));
    const allowed = [slot.ext, ...(slot.extras ?? [])];
    if (!allowed.some((ext) => f.name.toLowerCase().endsWith(ext))) {
      setErrors((prev) => ({ ...prev, [slot.id]: `Expected a ${allowed.join(" / ")} file` }));
      return;
    }
    if (f.size > MAX_BYTES) {
      setErrors((prev) => ({
        ...prev,
        [slot.id]: `File is ${formatSize(f.size)} — the limit is 5 MB`,
      }));
      return;
    }
    const isBinary = /\.(xlsx|xls)$/i.test(f.name);
    let content = "";
    if (!isBinary) {
      try {
        content = await f.text();
      } catch {
        content = "";
      }
      if (f.size === 0 || content.trim().length === 0) {
        setErrors((prev) => ({
          ...prev,
          [slot.id]: "Couldn't read this file — check the format",
        }));
        return;
      }
    } else if (f.size === 0) {
      setErrors((prev) => ({ ...prev, [slot.id]: "File is empty" }));
      return;
    }
    setFiles((prev) => ({ ...prev, [slot.id]: { name: f.name, size: f.size, content, file: f } }));
  }

  const requiredDone = SLOTS.filter((s) => !s.optional).every((s) => files[s.id]);

  async function startRun() {
    setStarting(true);
    try {
      const payload = SLOTS.flatMap((s) =>
        files[s.id] ? [{ slot: s.id, file: files[s.id]!.file }] : [],
      );
      const { run_id } = await createRun(payload);
      navigate({ to: "/runs/$runId", params: { runId: run_id } });
    } catch (e) {
      setStarting(false);
      setErrors((prev) => ({ ...prev, source: `Could not start run — is the backend up? (${e})` }));
    }
  }

  const previewSlot = preview ? SLOTS.find((s) => s.id === preview) : null;
  const previewContent = preview
    ? (files[preview]?.content ?? FILE_PREVIEW_FALLBACK[preview])
    : "";

  return (
    <div className="mx-auto max-w-4xl">
      <header className="mb-8">
        <h2 className="text-lg font-semibold text-foreground">New Run</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Upload your mapping context. The agent handles the rest.
        </p>
      </header>

      <div className="grid gap-4 md:grid-cols-2">
        {SLOTS.map((slot, i) => (
          <UploadCard
            key={slot.id}
            slot={slot}
            file={files[slot.id]}
            error={errors[slot.id]}
            onFile={(f) => void handleFile(slot, f)}
            onClear={() => setFiles((prev) => ({ ...prev, [slot.id]: undefined }))}
            onPreview={() => setPreview(slot.id)}
            className={i === SLOTS.length - 1 ? "md:col-span-2" : undefined}
          />
        ))}
      </div>

      <div className="mt-8 flex items-center justify-between">
        <p className="font-mono text-xs text-muted-foreground">
          {SLOTS.filter((s) => !s.optional && files[s.id]).length} of 4 required files uploaded
        </p>
        <button
          onClick={() => void startRun()}
          disabled={!requiredDone || starting}
          className="inline-flex items-center gap-2 rounded-md bg-primary px-5 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {starting && <Loader2 className="size-4 animate-spin motion-reduce:animate-none" />}
          {starting ? "Starting run…" : "Start run"}
        </button>
      </div>

      {previewSlot && (
        <div className="fixed inset-0 z-40" role="dialog" aria-label={`${previewSlot.title} preview`}>
          <button
            className="absolute inset-0 bg-background/70"
            aria-label="Close preview"
            onClick={() => setPreview(null)}
          />
          <aside className="absolute top-0 right-0 flex h-full w-full max-w-lg flex-col border-l bg-popover">
            <div className="flex items-center justify-between border-b px-5 py-3.5">
              <div>
                <p className="text-sm font-medium text-foreground">{previewSlot.title}</p>
                <p className="font-mono text-xs text-muted-foreground">
                  {files[previewSlot.id]?.name ?? previewSlot.hint}
                </p>
              </div>
              <button
                onClick={() => setPreview(null)}
                aria-label="Close"
                className="rounded-md p-1 text-muted-foreground hover:text-foreground"
              >
                <X className="size-4" />
              </button>
            </div>
            <pre className="flex-1 overflow-auto p-5 font-mono text-xs leading-5 whitespace-pre-wrap text-foreground">
              {previewContent}
            </pre>
          </aside>
        </div>
      )}
    </div>
  );
}