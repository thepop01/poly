import { redirect } from "next/navigation";

export default function LegacyGlobalWalletsPage() {
  redirect("/wallets?tab=standard");
}
