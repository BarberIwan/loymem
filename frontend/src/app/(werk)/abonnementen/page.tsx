"use client";

import { useLocale, useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";

import { Button, EmptyState, Field, Notice, Panel, uiStyles } from "@/components/ui";
import { api } from "@/lib/api";
import { euros } from "@/lib/money";
import { useErrorText } from "@/lib/useErrorText";
import type { PlanTerms } from "@/app/k/[slug]/[secret]/Memberships";

import shell from "../shell.module.css";
import s from "../vandaag/vandaag.module.css";
import w from "../werk.module.css";

type PolicyOptions = {
  unused_membership: Record<string, string>;
  no_show: Record<string, string>;
  unused_bundle: string;
  unused_credit: string;
  pause: string;
};
type Data = { plans: (PlanTerms & { active: boolean })[]; connected: boolean; selling_enabled: boolean; policy_options: PolicyOptions };

/** Above this the bonus is generous enough that the owner should see what it costs. */
const BONUS_WATCH = 30;
const cents = (v: string) => Math.round(Number(v.replace(/\s/g, "").replace(",", ".")) * 100);

const EMPTY = {
  kind: "membership",
  name: "",
  price: "35",
  value: "",
  credits: 2,
  validity_days: 180,
  cancel_notice_days: 0,
  cooling_off_days: 14,
  unused_rule: "expire_period",
  no_show_rule: "no_show_counts",
};

export default function PlansPage() {
  const t = useTranslations("plans");
  const locale = useLocale();
  const errorText = useErrorText();
  const [data, setData] = useState<Data | null>(null);
  const [f, setF] = useState(EMPTY);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api<Data>("/plans").then(setData, (e) => setError(errorText(e)));
  }, [errorText]);
  useEffect(load, [load]);

  const set = (k: keyof typeof EMPTY) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => {
    const next = { ...f, [k]: e.target.type === "number" ? Number(e.target.value) : e.target.value };
    if (k === "kind" && e.target.value === "credit") {
      next.validity_days = Math.max(365, f.validity_days);
      if (!f.value) next.value = "60";
      if (f.price === "35") next.price = "50";
    }
    setF(next);
  };
  const isCredit = f.kind === "credit";
  const priceCents = cents(f.price);
  const valueCents = cents(f.value);
  const bonus = isCredit && priceCents > 0 && valueCents >= priceCents ? Math.floor(((valueCents - priceCents) * 100) / priceCents) : null;

  async function connect() {
    try {
      const r = await api<{ url: string }>("/payments/connect");
      window.location.href = r.url;
    } catch (e) {
      setError(errorText(e));
    }
  }

  async function create(e: React.FormEvent) {
    e.preventDefault();
    try {
      const { price, value, ...rest } = f;
      await api("/plans", {
        method: "POST",
        json: {
          ...rest,
          price_cents: cents(price),
          value_cents: isCredit ? cents(value) : null,
          credits: isCredit ? 0 : f.credits,
          validity_days: f.kind === "membership" ? null : f.validity_days,
          unused_rule: f.kind === "membership" ? f.unused_rule : null,
          no_show_rule: isCredit ? null : f.no_show_rule,
        },
      });
      setF(EMPTY);
      setError(null);
      load();
    } catch (err) {
      setError(errorText(err));
    }
  }

  return (
    <div className={s.column}>
      <div className={s.header}>
        <h1 className={shell.title}>{t("title")}</h1>
        <p className={w.muted}>{t("lead")}</p>
      </div>
      {data && !data.selling_enabled && <Notice>{t("off")}</Notice>}
      {error && <Notice tone="danger">{error}</Notice>}
      {data &&
        (data.connected ? (
          <p className={w.muted}>{t("connected")}</p>
        ) : (
          <div>
            <Button type="button" variant="secondary" onClick={connect}>
              {t("connect")}
            </Button>
          </div>
        ))}
      {data &&
        (data.plans.length === 0 ? (
          <EmptyState title={t("emptyTitle")} body={t("emptyBody")} example={t("emptyExample")} />
        ) : (
          <ul className={s.list}>
            {data.plans.map((p) => (
              <li key={p.id} className={s.card}>
                <span className={s.kind}>{p.kind === "membership" ? t("kindMembership") : p.kind === "credit" ? t("kindCredit") : t("kindBundle")}</span>
                <span className={s.name}>{p.name}</span>
                <p className={s.reason}>
                  {p.kind === "credit"
                    ? t("summaryCredit", {
                        price: euros(p.price_cents, locale),
                        value: euros(p.value_cents ?? 0, locale),
                        percent: p.bonus_percent ?? 0,
                        days: p.validity_days ?? 365,
                        version: p.terms_version,
                      })
                    : t(p.kind === "membership" ? "summaryMonth" : "summaryOnce", { price: euros(p.price_cents, locale), count: p.credits, version: p.terms_version })}
                </p>
                <p className={s.detail}>{p.unused_policy}</p>
              </li>
            ))}
          </ul>
        ))}
      <Panel title={t("new")}>
        <form className={w.stack} onSubmit={create}>
          <div className={w.pair}>
            <label className={uiStyles.field}>
              <span className={uiStyles.label}>{t("kind")}</span>
              <select className={uiStyles.input} value={f.kind} onChange={set("kind")}>
                <option value="membership">{t("kindMembership")}</option>
                <option value="bundle">{t("kindBundle")}</option>
                <option value="credit">{t("kindCredit")}</option>
              </select>
            </label>
            <Field label={t("name")} value={f.name} onChange={set("name")} required minLength={2} maxLength={80} />
          </div>
          {isCredit ? (
            <>
              <div className={w.triple}>
                <Field label={t("pays")} inputMode="decimal" value={f.price} onChange={set("price")} required />
                <Field label={t("spends")} inputMode="decimal" value={f.value} onChange={set("value")} required />
                <Field label={t("validity")} type="number" min={365} max={1095} value={f.validity_days} onChange={set("validity_days")} />
              </div>
              {bonus !== null && priceCents > 0 && (
                <Notice tone={bonus > 100 ? "danger" : undefined}>
                  {bonus > 100
                    ? t("bonusTooHigh")
                    : t(bonus > BONUS_WATCH ? "bonusWatch" : "bonusFine", {
                        percent: bonus,
                        perEuro: euros(Math.round((priceCents * 100) / valueCents), locale),
                      })}
                </Notice>
              )}
              {isCredit && valueCents > 0 && valueCents < priceCents && <Notice tone="danger">{t("valueBelowPrice")}</Notice>}
            </>
          ) : (
            <div className={w.triple}>
              <Field label={t("price")} inputMode="decimal" value={f.price} onChange={set("price")} required />
              <Field label={t("credits")} type="number" min={1} max={100} value={f.credits} onChange={set("credits")} />
              {f.kind === "bundle" ? (
                <Field label={t("validity")} type="number" min={30} max={1095} value={f.validity_days} onChange={set("validity_days")} />
              ) : (
                <Field label={t("notice")} type="number" min={0} max={31} value={f.cancel_notice_days} onChange={set("cancel_notice_days")} />
              )}
            </div>
          )}
          <Field label={t("coolingOff")} type="number" min={14} max={60} value={f.cooling_off_days} onChange={set("cooling_off_days")} />
          {data && <Terms kind={f.kind} options={data.policy_options} unused={f.unused_rule} noShow={f.no_show_rule} onChange={(k, v) => setF({ ...f, [k]: v })} />}
          <p className={w.muted}>{t("versionNote")}</p>
          <div className={w.actions}>
            <Button type="submit">{t("save")}</Button>
          </div>
        </form>
      </Panel>
    </div>
  );
}

