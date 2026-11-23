"use client";

import { useTranslations } from "next-intl";
import { useParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { Notice } from "@/components/ui";
import { api } from "@/lib/api";

import styles from "../../../public.module.css";

/** Opening the link only shows this page; the page itself unsubscribes, so link
 * scanners in mail programs that fetch every URL do not unsubscribe anyone. */
export default function UnsubscribePage() {
  const t = useTranslations("unsubscribe");
  const { slug, token } = useParams<{ slug: string; token: string }>();
  const [state, setState] = useState<"working" | "done" | "failed">("working");
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    api(`/public/${slug}/afmelden/${token}`, { method: "POST" }).then(
      () => setState("done"),
      () => setState("failed"),
    );
  }, [slug, token]);

  return (
    <main className={styles.page}>
      <div className={styles.column}>{state === "working" ? <p className={styles.muted}>{t("working")}</p> : <Notice tone={state === "done" ? "ok" : "danger"}>{t(state)}</Notice>}</div>
    </main>
  );
}
