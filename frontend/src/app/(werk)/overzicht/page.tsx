"use client";

import { useFormatter, useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";

import { Button, EmptyState, Field, LinkButton, Notice, Panel, Stat } from "@/components/ui";
import { api } from "@/lib/api";
import { useErrorText } from "@/lib/useErrorText";

import w from "../werk.module.css";
import shell from "../shell.module.css";

type Signal = { kind: string; staff?: string; count?: number };
type Event = { id: string; kind: string; delta: number; customer: string; staff: string; reason: string | null; at: string; reversible: boolean };
type Overview = {
  customers: number;
  new_customers_30d: number;
  stamps_30d: number;
  rewards_redeemed_30d: number;
  rewards_open: number;
  due_for_visit: number;
  signals: Signal[];
  recent: Event[];
};

export default function OverviewPage() {
  const t = useTranslations("overview");
  const errorText = useErrorText();
  const [data, setData] = useState<Overview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);

  const load = useCallback(() => {
    api<Overview>("/overview").then(setData).catch((e) => setError(errorText(e)));
  }, [errorText]);
  useEffect(load, [load]);

  async function importFile(file: File) {
    const body = new FormData();
    body.append("file", file);
    try {
      const r = await api<{ added: number; skipped: number }>("/customers/import", { method: "POST", body });
      setNotice(t("importDone", r));
      load();
    } catch (e) {
      setError(errorText(e));
    }
  }

  return (
    <>
      <div className={w.head}>
        <h1 className={shell.title}>{t("title")}</h1>
        <span className={w.muted}>{t("period")}</span>
      </div>
      {error && <Notice tone="danger">{error}</Notice>}
      {notice && <Notice>{notice}</Notice>}
      {data && (
        <>
          <div className={w.stats}>
            <Stat label={t("customers")} value={data.customers} note={t("newCustomers", { count: data.new_customers_30d })} />
            <Stat label={t("stamps")} value={data.stamps_30d} note={t("stampsNote")} />
            <Stat label={t("redeemed")} value={data.rewards_redeemed_30d} note={t("open", { count: data.rewards_open })} />
            <Stat label={t("due")} value={data.due_for_visit} note={t("dueHint")} />
          </div>
          {data.signals.length > 0 && (
            <Panel title={t("signals")}>
              <div className={w.stack}>
                {data.signals.map((sg, i) => (
                  <p key={i} className={w.signal}>
                    {t(sg.kind as "many_corrections", { staff: sg.staff ?? "", count: sg.count ?? 0 })}
                  </p>
                ))}
              </div>
            </Panel>
          )}
          <Panel title={t("recent")}>
            {data.recent.length === 0 ? (
              <EmptyState
                title={t("emptyTitle")}
                body={t("emptyBody")}
                example={t("emptyExample")}
                action={<LinkButton href="/instellingen#aanmelden">{t("emptyAction")}</LinkButton>}
              />
            ) : (
              <ul className={w.list}>
                {data.recent.slice(0, showAll ? undefined : 10).map((ev) => (
                  <Row key={ev.id} ev={ev} onChanged={load} onError={(e) => setError(errorText(e))} />
                ))}
              </ul>
            )}
            {!showAll && data.recent.length > 10 && (
              <button type="button" className={w.textButton} onClick={() => setShowAll(true)}>
                {t("more")}
              </button>
            )}
          </Panel>
          <div className={w.actions}>
            <LinkButton variant="secondary" href="/api/v1/export">
              {t("export")}
            </LinkButton>
            <label className={w.muted}>
              <span className="visually-hidden">{t("import")}</span>
              <input type="file" accept=".csv,text/csv" className={w.hidden} id="import" onChange={(e) => e.target.files?.[0] && importFile(e.target.files[0])} />
              <Button variant="secondary" type="button" onClick={() => document.getElementById("import")?.click()}>
                {t("import")}
              </Button>
            </label>
            <span className={w.muted}>{t("importHint")}</span>
          </div>
        </>
      )}
    </>
  );
}

function Row({ ev, onChanged, onError }: { ev: Event; onChanged: () => void; onError: (e: unknown) => void }) {
  const t = useTranslations("overview");
  const common = useTranslations("common");
  const format = useFormatter();
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");

  async function reverse() {
    try {
      await api(`/events/${ev.id}/reverse`, { method: "POST", json: { reason } });
      setOpen(false);
      onChanged();
    } catch (e) {
      onError(e);
    }
  }

  return (
    <li className={w.item}>
      <span>
        <span className={w.what}>{ev.customer || "·"}</span> {t(`kind_${ev.kind}` as "kind_stamp")}
        {ev.reason ? `: ${ev.reason}` : ""}
      </span>
      <span className={w.when}>
        {format.dateTime(new Date(ev.at), { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}
        {ev.staff ? ` ${t("by", { name: ev.staff })}` : ""}
      </span>
      {ev.reversible && !open && (
        <button type="button" className={w.textButton} onClick={() => setOpen(true)}>
          {t("undo")}
        </button>
      )}
      {open && (
        <div className={w.reverse}>
          <Field label={t("reason")} placeholder={t("reasonPlaceholder")} value={reason} onChange={(e) => setReason(e.target.value)} minLength={3} autoFocus />
          <Button variant="secondary" type="button" onClick={() => setOpen(false)}>
            {common("cancel")}
          </Button>
          <Button variant="danger" type="button" onClick={reverse} disabled={reason.trim().length < 3}>
            {t("undo")}
          </Button>
        </div>
      )}
    </li>
  );
}
