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

type Data = { plans: (PlanTerms & { active: boolean })[]; connected: boolean; selling_enabled: boolean };

const EMPTY = {
  kind: "membership",
  name: "",
  price: "35",
  credits: 2,
  validity_days: 180,
  cancel_notice_days: 0,
  cooling_off_days: 14,
  unused_policy: "",
  no_show_policy: "",
  pause_policy: "",
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

  const set = (k: keyof typeof EMPTY) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
    setF({ ...f, [k]: e.target.type === "number" ? Number(e.target.value) : e.target.value });

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
      const { price, ...rest } = f;
      await api("/plans", {
        method: "POST",
        json: { ...rest, price_cents: Math.round(Number(price.replace(",", ".")) * 100), validity_days: f.kind === "bundle" ? f.validity_days : null },
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
                <span className={s.kind}>{p.kind === "membership" ? t("kindMembership") : t("kindBundle")}</span>
                <span className={s.name}>{p.name}</span>
                <p className={s.reason}>
                  {euros(p.price_cents, locale)} · {p.credits} · v{p.terms_version}
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
              </select>
            </label>
            <Field label={t("name")} value={f.name} onChange={set("name")} required minLength={2} maxLength={80} />
          </div>
          <div className={w.triple}>
            <Field label={t("price")} inputMode="decimal" value={f.price} onChange={set("price")} required />
            <Field label={t("credits")} type="number" min={1} max={100} value={f.credits} onChange={set("credits")} />
            {f.kind === "bundle" ? (
              <Field label={t("validity")} type="number" min={30} max={1095} value={f.validity_days} onChange={set("validity_days")} />
            ) : (
              <Field label={t("notice")} type="number" min={0} max={31} value={f.cancel_notice_days} onChange={set("cancel_notice_days")} />
            )}
          </div>
          <Field label={t("coolingOff")} type="number" min={14} max={60} value={f.cooling_off_days} onChange={set("cooling_off_days")} />
          {(["unused_policy", "no_show_policy", "pause_policy"] as const).map((k) => (
            <label key={k} className={uiStyles.field}>
              <span className={uiStyles.label}>{t(k === "unused_policy" ? "unused" : k === "no_show_policy" ? "noShow" : "pause")}</span>
              <textarea className={s.textarea} value={f[k]} onChange={set(k)} required minLength={10} maxLength={600} />
            </label>
          ))}
          <p className={w.muted}>{t("versionNote")}</p>
          <div className={w.actions}>
            <Button type="submit">{t("save")}</Button>
          </div>
        </form>
      </Panel>
    </div>
  );
}
