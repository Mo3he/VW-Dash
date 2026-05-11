"use client";
import { useState, useEffect, useCallback } from "react";
import { setAuth, getToken } from "@/lib/auth";

type Step = "loading" | "authed" | "login" | "setup";

export default function AuthGate({ children }: { children: React.ReactNode }) {
  const [step, setStep] = useState<Step>("loading");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    async function init() {
      try {
        const setupRes = await fetch("/api/auth/setup", { cache: "no-store" });
        if (setupRes.ok) {
          const data = await setupRes.json();
          if (data.needs_setup) {
            setStep("setup");
            return;
          }
        }
      } catch {}

      const token = getToken();
      if (!token) {
        setStep("login");
        return;
      }
      try {
        const res = await fetch("/api/auth/me", {
          headers: { Authorization: `Bearer ${token}` },
          cache: "no-store",
        });
        setStep(res.ok ? "authed" : "login");
      } catch {
        setStep("login");
      }
    }
    init();
  }, []);

  const handleLogin = useCallback(async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: username.trim(), password }),
      });
      if (res.ok) {
        const data = await res.json();
        setAuth(data.access_token, data.username, data.is_admin);
        setStep("authed");
      } else {
        setError("Invalid username or password.");
      }
    } catch {
      setError("Connection error. Please try again.");
    }
    setBusy(false);
  }, [username, password]);

  const handleSetup = useCallback(async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const res = await fetch("/api/auth/setup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: username.trim(), password, is_admin: true }),
      });
      if (res.ok) {
        const data = await res.json();
        setAuth(data.access_token, data.username, data.is_admin);
        setStep("authed");
      } else {
        const err = await res.json().catch(() => ({ detail: "Setup failed" }));
        setError(err.detail ?? "Setup failed.");
      }
    } catch {
      setError("Connection error. Please try again.");
    }
    setBusy(false);
  }, [username, password]);

  if (step === "loading") {
    return (
      <div className="min-h-screen bg-[#0f1117] flex items-center justify-center">
        <div className="w-6 h-6 border-2 border-[#00B0F0] border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (step === "authed") return <>{children}</>;

  const isSetup = step === "setup";

  return (
    <div className="min-h-screen bg-[#0f1117] flex items-center justify-center px-4">
      <div className="bg-[#1a1f2e] border border-white/10 rounded-xl p-8 w-full max-w-sm">
        <h1 className="text-white text-xl font-bold mb-1">VW Dash</h1>
        <p className="text-gray-400 text-sm mb-6">
          {isSetup
            ? "Create your admin account to get started."
            : "Sign in to continue."}
        </p>
        <form onSubmit={isSetup ? handleSetup : handleLogin} className="flex flex-col gap-3">
          <input
            type="text"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder="Username"
            autoComplete="username"
            autoFocus
            className="bg-[#0f1117] border border-white/20 rounded-lg px-4 py-2 text-white text-sm placeholder:text-gray-600 focus:outline-none focus:border-[#00B0F0]"
          />
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Password"
            autoComplete={isSetup ? "new-password" : "current-password"}
            className="bg-[#0f1117] border border-white/20 rounded-lg px-4 py-2 text-white text-sm placeholder:text-gray-600 focus:outline-none focus:border-[#00B0F0]"
          />
          {error && <p className="text-red-400 text-xs">{error}</p>}
          <button
            type="submit"
            disabled={busy || !username.trim() || !password}
            className="bg-[#00B0F0] hover:bg-[#0090c8] disabled:opacity-50 text-white font-semibold rounded-lg py-2 text-sm transition-colors"
          >
            {busy
              ? isSetup ? "Creating…" : "Signing in…"
              : isSetup ? "Create account" : "Sign in"}
          </button>
        </form>
      </div>
    </div>
  );
}
