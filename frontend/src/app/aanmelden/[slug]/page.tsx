import { notFound } from "next/navigation";

import { Pass } from "@/components/Pass";
import type { Palette } from "@/lib/api";
import { serverGet } from "@/lib/server";

import styles from "../../public.module.css";
import { SignupForm } from "./SignupForm";

type Business = {
  name: string;
  slug: string;
  palette: Palette;
  program: { name: string; stamps_required: number; reward: string };
};

export default async function SignupPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const b = await serverGet<Business>(`/public/${encodeURIComponent(slug)}`);
  if (!b) notFound();
  return (
    <main className={styles.page}>
      <div className={styles.column}>
        <Pass business={b.name} programName={b.program.name} palette={b.palette} stamps={0} total={b.program.stamps_required} />
        <SignupForm slug={b.slug} business={b.name} count={b.program.stamps_required} reward={b.program.reward} />
      </div>
    </main>
  );
}
