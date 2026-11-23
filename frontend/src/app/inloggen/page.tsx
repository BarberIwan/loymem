"use client";

import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button, Field, Notice, Wordmark } from "@/components/ui";
import { api } from "@/lib/api";
import { useErrorText } from "@/lib/useErrorText";

import styles from "../public.module.css";

export default function LoginPage() {
  const t = useTranslations("login");
  const errorText = useErrorText();
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(form: FormData) {
    setBusy(true);
    try {
      const r = await api<{ role: string }>("/auth/login", {
        method: "POST",
        json: { email: form.get("email"), password: form.get("password") },
      });
      router.replace(r.role === "staff" ? "/scan" : "/overzicht");
    } catch (e) {
      setError(errorText(e));
      setBusy(false);
    }
  }

  return (
    <main className={styles.page}>
      <div className={styles.column}>
        <Wordmark />
        <h1 className={styles.lead}>{t("title")}</h1>
        <form className={styles.form} action={submit}>
          <Field name="email" type="email" label={t("email")} autoComplete="username" required />
          <Field name="password" type="password" label={t("password")} autoComplete="current-password" required />
          {error && <Notice tone="danger">{error}</Notice>}
          <Button type="submit" size="large" disabled={busy}>
            {t("submit")}
          </Button>
        </form>
      </div>
    </main>
  );
}
