"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";

import { MaskChips } from "@/components/Chips";
import { Button, Field, Notice, uiStyles } from "@/components/ui";
import { api } from "@/lib/api";
import { useErrorText } from "@/lib/useErrorText";

import styles from "../../../public.module.css";

export type WaitlistPrefs = { service_id: string | null; days_mask: number; dayparts_mask: number; min_notice_minutes: number };

type Props = {
  path: string;
  current: WaitlistPrefs | null;
  hasEmail: boolean;
  services: { id: string; name: string }[];
  onChange: () => void;
};

/** Join the free-slot list. Consent covers slot alerts only. */
export function Waitlist({ path, current, hasEmail, services, onChange }: Props) {
  const t = useTranslations("waitlist");
  const errorText = useErrorText();
  const [open, setOpen] = useState(false);
  const [prefs, setPrefs] = useState<WaitlistPrefs>(current ?? { service_id: null, days_mask: 127, dayparts_mask: 7, min_notice_minutes: 60 });
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const days = [0, 1, 2, 3, 4, 5, 6].map((i) => t(`d${i}` as "d0"));
  const parts = [0, 1, 2].map((i) => t(`p${i}` as "p0"));

  const summary = (p: WaitlistPrefs) => {
    const d = p.days_mask === 127 ? t("everyDay") : days.filter((_, i) => p.days_mask & (1 << i)).join(", ");
    const dp = p.dayparts_mask === 7 ? t("allDay") : parts.filter((_, i) => p.dayparts_mask & (1 << i)).join(", ");
    return t("summary", { days: d, dayparts: dp });
  };

  async function save() {
    try {
      await api(`${path}/waitlist`, { method: "PUT", json: { ...prefs, email: hasEmail ? undefined : email || undefined } });
      setOpen(false);
      setError(null);
      onChange();
    } catch (e) {
      setError(errorText(e));
    }
  }

  async function leave() {
    await api(`${path}/waitlist`, { method: "DELETE" }).catch(() => undefined);
    onChange();
  }

  return (
    <section className={styles.section} aria-labelledby="waitlist-title">
      <h2 id="waitlist-title" className={styles.sectionTitle}>
        {t("title")}
      </h2>
      {current && !open ? (
        <>
          <p>
            {t("joined")} <span className={styles.muted}>{summary(current)}</span>
          </p>
          <div className={styles.inline}>
            <Button type="button" variant="secondary" onClick={() => setOpen(true)}>
              {t("change")}
            </Button>
            <button type="button" className={styles.linkButton} onClick={leave}>
              {t("leave")}
            </button>
          </div>
        </>
      ) : !open ? (
        <>
          <p className={styles.muted}>{t("lead")}</p>
          <Button type="button" variant="secondary" onClick={() => setOpen(true)}>
            {t("join")}
          </Button>
        </>
      ) : (
        <div className={styles.form}>
          {services.length > 0 && (
            <label className={uiStyles.field}>
              <span className={uiStyles.label}>{t("service")}</span>
              <select className={styles.select} value={prefs.service_id ?? ""} onChange={(e) => setPrefs({ ...prefs, service_id: e.target.value || null })}>
                <option value="">{t("anyService")}</option>
                {services.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
            </label>
          )}
          <div className={uiStyles.field}>
            <span className={uiStyles.label}>{t("days")}</span>
            <MaskChips label={t("days")} labels={days} value={prefs.days_mask} onChange={(v) => setPrefs({ ...prefs, days_mask: v })} />
          </div>
          <div className={uiStyles.field}>
            <span className={uiStyles.label}>{t("dayparts")}</span>
            <MaskChips label={t("dayparts")} labels={parts} value={prefs.dayparts_mask} onChange={(v) => setPrefs({ ...prefs, dayparts_mask: v })} />
          </div>
          <label className={uiStyles.field}>
            <span className={uiStyles.label}>{t("notice")}</span>
            <select className={styles.select} value={prefs.min_notice_minutes} onChange={(e) => setPrefs({ ...prefs, min_notice_minutes: Number(e.target.value) })}>
              <option value={60}>{t("notice60")}</option>
              <option value={180}>{t("notice180")}</option>
              <option value={1440}>{t("notice1440")}</option>
            </select>
          </label>
          {!hasEmail && <Field label={t("email")} type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} help={t("emailHint")} />}
          {error && <Notice tone="danger">{error}</Notice>}
          <Button type="button" onClick={save} disabled={!hasEmail && !email}>
            {current ? t("save") : t("join")}
          </Button>
        </div>
      )}
    </section>
  );
}
