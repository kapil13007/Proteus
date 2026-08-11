import { Eye, EyeOff } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { login, register } from "@/lib/api";
import { cn } from "@/lib/utils";

const PASSWORD_RULES: { label: string; test: (pw: string) => boolean }[] = [
  { label: "At least 8 characters", test: (pw) => pw.length >= 8 },
  { label: "One uppercase letter", test: (pw) => /[A-Z]/.test(pw) },
  { label: "One lowercase letter", test: (pw) => /[a-z]/.test(pw) },
  { label: "One number", test: (pw) => /\d/.test(pw) },
  { label: "One special character", test: (pw) => /[^\w\s]/.test(pw) },
];

export function LoginScreen({ onAuthed }: { onAuthed: () => void }) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  function switchMode(next: "login" | "register") {
    setMode(next);
    setError(null);
    setNotice(null);
    setPassword("");
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setNotice(null);
    setSubmitting(true);
    try {
      if (mode === "login") {
        await login(email, password);
        onAuthed();
      } else {
        await register(email, password, name);
        // Deliberately do not log the user in — send them to the login form instead.
        setMode("login");
        setPassword("");
        setNotice("Account created — log in to continue.");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center justify-center gap-2">
          <span className="flex size-8 items-center justify-center rounded-md bg-primary font-mono text-sm font-bold text-primary-foreground">
            m
          </span>
          <span className="font-mono text-base text-foreground">mapfl0w</span>
        </div>

        <div className="rounded-lg border bg-card p-6">
          <h1 className="mb-1 text-sm font-medium text-foreground">
            {mode === "login" ? "Log in" : "Create an account"}
          </h1>
          <p className="mb-5 text-xs text-muted-foreground">
            {mode === "login" ? "Welcome back to the STTM control room." : "Get access to the STTM control room."}
          </p>

          {notice && (
            <p className="mb-4 rounded-md border border-success/30 bg-success/10 px-3 py-2 text-xs text-success">
              {notice}
            </p>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            {mode === "register" && (
              <div className="space-y-1.5">
                <Label htmlFor="name">Name</Label>
                <Input id="name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Jane Doe" />
              </div>
            )}
            <div className="space-y-1.5">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@company.com"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="password">Password</Label>
              <div className="relative">
                <Input
                  id="password"
                  type={showPassword ? "text" : "password"}
                  required
                  minLength={8}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  className="pr-9"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((v) => !v)}
                  aria-label={showPassword ? "Hide password" : "Show password"}
                  tabIndex={-1}
                  className="absolute inset-y-0 right-0 flex w-9 items-center justify-center text-muted-foreground hover:text-foreground"
                >
                  {showPassword ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
                </button>
              </div>

              {mode === "register" && password.length > 0 && (
                <ul className="mt-2 space-y-0.5">
                  {PASSWORD_RULES.map((rule) => {
                    const met = rule.test(password);
                    return (
                      <li
                        key={rule.label}
                        className={cn(
                          "text-xs",
                          met ? "text-success" : "text-muted-foreground",
                        )}
                      >
                        {met ? "✓" : "·"} {rule.label}
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>

            {error && <p className="text-xs text-destructive">{error}</p>}

            <Button type="submit" disabled={submitting} className="w-full">
              {submitting ? "Please wait…" : mode === "login" ? "Log in" : "Create account"}
            </Button>
          </form>

          <button
            type="button"
            onClick={() => switchMode(mode === "login" ? "register" : "login")}
            className="mt-4 w-full text-center text-xs text-muted-foreground hover:text-foreground"
          >
            {mode === "login" ? "Need an account? Sign up" : "Already have an account? Log in"}
          </button>
        </div>
      </div>
    </div>
  );
}
