import DashboardClient from "./DashboardClient";

// Data is fetched client-side (token lives in localStorage, not available to SSR)
export default function HomePage() {
  return <DashboardClient initial={null} history={[]} />;
}
