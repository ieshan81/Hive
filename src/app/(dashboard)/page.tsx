import { redirect } from "next/navigation";

/** Research v2 — AI cockpit is the primary entry (live truth, no snapshot cache). */
export default function HomePage() {
  redirect("/cockpit");
}
