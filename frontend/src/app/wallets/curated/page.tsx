import { redirect } from "next/navigation";

export default function CuratedListPage() {
  redirect("/wallets?tab=curated");
}
