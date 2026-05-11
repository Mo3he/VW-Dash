"use client";
import { useState, useRef, useEffect } from "react";
import { useRouter } from "next/navigation";
import { Eye, EyeOff, Upload } from "lucide-react";
import { authHeaders, isAdmin } from "@/lib/auth";

interface ServerSettings {
  vw_username: string;
  vw_password_set: boolean;
  vw_vin: string;
  electricity_rate_per_kwh: number;
  currency_symbol: string;
  currency_after: boolean;
  epa_rated_range_km: number;
  poll_interval_seconds: number;
  vehicle_name: string;
  battery_capacity_kwh: number;
  timezone: string;
  time_24h: boolean;
  distance_unit: "km" | "miles";
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
  vehicle_name: string;
  battery_capacity_kwh: string;
  timezone: string;
  time_24h: boolean;
  distance_unit: "km" | "miles";
  webhook_url: string;
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
    poll_interval_seconds: String(Math.round((s?.poll_interval_seconds ?? 300) / 60)),
    vehicle_name: s?.vehicle_name ?? "ID.4",
    battery_capacity_kwh: String(s?.battery_capacity_kwh ?? 77),
    timezone: s?.timezone ?? "UTC",
    time_24h: s?.time_24h ?? false,
    distance_unit: s?.distance_unit ?? "km",
    webhook_url: "",
  };
}

interface ImportResult {
  snapshots: number;
  trips: number;
  charging_sessions: number;
}

function GeocodeBackfill() {
  const [started, setStarted] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    setError(null);
    try {
      const { authHeaders } = await import("@/lib/auth");
      const res = await fetch("/api/import/geocode-backfill", {
        method: "POST",
        headers: authHeaders(),
      });
      if (!res.ok) throw new Error(await res.text());
      setStarted(true);
    } catch (err) {
      setError(String(err));
    }
  }

  return (
    <div className="rounded-2xl bg-[#161b27] border border-white/5 p-4 flex flex-col gap-3">
      <div className="text-xs text-gray-400 uppercase tracking-wider font-medium">Geocoding</div>
      <p className="text-xs text-gray-500">
        Fill in missing addresses for imported trips and charging sessions. Runs in the background — check Trips/Journeys in a few minutes.
      </p>
      <button
        type="button"
        onClick={run}
        disabled={started}
        className="flex items-center justify-center gap-2 rounded-xl bg-white/5 border border-white/10 text-white font-medium py-2.5 text-sm hover:bg-white/10 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
      >
        {started ? "Running in background…" : "Geocode missing addresses"}
      </button>
      {error && <div className="text-sm text-red-400 text-center">{error}</div>}
    </div>
  );
}

interface DashUser {
  id: number;
  username: string;
  is_admin: boolean;
}

