import { api } from "@/lib/api";
import DashboardClient from "./DashboardClient";

export const revalidate = 0;

export default async function HomePage() {
  const [latest, history] = await Promise.all([
    api.vehicle.latest().catch(() => null),
    api.vehicle.history(24).catch(() => []),
  ]);

  return <DashboardClient initial={latest} history={history} />;
}