/** The terms a customer will read, chosen from fixed sentences that a lawyer checked once. */
function Terms({ kind, options, unused, noShow, onChange }: {
  kind: string;
  options: PolicyOptions;
  unused: string;
  noShow: string;
  onChange: (key: "unused_rule" | "no_show_rule", value: string) => void;
}) {
  const t = useTranslations("plans");
  return (
    <div className={w.stack}>
      <div>
        <p className={uiStyles.label}>{t("termsHeading")}</p>
        <p className={w.muted}>{t("termsLead")}</p>
      </div>
      {kind === "membership" ? (
        <Choice legend={t("unused")} name="unused_rule" value={unused} options={options.unused_membership} labels={(k) => t(`unusedOpt.${k}`)} onChange={(v) => onChange("unused_rule", v)} />
      ) : (
        <Fixed label={kind === "credit" ? t("unusedCredit") : t("unused")} text={kind === "credit" ? options.unused_credit : options.unused_bundle} />
      )}
      {kind !== "credit" && (
        <>
          <Choice legend={t("noShow")} name="no_show_rule" value={noShow} options={options.no_show} labels={(k) => t(`noShowOpt.${k}`)} onChange={(v) => onChange("no_show_rule", v)} />
          <Fixed label={t("pause")} text={options.pause} />
        </>
      )}
    </div>
  );
}

function Choice({ legend, name, value, options, labels, onChange }: {
  legend: string;
  name: string;
  value: string;
  options: Record<string, string>;
  labels: (key: string) => string;
  onChange: (value: string) => void;
}) {
  return (
    <fieldset className={w.choices}>
      <legend className={uiStyles.label}>{legend}</legend>
      {Object.entries(options).map(([key, sentence]) => (
        <label key={key} className={w.choice}>
          <input type="radio" name={name} value={key} checked={value === key} onChange={() => onChange(key)} />
          <span className={w.choiceBody}>
            <span className={w.choiceTitle}>{labels(key)}</span>
            <span className={w.choiceText}>{sentence}</span>
          </span>
        </label>
      ))}
    </fieldset>
  );
}

function Fixed({ label, text }: { label: string; text: string }) {
  const t = useTranslations("plans");
  return (
    <div className={w.fixed}>
      <span className={uiStyles.label}>
        {label} <span className={uiStyles.labelMuted}>({t("fixed")})</span>
      </span>
      <span className={w.choiceText}>{text}</span>
    </div>
  );
}
