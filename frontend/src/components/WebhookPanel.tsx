"use client";

import { useFormatter, useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";

import { api } from "@/lib/api";
import { useErrorText } from "@/lib/useErrorText";

import { Button, Field, Notice, Panel } from "./ui";
import s from "./ui.module.css";

type Mapping = Record<string, string | string[] | null>;
type Hook = {
  set_up: boolean;
  active: boolean;
  url: string;
  mapping: Mapping;
  deliveries: { appointment_id: string | null; outcome: string; at: string }[];
};
const FIELDS = ["appointment_id", "status", "customer_phone", "customer_email", "service", "ended_at"] as const;

/** Settings for the generic webhook. Owner only; the server refuses anyone else. */
export function WebhookPanel() {
  const t = useTranslations("webhook");
  const common = useTranslations("common");
  const format = useFormatter();
  const errorText = useErrorText();
  const [hook, setHook] = useState<Hook | null>(null);
  const [secret, setSecret] = useState<string | null>(null);
  const [draft, setDraft] = useState<Mapping>({});
  const [status, setStatus] = useState<{ tone: "ok" | "danger"; text: string } | null>(null);

  const load = useCallback(() => {
    api<Hook>("/webhook").then(setHook, () => setHook(null));
  }, []);
  useEffect(load, [load]);

  if (!hook) return null;
  const mapping = { ...hook.mapping, ...draft };

  async function rotate() {
    try {
      const r = await api<{ secret: string }>("/webhook/secret", { method: "POST" });
      setSecret(r.secret);
      load();
    } catch (e) {
      setStatus({ tone: "danger", text: errorText(e) });
    }
  }

  async function save() {
    try {
      const statuses = String(mapping.completed_statuses ?? "")
        .split(",")
        .map((x) => x.trim())
        .filter(Boolean);
      const clean = Object.fromEntries(FIELDS.map((f) => [f, (mapping[f] as string) || null]));
      setHook(await api<Hook>("/webhook", { method: "PATCH", json: { mapping: { ...clean, completed_statuses: statuses } } }));
      setDraft({});
      setStatus({ tone: "ok", text: common("saved") });
    } catch (e) {
      setStatus({ tone: "danger", text: errorText(e) });
    }
  }

  return (
    <Panel title={t("title")}>
      <div className={s.empty}>
        <p className={s.emptyBody}>{t("lead")}</p>
        {!hook.set_up ? (
          <Button type="button" onClick={rotate}>
            {t("setUp")}
          </Button>
        ) : (
          <>
            <Field label={t("url")} value={hook.url} readOnly onFocus={(e) => e.target.select()} />
            {secret && (
              <>
                <Field label={t("secret")} value={secret} readOnly onFocus={(e) => e.target.select()} help={t("secretOnce")} />
              </>
            )}
            <p className={s.label}>{t("mapping")}</p>
            <p className={s.help}>{t("mappingHint")}</p>
            {FIELDS.map((f) => (
              <Field
                key={f}
                label={t(`f_${f}`)}
                value={(mapping[f] as string) ?? ""}
                onChange={(e) => setDraft((d) => ({ ...d, [f]: e.target.value }))}
              />
            ))}
            <Field
              label={t("completed")}
              help={t("completedHint")}
              value={Array.isArray(mapping.completed_statuses) ? mapping.completed_statuses.join(", ") : String(mapping.completed_statuses ?? "")}
              onChange={(e) => setDraft((d) => ({ ...d, completed_statuses: e.target.value }))}
            />
            <div className={s.empty}>
              <Button type="button" onClick={save} disabled={Object.keys(draft).length === 0}>
                {common("save")}
              </Button>
              {status && <Notice tone={status.tone}>{status.text}</Notice>}
            </div>
            <p className={s.label}>{t("deliveries")}</p>
            {hook.deliveries.length === 0 ? (
              <p className={s.help}>{t("noDeliveries")}</p>
            ) : (
              hook.deliveries.map((d, i) => (
                <p key={i} className={s.help}>
                  {format.dateTime(new Date(d.at), { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })} · {d.appointment_id ?? ""} ·{" "}
                  {t(`o_${d.outcome}` as "o_stamped")}
                </p>
              ))
            )}
            <Button type="button" variant="secondary" onClick={rotate}>
              {t("rotate")}
            </Button>
          </>
        )}
      </div>
    </Panel>
  );
}
