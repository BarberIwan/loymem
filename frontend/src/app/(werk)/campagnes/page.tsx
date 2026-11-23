"use client";

import { useFormatter, useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";

import { Button, EmptyState, Field, Notice, Panel, uiStyles } from "@/components/ui";
import { api } from "@/lib/api";
import { useErrorText } from "@/lib/useErrorText";

import shell from "../shell.module.css";
import s from "../vandaag/vandaag.module.css";
import w from "../werk.module.css";

type Report = {
  status: string;
  verdict?: "window_open" | "too_small" | "not_demonstrable" | "demonstrable";
  observed?: { sent: number; returned: number; control: number; control_returned: number };
  estimated_extra_visits?: number;
};
type Campaign = {
  id: string;
  name: string;
  audience: string;
  message: string;
  holdout_percent: number;
  window_days: number;
  sent_at: string | null;
  size: number;
  control: number;
  report: Report;
};

const AUDIENCES = ["due_for_visit", "lapsed_60", "all_consented"] as const;

export default function CampaignsPage() {
  const t = useTranslations("campaigns");
  const format = useFormatter();
  const errorText = useErrorText();
  const [list, setList] = useState<Campaign[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [f, setF] = useState({ name: "", audience: "due_for_visit", message: "", holdout_percent: 10, window_days: 30 });

  const load = useCallback(() => {
    api<Campaign[]>("/campaigns").then(setList, (e) => setError(errorText(e)));
  }, [errorText]);
  useEffect(load, [load]);

  async function run(fn: () => Promise<unknown>) {
    try {
      await fn();
      setError(null);
    } catch (e) {
      setError(errorText(e));
    }
    load();
  }

  const date = (iso: string, plusDays = 0) => format.dateTime(new Date(new Date(iso).getTime() + plusDays * 86_400_000), { day: "numeric", month: "long" });

  return (
    <div className={s.column}>
      <div className={s.header}>
        <h1 className={shell.title}>{t("title")}</h1>
        <p className={w.muted}>{t("lead")}</p>
      </div>
      {error && <Notice tone="danger">{error}</Notice>}
      {list &&
        (list.length === 0 ? (
          <EmptyState title={t("emptyTitle")} body={t("emptyBody")} example={t("emptyExample")} />
        ) : (
          <ul className={s.list}>
            {list.map((c) => (
              <li key={c.id} className={s.card}>
                <span className={s.kind}>{t(`a_${c.audience}` as "a_due_for_visit")}</span>
                <span className={s.name}>{c.name}</span>
                <p className={s.message}>{c.message}</p>
                <p className={s.detail}>{t("size", { size: c.size, control: c.control })}</p>
                {c.sent_at ? (
                  <>
                    <p className={s.detail}>{t("sentOn", { date: date(c.sent_at) })}</p>
                    {c.report.observed && <p className={s.reason}>{t("observed", c.report.observed)}</p>}
                    <p className={s.note}>
                      {c.report.verdict === "window_open"
                        ? t("r_window_open", { date: date(c.sent_at, c.window_days) })
                        : c.report.verdict === "demonstrable"
                          ? t("r_demonstrable", { extra: c.report.estimated_extra_visits ?? 0 })
                          : t(`r_${c.report.verdict ?? "too_small"}` as "r_too_small")}
                    </p>
                  </>
                ) : (
                  <div className={s.actions}>
                    <Button type="button" onClick={() => run(() => api(`/campaigns/${c.id}/send`, { method: "POST" }))} disabled={c.size - c.control === 0}>
                      {t("send")}
                    </Button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        ))}
      <Panel title={t("new")}>
        <form
          className={w.stack}
          onSubmit={(e) => {
            e.preventDefault();
            run(() => api("/campaigns", { method: "POST", json: f }));
          }}
        >
          <p className={w.muted}>{t("consentNote")}</p>
          <div className={w.pair}>
            <Field label={t("name")} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} required minLength={2} maxLength={80} />
            <label className={uiStyles.field}>
              <span className={uiStyles.label}>{t("audience")}</span>
              <select className={uiStyles.input} value={f.audience} onChange={(e) => setF({ ...f, audience: e.target.value })}>
                {AUDIENCES.map((a) => (
                  <option key={a} value={a}>
                    {t(`a_${a}`)}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <label className={uiStyles.field}>
            <span className={uiStyles.label}>{t("message")}</span>
            <textarea className={s.textarea} value={f.message} onChange={(e) => setF({ ...f, message: e.target.value })} required minLength={10} maxLength={600} />
          </label>
          <div className={w.pair}>
            <Field label={t("holdout")} type="number" min={5} max={50} value={f.holdout_percent} onChange={(e) => setF({ ...f, holdout_percent: Number(e.target.value) })} />
            <Field label={t("window")} type="number" min={7} max={90} value={f.window_days} onChange={(e) => setF({ ...f, window_days: Number(e.target.value) })} />
          </div>
          <div className={w.actions}>
            <Button type="submit">{t("create")}</Button>
          </div>
        </form>
      </Panel>
    </div>
  );
}
