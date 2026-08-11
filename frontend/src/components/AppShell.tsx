import { Link, useRouterState } from "@tanstack/react-router";
import {
  LayoutList,
  LogOut,
  PanelLeftClose,
  PanelLeftOpen,
  Plug,
  Plus,
  Settings,
} from "lucide-react";
import { useState, type ReactNode } from "react";
import { logout, type AuthUser } from "@/lib/api";
import { cn } from "@/lib/utils";

const NAV = [
  { to: "/", label: "Runs", icon: LayoutList, exact: true },
  { to: "/new-run", label: "New Run", icon: Plus },
  { to: "/connections", label: "Connections", icon: Plug },
  { to: "/settings", label: "Settings", icon: Settings },
];

function pageTitle(pathname: string): string {
  if (pathname === "/") return "Runs";
  if (pathname.startsWith("/new-run")) return "New Run";
  if (pathname.startsWith("/connections")) return "Connections";
  if (pathname.startsWith("/settings")) return "Settings";
  if (/^\/runs\/[^/]+\/review/.test(pathname)) return "Review";
  if (/^\/runs\/[^/]+\/result/.test(pathname)) return "Run Result";
  if (pathname.startsWith("/runs/")) return "Run Status";
  return "Mapfl0w";
}

function ConnectionBadge({ name }: { name: string }) {
  return (
    <span className="hidden items-center gap-1.5 rounded-full border bg-card px-2.5 py-1 font-mono text-xs text-muted-foreground sm:inline-flex">
      <span className="size-1.5 rounded-full bg-success" />
      {name}
    </span>
  );
}

export function AppShell({ children, user }: { children: ReactNode; user: AuthUser }) {
  const [expanded, setExpanded] = useState(true);
  const pathname = useRouterState({ select: (s) => s.location.pathname });

  async function handleLogout() {
    await logout();
    window.location.href = "/";
  }

  const initial = (user.name || user.email).charAt(0).toUpperCase();

  return (
    <div className="flex min-h-screen w-full">
      <aside
        className={cn(
          "sticky top-0 flex h-screen shrink-0 flex-col border-r bg-sidebar transition-[width] duration-200 motion-reduce:transition-none",
          expanded ? "w-60" : "w-[72px]",
        )}
      >
        <div className={cn("flex h-14 items-center border-b", expanded ? "px-4" : "justify-center")}>
          <Link to="/" className="flex items-center gap-2 rounded-md">
            <span className="flex size-7 items-center justify-center rounded-md bg-primary font-mono text-sm font-bold text-primary-foreground">
              m
            </span>
            {expanded && <span className="font-mono text-sm text-foreground">mapfl0w</span>}
          </Link>
        </div>

        <nav className="flex-1 space-y-1 p-2">
          {NAV.map((item) => (
            <Link
              key={item.to}
              to={item.to}
              activeOptions={{ exact: item.exact ?? false }}
              activeProps={{ className: "bg-sidebar-accent text-primary" }}
              inactiveProps={{ className: "text-muted-foreground hover:bg-sidebar-accent/60 hover:text-foreground" }}
              className={cn(
                "flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
                !expanded && "justify-center px-0",
              )}
              title={item.label}
            >
              <item.icon className="size-4 shrink-0" />
              {expanded && <span>{item.label}</span>}
            </Link>
          ))}
        </nav>

        <div className="border-t p-2">
          <button
            onClick={() => setExpanded((v) => !v)}
            className={cn(
              "mb-1 flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-sidebar-accent/60 hover:text-foreground",
              !expanded && "justify-center px-0",
            )}
            aria-label={expanded ? "Collapse sidebar" : "Expand sidebar"}
          >
            {expanded ? <PanelLeftClose className="size-4" /> : <PanelLeftOpen className="size-4" />}
            {expanded && <span>Collapse</span>}
          </button>
          <div className={cn("flex items-center gap-3 rounded-md px-3 py-2", !expanded && "justify-center px-0")}>
            <span className="flex size-7 shrink-0 items-center justify-center rounded-full border bg-elevated font-mono text-xs text-foreground">
              {initial}
            </span>
            {expanded && (
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm text-foreground">{user.name || user.email}</p>
                <p className="truncate font-mono text-xs text-muted-foreground">{user.email}</p>
              </div>
            )}
            <button
              onClick={handleLogout}
              aria-label="Log out"
              title="Log out"
              className="shrink-0 rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-sidebar-accent/60 hover:text-foreground"
            >
              <LogOut className="size-3.5" />
            </button>
          </div>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex h-14 items-center justify-between border-b bg-background/95 px-6 backdrop-blur-none">
          <h1 className="text-sm font-medium text-foreground">{pageTitle(pathname)}</h1>
          <div className="flex items-center gap-2">
            <ConnectionBadge name="BigQuery" />
            <ConnectionBadge name="GitHub" />
            <ConnectionBadge name="Dataform" />
          </div>
        </header>
        <main className="flex-1 px-6 py-6">{children}</main>
      </div>
    </div>
  );
}