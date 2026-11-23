"use client";

import { useTranslations } from "next-intl";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { Notice } from "@/components/ui";
import { api } from "@/lib/api";

import styles from "../../../../public.module.css";

export default function ReissuePage() {
  const t = useTranslations("reissue");
  const card = useTranslations("card");
  const { slug, token } = useParams<{ slug: string; token: string }>();
  const router = useRouter();
  const [failed, setFailed] = useState(false);
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    api<{ card_url: string }>(`/public/${slug}/reissue/${token}`, { method: "POST" })
      .then((r) => router.replace(r.card_url))
      .catch(() => setFailed(true));
  }, [slug, token, router]);

  return (
    <main className={styles.page}>
      <div className={styles.column}>
        {failed ? (
          <>
            <Notice tone="danger">{t("failed")}</Notice>
            <a className={styles.link} href={`/k/${slug}/kwijt`}>
              {card("lostLink")}
            </a>
          </>
        ) : (
          <p className={styles.muted}>{t("working")}</p>
        )}
      </div>
    </main>
  );
}
