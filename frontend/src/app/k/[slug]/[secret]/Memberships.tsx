"use client";

import { useFormatter, useLocale, useTranslations } from "next-intl";
import { useState } from "react";

import { Button, Notice } from "@/components/ui";
import { api, type Balance, type BalanceLine } from "@/lib/api";
import { euros } from "@/lib/money";
import { useErrorText } from "@/lib/useErrorText";

import styles from "../../../public.module.css";

export type PlanTerms = {
  id: string;
  kind: "membership" | "bundle" | "credit";
  name: string;
  price_cents: number;
  credits: number;
  value_cents: number | null;
  bonus_percent: number | null;
  validity_days: number | null;
  cancel_notice_days: number;
  cooling_off_days: number;
  unused_policy: string;
  no_show_policy: string;
  pause_policy: string;
  refund_policy: string;
  terms_version: number;
  renews: boolean;
};
export type Sub = {
  id: string;
  plan: string;
  kind: string;
  status: string;
  renews: boolean;
  period_end: string | null;
  credits: number | null;
  balance_cents: number | null;
};

type Props = {
  path: string;
  plans: PlanTerms[];
  subscriptions: Sub[];
  balance: Balance;
  history: BalanceLine[];
  onChange: () => void;
};

/** Every condition is visible before paying; cancelling is one step on the card. */
export function Memberships({ path, plans, subscriptions, balance, history, onChange }: Props) {
  const t = useTranslations("membership");
  const visits = subscriptions.filter((s) => s.kind !== "credit");
  const credits = subscriptions.filter((s) => s.kind === "credit");
  // A balance can always be topped up; a membership or bundle is bought once at a time.
  const offers = plans.filter((p) => p.kind === "credit" || visits.length === 0);
  if (offers.length === 0 && subscriptions.length === 0) return null;
  return (
    <section className={styles.section} aria-labelledby="ms-title">
      <h2 id="ms-title" className={styles.sectionTitle}>
        {visits.length === 0 && offers.every((p) => p.kind === "credit") ? t("titleBalance") : t("title")}
      </h2>
      {(balance.cents > 0 || credits.some((s) => s.status === "pending")) && (
        <BalanceBlock balance={balance} history={history} pending={credits.some((s) => s.status === "pending")} />
      )}
      {visits.map((s) => (
        <Mine key={s.id} path={path} sub={s} onChange={onChange} />
      ))}
      {offers.map((p) => (
        <Offer key={p.id} path={path} plan={p} />
      ))}
    </section>
  );
}

function BalanceBlock({ balance, history, pending }: { balance: Balance; history: BalanceLine[]; pending: boolean }) {
  const t = useTranslations("membership");
  const locale = useLocale();
  const format = useFormatter();
  const day = (iso: string) => format.dateTime(new Date(iso), { day: "numeric", month: "long", year: "numeric" });
  const label = (l: BalanceLine) =>
    l.kind === "topup" ? t("lineTopup") : l.kind === "expire" ? t("lineExpire") : l.kind === "refund" ? t("lineRefund") : l.undone ? t("lineUndone") : t("lineSpend");
  return (
    <div className={styles.form}>
      {balance.cents > 0 && (
        <div className={styles.balanceHead}>
          <p>
            <strong>{t("balanceTitle")}</strong>
          </p>
          <p className={styles.balanceAmount}>{euros(balance.cents, locale)}</p>
          {balance.parts.map((p) => (
            <p key={p.expires} className={styles.muted}>
              {balance.parts.length > 1
                ? t("balancePartUntil", { amount: euros(p.cents, locale), date: day(p.expires) })
                : t("balanceUntil", { date: day(p.expires) })}
            </p>
          ))}
        </div>
      )}
      {pending && <p className={styles.muted}>{t("pending")}</p>}
      {history.length > 0 && (
        <ul className={styles.ledger} aria-label={t("historyTitle")}>
          {history.map((l, i) => (
            <li key={`${l.at}-${i}`} className={l.undone ? styles.ledgerUndone : undefined}>
              <span>
                {label(l)} <span className={styles.muted}>{format.dateTime(new Date(l.at), { day: "numeric", month: "short" })}</span>
              </span>
              <span className={styles.ledgerAmount}>
                {l.cents > 0 ? "+" : "−"}
                {euros(Math.abs(l.cents), locale)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
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
          <p>{t("creditsLeft", { count: sub.credits ?? 0 })}</p>
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
  const isCredit = plan.kind === "credit";
  const value = isCredit && plan.value_cents ? euros(plan.value_cents, locale) : "";

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
      {isCredit ? (
        <div className={styles.offerCredit}>
          <p>
            <strong>{plan.name}</strong>
          </p>
          <p className={styles.offerLine}>
            {t("creditPayGet", { price, value })}
            {plan.bonus_percent ? <span className={styles.bonus}>{t("bonus", { percent: plan.bonus_percent })}</span> : null}
          </p>
          <p className={styles.muted}>{t("creditValid", { days: plan.validity_days ?? 365 })}</p>
        </div>
      ) : (
        <>
          <p>
            <strong>{plan.name}</strong> · {plan.renews ? t("perMonth", { price }) : t("once", { price })}
          </p>
          <p className={styles.muted}>
            {plan.renews ? t("creditsMonth", { count: plan.credits }) : t("creditsTotal", { count: plan.credits, days: plan.validity_days ?? 0 })}
          </p>
        </>
      )}
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
            {isCredit ? (
              <>
                <dt>{t("creditUse")}</dt>
                <dd>{t("creditUseBody", { value })}</dd>
              </>
            ) : (
              <>
                <dt>{t("noShow")}</dt>
                <dd>{plan.no_show_policy}</dd>
                <dt>{t("pause")}</dt>
                <dd>{plan.pause_policy}</dd>
              </>
            )}
            {plan.refund_policy && (
              <>
                <dt>{t("refund")}</dt>
                <dd>{plan.refund_policy}</dd>
              </>
            )}
          </dl>
          <p className={styles.muted}>{t("version", { version: plan.terms_version })}</p>
          <p>{plan.renews ? t("charge", { price }) : isCredit ? t("chargeCredit", { price, value }) : t("chargeOnce", { price })}</p>
          <label className={styles.check}>
            <input type="checkbox" checked={accepted} onChange={(e) => setAccepted(e.target.checked)} />
            <span>{t("accept")}</span>
          </label>
          {error && <Notice tone="danger">{error}</Notice>}
          <Button type="button" size="large" onClick={buy} disabled={!accepted} aria-describedby={accepted ? undefined : `accept-${plan.id}`}>
            {t("buy")} · {price}
          </Button>
          {!accepted && (
            <p id={`accept-${plan.id}`} className={styles.muted}>
              {t("acceptFirst")}
            </p>
          )}
        </>
      )}
    </div>
  );
}
