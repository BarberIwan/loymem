"use client";

import { useFormatter, useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";

import { Button, EmptyState, Field, Notice, Panel, uiStyles } from "@/components/ui";
import { api } from "@/lib/api";
import { useBenefitText } from "@/lib/benefit";
import { useErrorText } from "@/lib/useErrorText";

import shell from "../shell.module.css";
import w from "../werk.module.css";
import s from "../vandaag/vandaag.module.css";

type Recipient = { customer_id: string; first_name: string | null; reason: string; status: string };
type Offer = {
  id: string;
  service: string | null;
  staff_name: string | null;
  starts_at: string;
  book_by: string;
  benefit: string;
  benefit_value: number;
  benefit_text: string | null;
  capacity: number;
  claims: number;
  status: string;
  sending_started: boolean;
  next_send_at: string | null;
  recipients: Recipient[];
};
type Service = { id: string; name: string };

const clock = (iso: string) => iso.slice(11, 16);

function local(d: Date) {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

type Freed = { starts_at: string; service: string | null; staff: string | null };

function inHours(h: number) {
  const d = new Date(Date.now() + h * 3600_000);
  d.setMinutes(Math.ceil(d.getMinutes() / 15) * 15, 0, 0);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export default function SlotsPage() {
  const t = useTranslations("slots");
  const errorText = useErrorText();
  const [offers, setOffers] = useState<Offer[] | null>(null);
  const [services, setServices] = useState<Service[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [freed, setFreed] = useState<Freed[]>([]);
  const [prefill, setPrefill] = useState<{ starts_at: string; staff_name: string; key: number } | null>(null);

  const load = useCallback(() => {
    api<Offer[]>("/slots").then(setOffers, (e) => setError(errorText(e)));
    api<Freed[]>("/slots/freed").then(setFreed, () => setFreed([]));
  }, [errorText]);
  useEffect(() => {
    load();
    api<{ services: Service[] }>("/settings").then((d) => setServices(d.services), () => undefined);
  }, [load]);

  async function run(fn: () => Promise<unknown>) {
    try {
      await fn();
      setError(null);
    } catch (e) {
      setError(errorText(e));
    }
    load();
  }

  return (
    <div className={s.column}>
      <div className={s.header}>
        <h1 className={shell.title}>{t("title")}</h1>
        <p className={w.muted}>{t("lead")}</p>
      </div>
      <Notice>{t("slow")}</Notice>
      {error && <Notice tone="danger">{error}</Notice>}
      {freed.length > 0 && (
        <FreedList
          freed={freed}
          onPick={(x) => {
            const start = new Date(x.starts_at);
            setPrefill({ starts_at: local(start), staff_name: x.staff ?? "", key: Date.now() });
          }}
        />
      )}
      <NewOffer
        key={prefill?.key ?? 0}
        services={services}
        prefill={prefill}
        onCreate={(body) => run(() => api("/slots", { method: "POST", json: body }))}
      />
      {offers &&
        (offers.length === 0 ? (
          <EmptyState title={t("emptyTitle")} body={t("emptyBody")} example={t("emptyExample")} />
        ) : (
          <ul className={s.list}>
            {offers.map((o) => (
              <OfferCard key={o.id} offer={o} run={run} />
            ))}
          </ul>
        ))}
    </div>
  );
}

function FreedList({ freed, onPick }: { freed: Freed[]; onPick: (x: Freed) => void }) {
  const t = useTranslations("slots");
  const format = useFormatter();
  return (
    <Panel title={t("freedTitle")}>
      <p className={w.muted}>{t("freedLead")}</p>
      <ul className={w.rows}>
        {freed.map((x) => (
          <li key={x.starts_at} className={w.runRow}>
            <div className={w.runHead}>
              <span>
                <strong>
                  {format.dateTime(new Date(x.starts_at), { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}
                </strong>{" "}
                <span className={w.muted}>{[x.staff, x.service].filter(Boolean).join(" · ")}</span>
              </span>
              <button type="button" className={uiStyles.linkButton} onClick={() => onPick(x)}>
                {t("freedOffer")}
              </button>
            </div>
          </li>
        ))}
      </ul>
    </Panel>
  );
}

function NewOffer({ services, prefill, onCreate }: {
  services: Service[];
  prefill: { starts_at: string; staff_name: string } | null;
  onCreate: (body: object) => void;
}) {
  const t = useTranslations("slots");
  const [f, setF] = useState({
    starts_at: prefill?.starts_at ?? inHours(3),
    book_by: prefill ? local(new Date(new Date(prefill.starts_at).getTime() - 3600_000)) : inHours(2),
    service_id: "",
    staff_name: prefill?.staff_name ?? "",
    benefit: "stamps",
    benefit_value: 2,
    benefit_text: "",
    capacity: 1,
    group_size: 3,
    wait_minutes: 10,
  });
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setF({ ...f, [k]: e.target.type === "number" ? Number(e.target.value) : e.target.value });

  return (
    <Panel title={t("new")}>
      <form
        className={w.stack}
        onSubmit={(e) => {
          e.preventDefault();
          onCreate({ ...f, service_id: f.service_id || null, staff_name: f.staff_name || null, benefit_text: f.benefit_text || null });
        }}
      >
        <div className={w.pair}>
          <Field label={t("startsAt")} type="datetime-local" value={f.starts_at} onChange={set("starts_at")} required />
          <Field label={t("bookBy")} type="datetime-local" value={f.book_by} onChange={set("book_by")} required />
        </div>
        <div className={w.pair}>
          <label className={uiStyles.field}>
            <span className={uiStyles.label}>{t("service")}</span>
            <select className={uiStyles.input} value={f.service_id} onChange={set("service_id")}>
              <option value="">{t("anyService")}</option>
              {services.map((sv) => (
                <option key={sv.id} value={sv.id}>
                  {sv.name}
                </option>
              ))}
            </select>
          </label>
          <Field label={t("staffName")} value={f.staff_name} onChange={set("staff_name")} maxLength={80} />
        </div>
        <div className={w.pair}>
          <label className={uiStyles.field}>
            <span className={uiStyles.label}>{t("benefit")}</span>
            <select className={uiStyles.input} value={f.benefit} onChange={set("benefit")}>
              <option value="stamps">{t("bStamps")}</option>
              <option value="upgrade">{t("bUpgrade")}</option>
              <option value="discount">{t("bDiscount")}</option>
            </select>
          </label>
          {f.benefit === "upgrade" ? (
            <Field label={t("upgradeText")} value={f.benefit_text} onChange={set("benefit_text")} maxLength={120} required />
          ) : (
            <Field
              label={f.benefit === "stamps" ? t("stampsCount") : t("percent")}
              type="number"
              min={1}
              max={f.benefit === "stamps" ? 10 : 50}
              value={f.benefit_value}
              onChange={set("benefit_value")}
            />
          )}
        </div>
        <div className={w.triple}>
          <Field label={t("capacity")} type="number" min={1} max={20} value={f.capacity} onChange={set("capacity")} />
          <Field label={t("groupSize")} type="number" min={1} max={50} value={f.group_size} onChange={set("group_size")} />
          <Field label={t("wait")} type="number" min={1} max={240} value={f.wait_minutes} onChange={set("wait_minutes")} />
        </div>
        <div className={w.actions}>
          <Button type="submit">{t("create")}</Button>
        </div>
      </form>
    </Panel>
  );
}

function OfferCard({ offer: o, run }: { offer: Offer; run: (fn: () => Promise<unknown>) => void }) {
  const t = useTranslations("slots");
  const format = useFormatter();
  const benefitText = useBenefitText();
  const open = o.status === "open";
  const queued = o.recipients.filter((r) => r.status === "queued").length;
  return (
    <li className={s.card}>
      <span className={s.kind}>{t(`st_${o.status}` as "st_open")}</span>
      <span className={s.name}>
        {format.dateTime(new Date(o.starts_at), { weekday: "short", day: "numeric", month: "short" })} {clock(o.starts_at)}
        {o.service ? ` · ${o.service}` : ""}
      </span>
      <p className={s.reason}>
        {benefitText(o)} · {t("bookBy")} {clock(o.book_by)}
      </p>
      <p className={s.detail}>{t("claims", { count: o.claims, total: o.capacity })}</p>
      {o.sending_started && o.next_send_at && open && <p className={s.detail}>{t("sending", { time: format.dateTime(new Date(o.next_send_at), { hour: "2-digit", minute: "2-digit" }) })}</p>}
      <p className={w.muted}>{t("recipients")}</p>
      {o.recipients.length === 0 ? (
        <p className={s.detail}>{t("noRecipients")}</p>
      ) : (
        <ol className={w.list}>
          {o.recipients.map((r) => (
            <li key={r.customer_id} className={w.item}>
              <span>
                <span className={w.what}>{r.first_name ?? "·"}</span> <span className={w.when}>{t(`r_${r.reason}` as "r_waitlist")}</span>
              </span>
              <span className={w.when}>{t(`s_${r.status}` as "s_queued")}</span>
              {open && r.status === "queued" && !o.sending_started ? (
                <button type="button" className={w.textButton} onClick={() => run(() => api(`/slots/${o.id}/skip`, { method: "POST", json: { customer_id: r.customer_id } }))}>
                  {t("remove")}
                </button>
              ) : (
                <span />
              )}
            </li>
          ))}
        </ol>
      )}
      {open && (
        <div className={s.actions}>
          {!o.sending_started && queued > 0 && (
            <Button type="button" onClick={() => run(() => api(`/slots/${o.id}/send`, { method: "POST" }))}>
              {t("send")}
            </Button>
          )}
          <Button type="button" variant="secondary" onClick={() => run(() => api(`/slots/${o.id}/close`, { method: "POST", json: { status: "filled" } }))}>
            {t("filled")}
          </Button>
          <button type="button" className={s.quiet} onClick={() => run(() => api(`/slots/${o.id}/close`, { method: "POST", json: { status: "closed" } }))}>
            {t("close")}
          </button>
        </div>
      )}
    </li>
  );
}
