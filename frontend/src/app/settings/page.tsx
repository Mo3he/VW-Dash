import SettingsForm from "./SettingsForm";

export const revalidate = 0;

async function fetchSettings() {
  try {
    const res = await fetch("http://localhost:8000/api/settings", {
      cache: "no-store",
    });
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

export default async function SettingsPage() {
  const current = await fetchSettings();
  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-lg font-semibold text-white">Settings</h1>
      <SettingsForm initial={current} />
    </div>
  );
}
