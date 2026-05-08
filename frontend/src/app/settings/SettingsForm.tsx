"use client";
import { useState } from "react";
import { Eye, EyeOff } from "lucide-react";

interface ServerSettings {
  vw_username: string;
  vw_password_set: boolean;
  vw_vin: string;
  electricity_rate_per_kwh: number;
  currency_symbol: string;
  currency_after: boolean;
  epa_rated_range_km: number;
  poll_interval_seconds: number;
}

interface FormState {
  vw_username: string;
  vw_password: string;
  vw_vin: string;
  electricity_rate_per_kwh: string;
  currency_symbol: string;
  currency_after: boolean;
  epa_rated_range_km: string;
  poll_interval_seconds: string;
}

interface Props {
  initial: ServerSettings | null;
}

function toForm(s: ServerSettings | null): FormState {
  return {
    vw_username: s?.vw_username ?? "",
    vw_password: "",
    vw_vin: s?.vw_vin ?? "",
    electricity_rate_per_kwh: String(s?.electricity_rate_per_kwh ?? 0.13),
    currency_symbol: s?.currency_symbol ?? "kr",
    currency_after: s?.currency_after ?? false,
    epa_rated_range_km: String(s?.epa_rated_range_km ?? 410),
    poll_interval_seconds: String(s?.poll_interval_seconds ?? 300),
  };
}

