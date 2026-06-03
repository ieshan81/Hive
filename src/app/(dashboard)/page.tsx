import { redirect } from "next/navigation";

/** Primary entry — Mission Control answers “Is the system safe and running?” */
export default function HomePage() {
  redirect("/mission-control");
}
