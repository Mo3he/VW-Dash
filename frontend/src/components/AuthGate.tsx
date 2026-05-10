"use client";
import { useState, useEffect, useCallback } from "react";
import { getToken, setToken } from "@/lib/auth";

async function checkAuth(token: string): Promise<"ok" | "unauthorized" | "no_auth_needed"> {
  const headers: Record<string, string> = token ? { Authorization: `Bearer ${token}` } : {};
  try {
    const res = await fetch("/api/settings", { cache: "no-store", headers });
    if (res.ok) return token ? "ok" : "no_auth_needed";
    if (res.status === 401) return "unauthorized";
    return "no_auth_needed";
  } catch {
    return "no_auth_needed";
  }
}

export default function AuthGate({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<"loading" | "authed" | "locked">("loading");
  const [input, setInput] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    const token = getToken() ?? "";
    checkAuth(token).then((result) => {
      if (result === "unauthorized") {
        setState("locked");
      } else {
        setState("authed");
      }
    });
  }, []);

  const handleSubmit = useCallback(async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError("");
    const result = await checkAuth(input.trim());
    if (result === "ok") {
      setToken(input.trim());
      setState("authed");
    } else {
      setError("Invalid token. Please try again.");
    }
    setSubmitting(false);
  }, [input]);

  if (state === "loading") {
    return (
      <div className="min-h-screen bg-[#0f1117] flex items-center justify-center">
        <div className="w-6 h-6 border-2 border-[#00B0F0] border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (state === "locked") {
    return (
      <div className="min-h-screen bg-[#0f1117] flex items-center justify-center px-4">
        <div className="bg-[#1a1f2e] border border-white/10 rounded-xl p-8 w-full max-w-sm">
          <h1 className="text-white text-xl font-bold mb-2">VW Dash</h1>
          <p className="text-gray-400 text-sm mb-6">Enter your access token to continue.</p>
          <form onSubmit={handleSubmit} className="flex flex-col gap-3">
            <input
              type="password"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Access token"
              autoFocus
              className="bg-[#0f1117] border border-white/20 rounded-lg px-4 py-2 text-white text-sm placeholder:text-gray-600 focus:outline-none focus:border-[#00B0F0]"
            />
            {error && <p className="text-red-400 text-xs">{error}</p>}
            <button
              type="submit"
              disabled={submitting || !input.trim()}
              className="bg-[#00B0F0] hover:bg-[#0090c8] disabled:opacity-50 text-white font-semibold rounded-lg py-2 text-sm transition-colors"
            >
              {submitting ? "Checking…" : "Unlock"}
            </button>
          </form>
        </div>
      </div>
    );
  }

  return <>{children}</>;
}
