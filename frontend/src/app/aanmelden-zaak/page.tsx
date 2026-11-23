"use client";

import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button, Field, Notice, Wordmark } from "@/components/ui";
import { api } from "@/lib/api";
import { useErrorText } from "@/lib/useErrorText";

import styles from "../public.module.css";

export default function BusinessSignupPage() {
  const t = useTranslations("businessSignup");
  const errorText = useErrorText();
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(form: FormData) {
    setBusy(true);
    const v = (k: string) => String(form.get(k) ?? "");
    try {
      await api("/business-signup", {
        method: "POST",
        json: { code: v("code"), business_name: v("business_name"), owner_name: v("owner_name"), email: v("email"), password: v("password") },
      });
      router.replace("/instellingen?start=1");
    } catch (e) {
      setError(errorText(e));
      setBusy(false);
    }
  }

  return (
    <main className={styles.page}>
      <div className={styles.column}>
        <Wordmark />
        <h1 className={styles.title}>{t("title")}</h1>
        <p className={styles.muted}>{t("lead")}</p>
        <form className={styles.form} action={submit}>
          <Field name="code" label={t("code")} required autoComplete="off" />
          <Field name="business_name" label={t("businessName")} required minLength={2} maxLength={120} autoComplete="organization" />
          <Field name="owner_name" label={t("ownerName")} required minLength={2} autoComplete="name" />
          <Field name="email" type="email" label={t("email")} required autoComplete="username" />
          <Field name="password" type="password" label={t("password")} help={t("passwordHint")} required minLength={10} autoComplete="new-password" />
          {error && <Notice tone="danger">{error}</Notice>}
          <Button type="submit" size="large" disabled={busy}>
            {t("submit")}
          </Button>
        </form>
      </div>
    </main>
  );
}
