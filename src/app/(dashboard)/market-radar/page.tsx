import { getDashboardData } from "@/lib/dashboard";
import { DynamicMarketRadarPanel } from "@/components/panels/DynamicMarketRadarPanel";

export default async function MarketRadarPage() {
  const data = await getDashboardData();
  return (
    <DynamicMarketRadarPanel
      assets={data.marketAssets}
      refreshedAt={data.marketRadarMeta.refreshedAt}
      opportunitiesScanned={data.marketRadarMeta.opportunitiesScanned}
      statusMessage={data.marketRadarMeta.message}
    />
  );
}
