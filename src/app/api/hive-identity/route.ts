import { NextResponse } from "next/server";

/** Lets you confirm this deployment is Hive Next.js (not another Railway app on a shared domain). */
export async function GET() {
  return NextResponse.json({
    app: "caged-hive-quant",
    service: "hive-frontend",
    railway_public_domain: process.env.RAILWAY_PUBLIC_DOMAIN ?? null,
    api_url: process.env.NEXT_PUBLIC_API_URL ?? process.env.API_URL ?? null,
  });
}
