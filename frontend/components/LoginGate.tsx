"use client";

import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { API_BASE_URL, hasAuthToken, setAuthToken, validateAuthToken } from "@/lib/api";

/**
 * Gates the app behind HTTP Basic Auth credentials, entered once per browser
 * session. A no-op visually once authed; does nothing if the backend has no
 * auth configured (validateAuthToken will simply succeed against an open API).
 */
export default function LoginGate({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(false);
  const [authed, setAuthed] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setAuthed(hasAuthToken());
    setReady(true);
  }, []);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setChecking(true);
    setError(null);
    const token = btoa(`${username}:${password}`);
    const result = await validateAuthToken(token);
    setChecking(false);
    if (result === "unreachable") {
      setError(`Cannot reach the backend at ${API_BASE_URL}. This looks like a network or CORS issue, not your credentials.`);
      return;
    }
    if (result === "unauthorized") {
      setError("Invalid username or password.");
      return;
    }
    setAuthToken(token);
    setAuthed(true);
  }

  if (!ready) return null;
  if (authed) return <>{children}</>;

  return (
    <div className="flex min-h-screen items-center justify-center bg-white px-5">
      <form onSubmit={submit} className="w-full max-w-sm space-y-4 rounded-2xl border border-black/10 p-6">
        <div>
          <p className="text-sm font-semibold tracking-tight">Agentic PR Reviewer</p>
          <p className="text-xs text-neutral-500">Sign in to continue.</p>
        </div>
        {error && <p className="text-xs text-red-600">{error}</p>}
        <input
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          placeholder="Username"
          autoFocus
          className="w-full rounded-lg border border-black/15 px-3 py-2 text-sm outline-none focus:border-black"
        />
        <input
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          type="password"
          placeholder="Password"
          className="w-full rounded-lg border border-black/15 px-3 py-2 text-sm outline-none focus:border-black"
        />
        <button
          type="submit"
          disabled={checking}
          className="w-full rounded-full bg-black px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          {checking ? "Checking…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}
