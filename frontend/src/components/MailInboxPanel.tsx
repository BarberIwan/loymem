"use client";

import { useFormatter, useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";

import { api } from "@/lib/api";
import { useErrorText } from "@/lib/useErrorText";

import { Button, Field, Notice, Panel } from "./ui";
import s from "./ui.module.css";

type Inbox = {
  set_up: boolean;
  domain_ready: boolean;
  systems: { name: string; sender: string }[];
  address?: string | null;
  active?: boolean;
  count_visits?: boolean;
  gmail_code?: string | null;
  last_received_at?: string | null;
  recent?: { kind: string; outcome: string; at: string }[];
};

/** Appointments from forwarded booking mails, for systems without an open connection. Owner only. */
export function MailInboxPanel() {
  const t = useTranslations("mailInbox");
  const format = useFormatter();
  const errorText = useErrorText();
  const [inbox, setInbox] = useState<Inbox | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const load = useCallback(() => {
    api<Inbox>("/mail-inbox").then(setInbox, () => setInbox(null));
  }, []);
  useEffect(load, [load]);
  if (!inbox) return null;

  const systems = inbox.systems.map((x) => x.name).join(", ");
  const sender = inbox.systems[0]?.sender ?? "";

  async function call(path: string, init: { method: string; json?: unknown }) {
    setError(null);
    try {
      setInbox(await api<Inbox>(path, init));
    } catch (e) {
      setError(errorText(e));
    }
  }

  async function copy() {
    if (!inbox?.address) return;
    try {
      await navigator.clipboard.writeText(inbox.address);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  const set = (patch: Partial<Pick<Inbox, "active" | "count_visits">>) =>
    call("/mail-inbox", { method: "PATCH", json: { active: inbox.active, count_visits: inbox.count_visits, ...patch } });

  return (
    <Panel title={t("title")}>
      <div className={s.empty}>
        <p className={s.emptyBody}>{t("lead", { systems })}</p>
        {!inbox.domain_ready ? (
          <Notice>{t("notReady")}</Notice>
        ) : !inbox.set_up ? (
          <Button type="button" onClick={() => call("/mail-inbox", { method: "POST" })}>
            {t("setUp")}
          </Button>
        ) : (
          <>
            <Field label={t("address")} value={inbox.address ?? ""} readOnly onFocus={(e) => e.target.select()} help={t("addressHelp")} />
            <div>
              <Button type="button" variant="secondary" onClick={copy}>
                {copied ? t("copied") : t("copy")}
              </Button>
            </div>
            <p className={s.label}>{t("howTitle")}</p>
            <ol className={s.steps}>
              <li>{t("step1")}</li>
              <li>{t("step2", { address: inbox.address ?? "" })}</li>
              <li>{inbox.gmail_code ? t("step3Code", { code: inbox.gmail_code }) : t("step3Wait")}</li>
              <li>{t("step4", { sender })}</li>
              <li>{t("step5")}</li>
            </ol>
            <label className={s.check}>
              <input type="checkbox" checked={!!inbox.count_visits} onChange={(e) => set({ count_visits: e.target.checked })} />
              <span className={s.checkText}>
                <span>{t("countVisits")}</span>
                <span className={s.help}>{t("countVisitsHelp")}</span>
              </span>
            </label>
            <label className={s.check}>
              <input type="checkbox" checked={!!inbox.active} onChange={(e) => set({ active: e.target.checked })} />
              <span>{t("active")}</span>
            </label>
            <p className={s.label}>{t("recent")}</p>
            {!inbox.recent || inbox.recent.length === 0 ? (
              <p className={s.help}>{t("none")}</p>
            ) : (
              inbox.recent.map((r, i) => (
                <p key={i} className={s.help}>
                  {format.dateTime(new Date(r.at), { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })} ·{" "}
                  {t(`k_${r.kind}` as "k_booked")} · {t(`o_${r.outcome}` as "o_matched")}
                </p>
              ))
            )}
            <Button type="button" variant="secondary" onClick={() => call("/mail-inbox?rotate=true", { method: "POST" })}>
              {t("rotate")}
            </Button>
          </>
        )}
        {error && <Notice tone="danger">{error}</Notice>}
      </div>
    </Panel>
  );
}
