import type { ReactNode } from "react";

export function Modal({
  title,
  children,
  onClose,
  wide = false,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
  wide?: boolean;
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-label={title}
    >
      <button className="absolute inset-0 bg-background/70" aria-label="Close" onClick={onClose} />
      <div
        className={`relative w-full rounded-lg border bg-popover p-5 ${wide ? "max-w-2xl" : "max-w-md"}`}
      >
        <h3 className="mb-4 text-sm font-medium text-foreground">{title}</h3>
        {children}
      </div>
    </div>
  );
}
