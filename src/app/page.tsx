import { Dashboard } from "@/components/Dashboard";
import { getDashboardData } from "@/lib/dashboard";

export default async function Home() {
  const data = await getDashboardData();
  return <Dashboard data={data} />;
}
