"use client";

import { useFormatter, useLocale, useTranslations } from "next-intl";
import { useState } from "react";

import { Button, Notice } from "@/components/ui";
import { api } from "@/lib/api";
import { euros } from "@/lib/money";
import { useErrorText } from "@/lib/useErrorText";

import styles from "../../../public.module.css";

export type PlanTerms = {
  id: string;
  kind: "membership" | "bundle";
  name: string;
  price_cents: number;
  credits: number;
  validity_days: number | null;
  cancel_notice_days: number;
  cooling_off_days: number;
  unused_policy: string;
  no_show_policy: string;
  pause_policy: string;
  terms_version: number;
  renews: boolean;
};
export type Sub = { id: string; plan: string; kind: string; status: string; renews: boolean; period_end: string | null; credits: number };

/** Every condition is visible before paying; cancelling is one step on the card. */
export function Memberships({ path, plans, subscriptions, onChange }: { path: string; plans: PlanTerms[]; subscriptions: Sub[]; onChange: () => void }) {
  const t = useTranslations("membership");
  if (plans.length === 0 && subscriptions.length === 0) return null;
  return (
    <section className={styles.section} aria-labelledby="ms-title">
      <h2 id="ms-title" className={styles.sectionTitle}>
        {t("title")}
      </h2>
      {subscriptions.map((s) => (
        <Mine key={s.id} path={path} sub={s} onChange={onChange} />
      ))}
      {subscriptions.length === 0 && plans.map((p) => <Offer key={p.id} path={path} plan={p} />)}
    </section>
  );
}

function Mine({ path, sub, onChange }: { path: string; sub: Sub; onChange: () => void }) {
  const t = useTranslations("membership");
  const format = useFormatter();
  const [confirm, setConfirm] = useState(false);
  const date = sub.period_end ? format.dateTime(new Date(sub.period_end), { day: "numeric", month: "long" }) : "";
  async function cancel() {
    await api(`${path}/subscriptions/${sub.id}/cancel`, { method: "POST" }).catch(() => undefined);
    setConfirm(false);
    onChange();
  }
  return (
    <div className={styles.form}>
      <p>
        <strong>{t("yours", { plan: sub.plan })}</strong>
      </p>
      {sub.status === "pending" ? (
        <p className={styles.muted}>{t("pending")}</p>
      ) : (
        <>
          <p>{t("creditsLeft", { count: sub.credits })}</p>
          <p className={styles.muted}>{sub.renews ? t("until", { date }) : t("cancelled", { date })}</p>
        </>
      )}
      {sub.renews &&
        (confirm ? (
          <>
            <p>{t("cancelConfirm")}</p>
            <div className={styles.inline}>
              <Button type="button" variant="danger" onClick={cancel}>
                {t("cancelYes")}
              </Button>
              <button type="button" className={styles.linkButton} onClick={() => setConfirm(false)}>
                {t("keep")}
              </button>
            </div>
          </>
        ) : (
          <button type="button" className={styles.linkButton} onClick={() => setConfirm(true)}>
            {t("cancel")}
          </button>
        ))}
    </div>
  );
}

function Offer({ path, plan }: { path: string; plan: PlanTerms }) {
  const t = useTranslations("membership");
  const locale = useLocale();
  const errorText = useErrorText();
  const [open, setOpen] = useState(false);
  const [accepted, setAccepted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const price = euros(plan.price_cents, locale);

  async function buy() {
    try {
      const r = await api<{ checkout_url: string }>(`${path}/plans/${plan.id}/buy`, { method: "POST", json: { terms_version: plan.terms_version } });
      window.location.href = r.checkout_url;
    } catch (e) {
      setError(errorText(e));
    }
  }

  return (
    <div className={styles.form}>
      <p>
        <strong>{plan.name}</strong> · {plan.renews ? t("perMonth", { price }) : t("once", { price })}
      </p>
      <p className={styles.muted}>
        {plan.renews ? t("creditsMonth", { count: plan.credits }) : t("creditsTotal", { count: plan.credits, days: plan.validity_days ?? 0 })}
      </p>
      {!open ? (
        <Button type="button" variant="secondary" onClick={() => setOpen(true)}>
          {t("termsTitle")}
        </Button>
      ) : (
        <>
          <dl className={styles.terms}>
            <dt>{t("termsTitle")}</dt>
            <dd>{plan.renews ? t("renews") : t("noRenew")}</dd>
            <dd>{plan.cancel_notice_days ? t("notice", { days: plan.cancel_notice_days }) : t("noNotice")}</dd>
            <dd>{t("coolingOff", { days: plan.cooling_off_days })}</dd>
            <dt>{t("unused")}</dt>
            <dd>{plan.unused_policy}</dd>
            <dt>{t("noShow")}</dt>
            <dd>{plan.no_show_policy}</dd>
            <dt>{t("pause")}</dt>
            <dd>{plan.pause_policy}</dd>
          </dl>
          <p className={styles.muted}>{t("version", { version: plan.terms_version })}</p>
          <label className={styles.check}>
            <input type="checkbox" checked={accepted} onChange={(e) => setAccepted(e.target.checked)} />
            <span>{t("accept")}</span>
          </label>
          {error && <Notice tone="danger">{error}</Notice>}
          <Button type="button" size="large" onClick={buy} disabled={!accepted}>
            {t("buy")} · {price}
          </Button>
        </>
      )}
    </div>
  );
}
