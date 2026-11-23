"use client";

import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button, Field, Notice, uiStyles } from "@/components/ui";
import { api } from "@/lib/api";
import { useErrorText } from "@/lib/useErrorText";

import styles from "../../public.module.css";

type Props = { slug: string; business: string; count: number; reward: string };

export function SignupForm({ slug, business, count, reward }: Props) {
  const t = useTranslations("signup");
  const common = useTranslations("common");
  const errorText = useErrorText();
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(form: FormData) {
    setBusy(true);
    setError(null);
    const value = (k: string) => String(form.get(k) ?? "").trim() || undefined;
    const num = (k: string) => (value(k) ? Number(value(k)) : undefined);
    try {
      const res = await api<{ card_url: string }>(`/public/${slug}/signup`, {
        method: "POST",
        json: {
          first_name: value("first_name"),
          phone: value("phone"),
          email: value("email"),
          birthday_day: num("day"),
          birthday_month: num("month"),
          marketing_consent: form.get("consent") === "on",
        },
      });
      router.replace(res.card_url);
    } catch (e) {
      setError(errorText(e));
      setBusy(false);
    }
  }

  return (
    <form className={styles.form} action={submit}>
      <p className={styles.lead}>{t("lead", { business, count, reward })}</p>
      <Field name="first_name" label={t("firstName")} autoComplete="given-name" required maxLength={60} />
      <Field name="phone" label={t("phone")} type="tel" autoComplete="tel" inputMode="tel" help={t("contactHint")} />
      <Field name="email" label={t("email")} type="email" autoComplete="email" />
      <fieldset className={`${styles.birthday} ${styles.bare}`}>
        <legend className={styles.legend}>
          {t("birthday")} <span className={styles.optional}>({common("optional")})</span>
        </legend>
        <div className={styles.pair}>
          <Field name="day" label={t("day")} inputMode="numeric" pattern="[0-9]*" maxLength={2} autoComplete="bday-day" />
          <label className={uiStyles.field}>
            <span className={uiStyles.label}>{t("month")}</span>
            <select name="month" className={styles.select} autoComplete="bday-month" defaultValue="">
              <option value="" />
              {t("months")
                .split(",")
                .map((m, i) => (
                  <option key={m} value={i + 1}>
                    {m}
                  </option>
                ))}
            </select>
          </label>
        </div>
      </fieldset>
      <label className={styles.check}>
        <input type="checkbox" name="consent" />
        <span>
          {t("consent", { business })}
          <br />
          <span className={styles.muted}>{t("consentHint")}</span>
        </span>
      </label>
      {error && <Notice tone="danger">{error}</Notice>}
      <Button type="submit" size="large" disabled={busy}>
        {t("submit")}
      </Button>
      <p className={styles.muted}>{t("privacy", { business })}</p>
    </form>
  );
}