function UsersManager({ inputClass }: { inputClass: string }) {
  const [adminView, setAdminView] = useState(false);
  const [users, setUsers] = useState<DashUser[]>([]);
  const [newUsername, setNewUsername] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newIsAdmin, setNewIsAdmin] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [changingPwFor, setChangingPwFor] = useState<number | null>(null);
  const [newPw, setNewPw] = useState("");
  const [pwError, setPwError] = useState<string | null>(null);

  useEffect(() => {
    if (!isAdmin()) {
      setLoading(false);
      return;
    }
    setAdminView(true);
    fetch("/api/auth/users", { headers: authHeaders() })
      .then((r) => (r.ok ? r.json() : Promise.reject(r)))
      .then(setUsers)
      .catch(() => setError("Failed to load users"))
      .finally(() => setLoading(false));
  }, []);

  if (!adminView || loading) return null;

  async function addUser(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const res = await fetch("/api/auth/users", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ username: newUsername.trim(), password: newPassword, is_admin: newIsAdmin }),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      setError((data as { detail?: string }).detail ?? "Failed to create user");
      return;
    }
    const user = await res.json() as DashUser;
    setUsers((u) => [...u, user]);
    setNewUsername("");
    setNewPassword("");
    setNewIsAdmin(false);
  }

  async function removeUser(id: number) {
    setError(null);
    const res = await fetch(`/api/auth/users/${id}`, {
      method: "DELETE",
      headers: authHeaders(),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      setError((data as { detail?: string }).detail ?? "Failed to delete user");
      return;
    }
    setUsers((u) => u.filter((x) => x.id !== id));
  }

  async function changePassword(id: number) {
    setPwError(null);
    const res = await fetch(`/api/auth/users/${id}/password`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ password: newPw }),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      setPwError((data as { detail?: string }).detail ?? "Failed to change password");
      return;
    }
    setChangingPwFor(null);
    setNewPw("");
  }

  return (
    <div className="rounded-2xl bg-[#161b27] border border-white/5 p-4 flex flex-col gap-4">
      <div className="text-xs text-gray-400 uppercase tracking-wider font-medium">Users</div>

      <div className="flex flex-col gap-2">
        {users.map((u) => (
          <div key={u.id} className="flex flex-col gap-1.5 py-1">
            <div className="flex items-center justify-between text-sm">
              <div className="flex items-center gap-2">
                <span className="text-white">{u.username}</span>
                {u.is_admin && (
                  <span className="text-[10px] text-[#00B0F0] bg-[#00B0F0]/10 rounded px-1.5 py-0.5">admin</span>
                )}
              </div>
              <div className="flex items-center gap-3">
                <button
                  type="button"
                  onClick={() => {
                    setChangingPwFor(changingPwFor === u.id ? null : u.id);
                    setNewPw("");
                    setPwError(null);
                  }}
                  className="text-gray-500 hover:text-gray-300 text-xs transition-colors"
                >
                  {changingPwFor === u.id ? "Cancel" : "Change password"}
                </button>
                <button
                  type="button"
                  onClick={() => removeUser(u.id)}
                  className="text-red-400 hover:text-red-300 text-xs transition-colors"
                >
                  Remove
                </button>
              </div>
            </div>
            {changingPwFor === u.id && (
              <form
                onSubmit={(e) => { e.preventDefault(); changePassword(u.id); }}
                className="flex items-center gap-2 mt-0.5"
              >
                <input
                  type="password"
                  placeholder="New password"
                  value={newPw}
                  onChange={(e) => setNewPw(e.target.value)}
                  autoComplete="new-password"
                  className={inputClass + " flex-1"}
                />
                <button
                  type="submit"
                  disabled={!newPw}
                  className="text-xs px-3 py-2 rounded-lg bg-white/5 border border-white/10 text-white hover:bg-white/10 transition-colors disabled:opacity-40"
                >
                  Save
                </button>
              </form>
            )}
            {changingPwFor === u.id && pwError && (
              <div className="text-xs text-red-400">{pwError}</div>
            )}
          </div>
        ))}
      </div>

      <div className="flex flex-col gap-2 border-t border-white/5 pt-3">
        <span className="text-xs text-gray-500 uppercase tracking-wider">Add user</span>
        <form onSubmit={addUser} className="flex flex-col gap-2">
          <input
            type="text"
            placeholder="Username"
            value={newUsername}
            onChange={(e) => setNewUsername(e.target.value)}
            autoComplete="off"
            className={inputClass}
          />
          <input
            type="password"
            placeholder="Password"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            autoComplete="new-password"
            className={inputClass}
          />
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={newIsAdmin}
              onChange={(e) => setNewIsAdmin(e.target.checked)}
              className="accent-[#00B0F0] w-4 h-4"
            />
            <span className="text-xs text-gray-400">Admin</span>
          </label>
          <button
            type="submit"
            disabled={!newUsername.trim() || !newPassword}
            className="flex items-center justify-center rounded-xl bg-white/5 border border-white/10 text-white font-medium py-2.5 text-sm hover:bg-white/10 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          >
            Add user
          </button>
        </form>
      </div>

      {error && <div className="text-sm text-red-400">{error}</div>}
    </div>
  );
}