export default function SettingsForm({ initial }: Props) {
  const [form, setForm] = useState<FormState>(toForm(initial));
  const [showPassword, setShowPassword] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function set(key: keyof FormState, value: string) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);

    const body: Record<string, string | number | boolean> = {
      electricity_rate_per_kwh: Number(form.electricity_rate_per_kwh),
      currency_symbol: form.currency_symbol,
      currency_after: form.currency_after,
      epa_rated_range_km: Number(form.epa_rated_range_km),
      poll_interval_seconds: Number(form.poll_interval_seconds),
    };

    if (form.vw_username) body.vw_username = form.vw_username;
    if (form.vw_vin) body.vw_vin = form.vw_vin;
    // Only send password if user typed something new
    if (form.vw_password) body.vw_password = form.vw_password;

    try {
      const res = await fetch("/api/settings", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error(await res.text());
      setSaved(true);
      setForm((f) => ({ ...f, vw_password: "" })); // clear password field after save
      setTimeout(() => setSaved(false), 3000);
    } catch (err) {
      setError(String(err));
    }
  }

  const inputClass =
    "rounded-lg bg-[#1e2535] border border-white/10 px-3 py-2 text-white text-sm focus:outline-none focus:border-[#00B0F0] w-full";

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4">

      {/* VW Account */}
      <div className="rounded-2xl bg-[#161b27] border border-white/5 p-4 flex flex-col gap-4">
        <div className="text-xs text-gray-400 uppercase tracking-wider font-medium">
          VW Account
        </div>

        <label className="flex flex-col gap-1">
          <span className="text-xs text-gray-500 uppercase tracking-wider">Email</span>
          <input
            type="email"
            value={form.vw_username}
            onChange={(e) => set("vw_username", e.target.value)}
            placeholder="your@email.com"
            autoComplete="username"
            className={inputClass}
          />
        </label>

        <label className="flex flex-col gap-1">
          <span className="text-xs text-gray-500 uppercase tracking-wider">
            Password
            {initial?.vw_password_set && !form.vw_password && (
              <span className="ml-2 text-green-500 normal-case">● saved</span>
            )}
          </span>
          <div className="relative">
            <input
              type={showPassword ? "text" : "password"}
              value={form.vw_password}
              onChange={(e) => set("vw_password", e.target.value)}
              placeholder={initial?.vw_password_set ? "Leave blank to keep current" : "Password"}
              autoComplete="current-password"
              className={`${inputClass} pr-10`}
            />
            <button
              type="button"
              onClick={() => setShowPassword((v) => !v)}
              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-300"
              tabIndex={-1}
            >
              {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
            </button>
          </div>
        </label>

        <label className="flex flex-col gap-1">
          <span className="text-xs text-gray-500 uppercase tracking-wider">VIN (optional)</span>
          <input
            type="text"
            value={form.vw_vin}
            onChange={(e) => set("vw_vin", e.target.value.toUpperCase())}
            placeholder="Auto-detect if blank"
            maxLength={17}
            className={`${inputClass} font-mono`}
          />
        </label>
      </div>

      {/* Cost & Range */}
      <div className="rounded-2xl bg-[#161b27] border border-white/5 p-4 flex flex-col gap-4">
        <div className="text-xs text-gray-400 uppercase tracking-wider font-medium">
          Cost & Range
        </div>

        <label className="flex flex-col gap-1">
          <span className="text-xs text-gray-500 uppercase tracking-wider">Currency symbol</span>
          <div className="flex gap-2 items-center">
            <input
              type="text"
              value={form.currency_symbol}
              onChange={(e) => set("currency_symbol", e.target.value)}
              className="rounded-lg bg-[#1e2535] border border-white/10 px-3 py-2 text-white text-sm focus:outline-none focus:border-[#00B0F0] w-16 text-center"
              maxLength={4}
            />
            <div className="flex rounded-lg overflow-hidden border border-white/10 text-xs">
              <button
                type="button"
                onClick={() => setForm((f) => ({ ...f, currency_after: false }))}
                className={`px-3 py-2 ${!form.currency_after ? "bg-[#00B0F0] text-[#001E50] font-semibold" : "bg-[#1e2535] text-gray-400"}`}
              >
                {form.currency_symbol || "$"}100
              </button>
              <button
                type="button"
                onClick={() => setForm((f) => ({ ...f, currency_after: true }))}
                className={`px-3 py-2 ${form.currency_after ? "bg-[#00B0F0] text-[#001E50] font-semibold" : "bg-[#1e2535] text-gray-400"}`}
              >
                100 {form.currency_symbol || "$"}
              </button>
            </div>
          </div>
        </label>

        <label className="flex flex-col gap-1">
          <span className="text-xs text-gray-500 uppercase tracking-wider">Electricity rate (per kWh)</span>
          <input
            type="number"
            value={form.electricity_rate_per_kwh}
            onChange={(e) => set("electricity_rate_per_kwh", e.target.value)}
            step="0.001"
            min="0"
            className={inputClass}
          />
        </label>

        <label className="flex flex-col gap-1">
          <span className="text-xs text-gray-500 uppercase tracking-wider">Rated range (km)</span>
          <input
            type="number"
            value={form.epa_rated_range_km}
            onChange={(e) => set("epa_rated_range_km", e.target.value)}
            step="1"
            min="0"
            className={inputClass}
          />
          <span className="text-xs text-gray-600">ID.4 RWD: 410 · AWD: 337 · Pro S: 418</span>
        </label>

        <label className="flex flex-col gap-1">
          <span className="text-xs text-gray-500 uppercase tracking-wider">Poll interval (seconds)</span>
          <input
            type="number"
            value={form.poll_interval_seconds}
            onChange={(e) => set("poll_interval_seconds", e.target.value)}
            step="60"
            min="60"
            className={inputClass}
          />
          <span className="text-xs text-gray-600">Minimum 60s — VW may rate-limit below 300s</span>
        </label>
      </div>

      <button
        type="submit"
        className="rounded-xl bg-[#00B0F0] text-[#001E50] font-semibold py-3 text-sm hover:bg-[#00c8ff] transition-colors"
      >
        Save settings
      </button>

      {saved && (
        <div className="text-center text-sm text-green-400">Settings saved.</div>
      )}
      {error && (
        <div className="text-center text-sm text-red-400">{error}</div>
      )}
    </form>
  );
}
