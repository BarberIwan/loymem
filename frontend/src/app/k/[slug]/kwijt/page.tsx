"use client";

import { useTranslations } from "next-intl";
import { useParams } from "next/navigation";
import { useState } from "react";

import { Button, Field, Notice } from "@/components/ui";
import { api } from "@/lib/api";
import { useErrorText } from "@/lib/useErrorText";

import styles from "../../../public.module.css";

export default function LostPage() {
  const t = useTranslations("lost");
  const errorText = useErrorText();
  const { slug } = useParams<{ slug: string }>();
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(form: FormData) {
    try {
      await api(`/public/${slug}/reissue`, { method: "POST", json: { contact: String(form.get("contact") ?? "") } });
      setSent(true);
    } catch (e) {
      setError(errorText(e));
    }
  }

  return (
    <main className={styles.page}>
      <div className={styles.column}>
        <h1 className={styles.lead}>{t("title")}</h1>
        {sent ? (
          <Notice>{t("sent")}</Notice>
        ) : (
          <form className={styles.form} action={submit}>
            <p className={styles.muted}>{t("lead")}</p>
            <Field name="contact" label={t("contact")} required minLength={5} autoComplete="email" />
            {error && <Notice tone="danger">{error}</Notice>}
            <Button type="submit" size="large">
              {t("submit")}
            </Button>
          </form>
        )}
      </div>
    </main>
  );
}
