import { api } from "@/lib/api";
import DashboardClient from "./DashboardClient";

export const revalidate = 0;

export default async function HomePage() {
  const [latest, history, batteryHealth] = await Promise.all([
    api.vehicle.latest().catch(() => null),
    api.vehicle.history(24).catch(() => []),
    api.vehicle.batteryHealth().catch(() => null),
  ]);

  return <DashboardClient initial={latest} history={history} batteryHealth={batteryHealth} />;
}
