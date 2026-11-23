"use client";

import { useFormatter, useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";

import { Button, EmptyState, LinkButton, Notice } from "@/components/ui";
import { api } from "@/lib/api";
import { useErrorText } from "@/lib/useErrorText";
import { useMe } from "@/lib/useMe";

import shell from "../shell.module.css";
import w from "../werk.module.css";
import s from "./vandaag.module.css";

type Item = {
  customer_id: string;
  kind: "due_for_visit" | "reward_unused";
  first_name: string | null;
  facts: Record<string, string | number | null>;
  action: "message" | "in_person";
  booking_url: string | null;
};
type Inbox = { items: Item[]; daily_limit: number; ignore_days: number };

export default function TodayPage() {
  const t = useTranslations("inbox");
  const errorText = useErrorText();
  const [data, setData] = useState<Inbox | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const me = useMe();

  const load = useCallback(() => {
    api<Inbox>("/inbox").then(setData, (e) => setError(errorText(e)));
  }, [errorText]);
  useEffect(load, [load]);

  return (
    <>
      <div className={s.header}>
        <h1 className={shell.title}>{t("title")}</h1>
        {data && <p className={w.muted}>{t("lead", { count: data.items.length, limit: data.daily_limit })}</p>}
      </div>
      {error && <Notice tone="danger">{error}</Notice>}
      {notice && <Notice>{notice}</Notice>}
      {data &&
        (data.items.length === 0 ? (
          <EmptyState
            title={t("emptyTitle")}
            body={t("emptyBody")}
            example={t("emptyExample")}
            action={<LinkButton href="/instellingen">{t("emptyAction")}</LinkButton>}
          />
        ) : (
          <ul className={s.list}>
            {data.items.map((item) => (
              <Opportunity
                key={`${item.customer_id}-${item.kind}`}
                item={item}
                ignoreDays={data.ignore_days}
                business={me?.business.name ?? ""}
                onDone={(text) => {
                  setNotice(text);
                  setError(null);
                  load();
                }}
                onError={(e) => setError(errorText(e))}
              />
            ))}
          </ul>
        ))}
    </>
  );
}

function Opportunity({ item, ignoreDays, business, onDone, onError }: { item: Item; ignoreDays: number; business: string; onDone: (t: string) => void; onError: (e: unknown) => void }) {
  const t = useTranslations("inbox");
  const format = useFormatter();
  const name = item.first_name ?? t("customer");
  const f = item.facts;
  const date = (v: unknown) => format.dateTime(new Date(String(v)), { day: "numeric", month: "long" });
  const base =
    item.kind === "reward_unused"
      ? t("messageReward", { name: item.first_name ?? "", reward: String(f.reward), business })
      : t("messageDue", { name: item.first_name ?? "", business });
  const suggested = item.booking_url ? `${base} ${t("messageLink", { url: item.booking_url })}` : base;
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const message = text ?? suggested;

  async function decide(decision: "sent" | "done" | "ignored") {
    setBusy(true);
    try {
      await api("/inbox/decide", {
        method: "POST",
        json: { customer_id: item.customer_id, kind: item.kind, decision, message: decision === "sent" ? message : undefined },
      });
      onDone(
        decision === "sent" ? t("sent", { name }) : decision === "done" ? t("handled", { name }) : t("ignored", { name, days: ignoreDays }),
      );
    } catch (e) {
      onError(e);
      setBusy(false);
    }
  }

  return (
    <li className={s.card}>
      <span className={s.kind}>
        {item.kind === "reward_unused" ? t("kindReward") : item.action === "in_person" ? t("kindInPerson") : t("kindDue")}
      </span>
      <span className={s.name}>{name}</span>
      {item.kind === "reward_unused" ? (
        <p className={s.reason}>{t("rewardReason", { reward: String(f.reward), date: date(f.earned_on) })}</p>
      ) : (
        <>
          <p className={s.reason}>{t("dueReason", { date: date(f.last_visit) })}</p>
          <p className={s.detail}>
            {f.service ? t("dueDetail", { service: String(f.service), days: Number(f.return_period_days) }) : t("dueDetailNoService", { days: Number(f.days_since) })}
            {f.personal_rhythm_days ? ` ${t("rhythm", { days: Number(f.personal_rhythm_days) })}` : ""}
          </p>
        </>
      )}
      {item.action === "message" ? (
        <>
          {editing ? (
            <>
              <label className="visually-hidden" htmlFor={`m-${item.customer_id}`}>
                {t("messageLabel", { name })}
              </label>
              <textarea id={`m-${item.customer_id}`} className={s.textarea} value={message} maxLength={600} onChange={(e) => setText(e.target.value)} autoFocus />
            </>
          ) : (
            <p className={s.message} aria-label={t("messageLabel", { name })}>
              {message}
            </p>
          )}
          <div className={s.actions}>
            <Button type="button" onClick={() => decide("sent")} disabled={busy || message.trim().length < 5}>
              {t("send")}
            </Button>
            {!editing && (
              <Button type="button" variant="secondary" onClick={() => setEditing(true)}>
                {t("edit")}
              </Button>
            )}
            <button type="button" className={s.quiet} onClick={() => decide("ignored")} disabled={busy}>
              {t("ignore", { days: ignoreDays })}
            </button>
          </div>
        </>
      ) : (
        <>
          <p className={s.note}>{t("inPerson", { name })}</p>
          <div className={s.actions}>
            <Button type="button" onClick={() => decide("done")} disabled={busy}>
              {t("done")}
            </Button>
            <button type="button" className={s.quiet} onClick={() => decide("ignored")} disabled={busy}>
              {t("ignore", { days: ignoreDays })}
            </button>
          </div>
        </>
      )}
    </li>
  );
}