export default function SettingsForm({ initial }: Props) {
  const router = useRouter();
  const [form, setForm] = useState<FormState>(toForm(initial));
  const [showPassword, setShowPassword] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const [importFile, setImportFile] = useState<File | null>(null);
  const [importWipe, setImportWipe] = useState(false);
  const [importLoading, setImportLoading] = useState(false);
  const [importResult, setImportResult] = useState<ImportResult | null>(null);
  const [importError, setImportError] = useState<string | null>(null);

  async function handleImport() {
    if (!importFile) return;
    setImportLoading(true);
    setImportResult(null);
    setImportError(null);
    try {
      const fd = new FormData();
      fd.append("file", importFile);
      fd.append("battery_kwh", form.battery_capacity_kwh);
      fd.append("wipe", String(importWipe));
      const res = await fetch("/api/import/vwsfriend", {
        method: "POST",
        headers: authHeaders(),
        body: fd,
      });
      if (!res.ok) throw new Error(await res.text());
      setImportResult(await res.json());
      setImportFile(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
    } catch (err) {
      setImportError(String(err));
    } finally {
      setImportLoading(false);
    }
  }

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
      poll_interval_seconds: Number(form.poll_interval_seconds) * 60,
      vehicle_name: form.vehicle_name,
      battery_capacity_kwh: Number(form.battery_capacity_kwh),
      timezone: form.timezone,
      time_24h: form.time_24h,
      distance_unit: form.distance_unit,
    };

    if (form.vw_username) body.vw_username = form.vw_username;
    if (form.vw_vin) body.vw_vin = form.vw_vin;
    // Only send password if user typed something new
    if (form.vw_password) body.vw_password = form.vw_password;

    if (form.webhook_url !== undefined) body.webhook_url = form.webhook_url;

    try {
      const res = await fetch("/api/settings", {
        method: "PATCH",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error(await res.text());
      setSaved(true);
      setForm((f) => ({ ...f, vw_password: "", webhook_url: "" }));
      setTimeout(() => setSaved(false), 3000);
      router.refresh();
    } catch (err) {
      setError(String(err));
    }
  }

  const [testStatus, setTestStatus] = useState<"idle" | "loading" | "ok" | "error">("idle");
  const [testDetail, setTestDetail] = useState<string>("");

  async function handleTestConnection() {
    setTestStatus("loading");
    setTestDetail("");
    try {
      const res = await fetch("/api/settings/test-connection", {
        method: "POST",
        headers: authHeaders(),
      });
      const data = await res.json();
      if (res.ok) {
        const vins = data.vehicles?.join(", ") || "no vehicles found";
        setTestStatus("ok");
        setTestDetail(vins);
      } else {
        setTestStatus("error");
        setTestDetail(data.detail || "Unknown error");
      }
    } catch (err) {
      setTestStatus("error");
      setTestDetail(String(err));
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

        <label className="flex flex-col gap-1">
          <span className="text-xs text-gray-500 uppercase tracking-wider">Vehicle name</span>
          <input
            type="text"
            value={form.vehicle_name}
            onChange={(e) => set("vehicle_name", e.target.value)}
            placeholder="e.g. ID.4, ID.3, ID.7"
            className={inputClass}
          />
          <span className="text-xs text-gray-600">Shown in the top bar</span>
        </label>

        <button
          type="button"
          onClick={handleTestConnection}
          disabled={testStatus === "loading"}
          className="flex items-center justify-center gap-2 rounded-xl bg-white/5 border border-white/10 text-white font-medium py-2.5 text-sm hover:bg-white/10 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {testStatus === "loading" ? "Testing…" : "Test VW connection"}
        </button>
        {testStatus === "ok" && (
          <div className="text-xs text-green-400">Connected — VINs: {testDetail}</div>
        )}
        {testStatus === "error" && (
          <div className="text-xs text-red-400">{testDetail}</div>
        )}
      </div>

      {/* Cost & Range */}
      <div className="rounded-2xl bg-[#161b27] border border-white/5 p-4 flex flex-col gap-4">
        <div className="text-xs text-gray-400 uppercase tracking-wider font-medium">
          Cost & Range
        </div>

        <label className="flex flex-col gap-1">
          <span className="text-xs text-gray-500 uppercase tracking-wider">Electricity rate (per kWh)</span>
          <input
            type="number"
            value={form.electricity_rate_per_kwh}
            onChange={(e) => set("electricity_rate_per_kwh", e.target.value)}
            step="0.01"
            min="0"
            className={inputClass}
          />
          <span className="text-xs text-gray-600">Used to calculate charging cost and cost per 100 km</span>
        </label>

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
          <span className="text-xs text-gray-500 uppercase tracking-wider">Battery capacity (kWh)</span>
          <input
            type="number"
            value={form.battery_capacity_kwh}
            onChange={(e) => set("battery_capacity_kwh", e.target.value)}
            step="0.1"
            min="1"
            className={inputClass}
          />
          <span className="text-xs text-gray-600">ID.4 77 kWh · ID.3 58 kWh · ID.7 86 kWh — used for cycle counting</span>
        </label>

        <label className="flex flex-col gap-1">
          <span className="text-xs text-gray-500 uppercase tracking-wider">Poll interval (minutes)</span>
          <input
            type="number"
            value={form.poll_interval_seconds}
            onChange={(e) => set("poll_interval_seconds", e.target.value)}
            step="1"
            min="1"
            className={inputClass}
          />
          <span className="text-xs text-gray-600">Minimum 1 min — VW may rate-limit below 5 min</span>
        </label>

        <label className="flex flex-col gap-1">
          <span className="text-xs text-gray-500 uppercase tracking-wider">Timezone</span>
          <input
            type="text"
            list="tz-list"
            value={form.timezone}
            onChange={(e) => set("timezone", e.target.value)}
            placeholder="e.g. Europe/London, America/New_York"
            className={inputClass}
          />
          <datalist id="tz-list">
            {[
              "UTC",
              "Europe/London","Europe/Dublin","Europe/Lisbon",
              "Europe/Paris","Europe/Berlin","Europe/Amsterdam","Europe/Brussels",
              "Europe/Rome","Europe/Madrid","Europe/Stockholm","Europe/Oslo","Europe/Copenhagen",
              "Europe/Helsinki","Europe/Warsaw","Europe/Prague","Europe/Vienna","Europe/Zurich",
              "Europe/Athens","Europe/Bucharest","Europe/Sofia","Europe/Istanbul",
              "Europe/Moscow","Europe/Kyiv",
              "America/New_York","America/Chicago","America/Denver","America/Los_Angeles",
              "America/Phoenix","America/Anchorage","Pacific/Honolulu",
              "America/Toronto","America/Vancouver","America/Edmonton","America/Winnipeg","America/Halifax",
              "America/Sao_Paulo","America/Argentina/Buenos_Aires","America/Santiago","America/Bogota",
              "America/Mexico_City","America/Lima",
              "Asia/Dubai","Asia/Riyadh","Asia/Tehran","Asia/Karachi","Asia/Kolkata",
              "Asia/Dhaka","Asia/Bangkok","Asia/Singapore","Asia/Shanghai","Asia/Tokyo",
              "Asia/Seoul","Asia/Hong_Kong","Asia/Taipei","Asia/Jakarta",
              "Australia/Sydney","Australia/Melbourne","Australia/Brisbane","Australia/Perth","Pacific/Auckland",
              "Africa/Cairo","Africa/Nairobi","Africa/Johannesburg","Africa/Lagos",
            ].map((tz) => <option key={tz} value={tz} />)}
          </datalist>
          <span className="text-xs text-gray-600">IANA timezone — used for all date and time display</span>
        </label>

        <div className="flex flex-col gap-1">
          <span className="text-xs text-gray-500 uppercase tracking-wider">Time format</span>
          <div className="flex rounded-lg overflow-hidden border border-white/10 text-xs w-fit">
            <button
              type="button"
              onClick={() => setForm((f) => ({ ...f, time_24h: false }))}
              className={`px-4 py-2 ${!form.time_24h ? "bg-[#00B0F0] text-[#001E50] font-semibold" : "bg-[#1e2535] text-gray-400"}`}
            >
              12h
            </button>
            <button
              type="button"
              onClick={() => setForm((f) => ({ ...f, time_24h: true }))}
              className={`px-4 py-2 ${form.time_24h ? "bg-[#00B0F0] text-[#001E50] font-semibold" : "bg-[#1e2535] text-gray-400"}`}
            >
              24h
            </button>
          </div>
        </div>

        <div className="flex flex-col gap-1">
          <span className="text-xs text-gray-500 uppercase tracking-wider">Distance unit</span>
          <div className="flex rounded-lg overflow-hidden border border-white/10 text-xs w-fit">
            <button
              type="button"
              onClick={() => setForm((f) => ({ ...f, distance_unit: "km" }))}
              className={`px-4 py-2 ${form.distance_unit === "km" ? "bg-[#00B0F0] text-[#001E50] font-semibold" : "bg-[#1e2535] text-gray-400"}`}
            >
              km
            </button>
            <button
              type="button"
              onClick={() => setForm((f) => ({ ...f, distance_unit: "miles" }))}
              className={`px-4 py-2 ${form.distance_unit === "miles" ? "bg-[#00B0F0] text-[#001E50] font-semibold" : "bg-[#1e2535] text-gray-400"}`}
            >
              miles
            </button>
          </div>
        </div>
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

      {/* Notifications */}
      <div className="rounded-2xl bg-[#161b27] border border-white/5 p-4 flex flex-col gap-4">
        <div className="text-xs text-gray-400 uppercase tracking-wider font-medium">Notifications</div>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-gray-500 uppercase tracking-wider">Webhook URL</span>
          <input
            type="url"
            value={form.webhook_url}
            onChange={(e) => set("webhook_url", e.target.value)}
            placeholder="https://ntfy.sh/my-topic or https://discord.com/api/webhooks/…"
            className={inputClass}
          />
          <span className="text-xs text-gray-600">
            POST JSON on charge/trip start and end. Leave blank to disable.
          </span>
        </label>
      </div>

      {/* Users — admin only */}
      <UsersManager inputClass={inputClass} />

      {/* VWsFriend Import */}
      <div className="rounded-2xl bg-[#161b27] border border-white/5 p-4 flex flex-col gap-4">
        <div className="text-xs text-gray-400 uppercase tracking-wider font-medium">
          Import from VWsFriend
        </div>

        <label className="flex flex-col gap-1">
          <span className="text-xs text-gray-500 uppercase tracking-wider">Backup file (.vwsfrienddbbackup)</span>
          <input
            ref={fileInputRef}
            type="file"
            accept=".backup,.vwsfrienddbbackup"
            onChange={(e) => setImportFile(e.target.files?.[0] ?? null)}
            className="text-sm text-gray-300 file:mr-3 file:py-1.5 file:px-3 file:rounded-lg file:border-0 file:text-xs file:font-medium file:bg-[#00B0F0]/10 file:text-[#00B0F0] hover:file:bg-[#00B0F0]/20 cursor-pointer"
          />
        </label>

        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={importWipe}
            onChange={(e) => setImportWipe(e.target.checked)}
            className="accent-[#00B0F0] w-4 h-4"
          />
          <span className="text-xs text-gray-400">Replace existing data</span>
        </label>

        <button
          type="button"
          onClick={handleImport}
          disabled={!importFile || importLoading}
          className="flex items-center justify-center gap-2 rounded-xl bg-white/5 border border-white/10 text-white font-medium py-2.5 text-sm hover:bg-white/10 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          <Upload size={15} />
          {importLoading ? "Importing…" : "Import"}
        </button>

        {importResult && (
          <div className="text-sm text-green-400 text-center">
            Imported {importResult.snapshots} snapshots · {importResult.trips} trips · {importResult.charging_sessions} charging sessions
            <div className="text-xs text-gray-500 mt-1">Geocoding addresses in background — check Trips/Journeys in a few minutes.</div>
          </div>
        )}
        {importError && (
          <div className="text-sm text-red-400 text-center">{importError}</div>
        )}
      </div>

      {/* Geocoding */}
      <GeocodeBackfill />
    </form>
  );
}
