"use client";

import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { Pass } from "@/components/Pass";
import { Qr } from "@/components/Qr";
import { WebhookPanel } from "@/components/WebhookPanel";
import { Button, Field, Notice, Panel, uiStyles } from "@/components/ui";
import { api, type Palette } from "@/lib/api";
import { cardText } from "@/lib/contrast";
import { useErrorText } from "@/lib/useErrorText";

import shell from "../shell.module.css";
import w from "../werk.module.css";

// Starting points that look good on a card; any other colour stays possible.
const SWATCHES = ["#1F4A38", "#20201E", "#6B2E26", "#2B3A55", "#8A6A3B", "#B8A99A", "#E8D9C4", "#4A3B52"];

type Settings = {
  name: string;
  slug: string;
  brand_colour: string;
  booking_url: string | null;
  palette: Palette;
  program_name: string;
  stamps_required: number;
  reward_description: string;
  inbox_daily_limit: number;
  inbox_ignore_days: number;
  signup_url: string;
  services: { id: string; name: string; return_period_days: number }[];
};

export default function SettingsPage() {
  const t = useTranslations("settings");
  const common = useTranslations("common");
  const errorText = useErrorText();
  const router = useRouter();
  const [data, setData] = useState<Settings | null>(null);
  const [draft, setDraft] = useState<Partial<Settings>>({});
  const [palette, setPalette] = useState<Palette | null>(null);
  const [status, setStatus] = useState<{ tone: "ok" | "danger"; text: string } | null>(null);

  const load = useCallback(() => {
    api<Settings>("/settings")
      .then((d) => {
        setData(d);
        setPalette(d.palette);
        setDraft({});
      })
      .catch((e) => setStatus({ tone: "danger", text: errorText(e) }));
  }, [errorText]);
  useEffect(load, [load]);

  if (!data) return status ? <Notice tone="danger">{status.text}</Notice> : null;
  const v = { ...data, ...draft };
  const set = (k: keyof Settings) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setDraft((d) => ({ ...d, [k]: e.target.type === "number" ? Number(e.target.value) : e.target.value }));

  async function save() {
    try {
      const body: Record<string, unknown> = { ...draft };
      if (body.booking_url === "") body.booking_url = null;
      const d = await api<Settings>("/settings", { method: "PATCH", json: body });
      setData(d);
      setPalette(d.palette);
      setDraft({});
      setStatus({ tone: "ok", text: common("saved") });
    } catch (e) {
      setStatus({ tone: "danger", text: errorText(e) });
    }
  }

  async function addService(form: FormData) {
    try {
      await api("/services", {
        method: "POST",
        json: { name: form.get("name"), return_period_days: Number(form.get("days")) },
      });
      load();
    } catch (e) {
      setStatus({ tone: "danger", text: errorText(e) });
    }
  }

  const preview: Palette = draft.brand_colour
    ? { background: draft.brand_colour, text: cardText(draft.brand_colour) }
    : (palette ?? data.palette);

  return (
    <>
      <h1 className={shell.title}>{t("title")}</h1>
      <div className={w.grid}>
        <div className={w.stack}>
          <Panel title={t("cardTitle")}>
            <div className={w.stack}>
              <Field label={t("name")} value={v.name} onChange={set("name")} />
              <div className={w.colour}>
                <label className={w.colourLabel} htmlFor="colour-hex">
                  {t("colour")}
                </label>
                <div className={w.swatches} role="radiogroup" aria-label={t("colour")}>
                  {SWATCHES.map((c) => (
                    <button
                      key={c}
                      type="button"
                      role="radio"
                      aria-checked={v.brand_colour.toUpperCase() === c}
                      aria-label={c}
                      className={w.swatchButton}
                      style={{ "--swatch": c } as React.CSSProperties}
                      onClick={() => setDraft((d) => ({ ...d, brand_colour: c }))}
                    />
                  ))}
                </div>
                <div className={w.colourRow}>
                  <input type="color" className={w.swatch} aria-label={t("custom")} value={v.brand_colour} onChange={set("brand_colour")} />
                  <input id="colour-hex" className={uiStyles.input} value={v.brand_colour} onChange={set("brand_colour")} pattern="#[0-9A-Fa-f]{6}" aria-describedby="colour-hint" />
                </div>
                <p id="colour-hint" className={w.muted}>
                  {t("colourHint")}
                </p>
              </div>
            </div>
          </Panel>
          <Panel title={t("programTitle")}>
            <div className={w.stack}>
              <Field label={t("programName")} value={v.program_name} onChange={set("program_name")} />
              <Field label={t("stampsRequired")} type="number" min={2} max={30} value={v.stamps_required} onChange={set("stamps_required")} />
              <Field label={t("reward")} value={v.reward_description} onChange={set("reward_description")} />
              <Field label={t("booking")} type="url" value={v.booking_url ?? ""} onChange={set("booking_url")} help={t("bookingHint")} placeholder="https://" />
              <div className={w.actions}>
                <Button type="button" onClick={save} disabled={Object.keys(draft).length === 0}>
                  {common("save")}
                </Button>
                {status && <Notice tone={status.tone}>{status.text}</Notice>}
              </div>
            </div>
          </Panel>
          <Panel title={t("inboxTitle")}>
            <div className={w.stack}>
              <p className={w.muted}>{t("inboxHint")}</p>
              <Field label={t("dailyLimit")} type="number" min={1} max={50} value={v.inbox_daily_limit} onChange={set("inbox_daily_limit")} />
              <Field label={t("ignoreDays")} type="number" min={1} max={365} value={v.inbox_ignore_days} onChange={set("inbox_ignore_days")} />
              <div className={w.actions}>
                <Button type="button" onClick={save} disabled={Object.keys(draft).length === 0}>
                  {common("save")}
                </Button>
              </div>
            </div>
          </Panel>
          <Panel title={t("servicesTitle")}>
            <div className={w.stack}>
              <p className={w.muted}>{t("servicesHint")}</p>
              {data.services.length === 0 ? (
                <p className={w.muted}>{t("servicesEmpty")}</p>
              ) : (
                <ul className={w.list}>
                  {data.services.map((sv) => (
                    <li key={sv.id} className={w.item}>
                      <span className={w.what}>{sv.name}</span>
                      <span className={w.when}>{t("daysValue", { count: sv.return_period_days })}</span>
                    </li>
                  ))}
                </ul>
              )}
              <form className={w.serviceRow} action={addService}>
                <Field name="name" label={t("serviceName")} required minLength={2} />
                <Field name="days" label={t("days")} type="number" min={1} max={730} required />
                <Button type="submit" variant="secondary">
                  {t("addService")}
                </Button>
              </form>
            </div>
          </Panel>
          <WebhookPanel />
          <Panel title={t("signupTitle")}>
            <div className={`${w.stack} ${w.centre}`} id="aanmelden">
              <p className={w.muted}>{t("signupHint")}</p>
              <div className={w.qrBox}>
                <Qr value={data.signup_url} label={data.signup_url} />
              </div>
              <p className={w.muted}>{data.signup_url}</p>
              <div className={w.noPrint}>
                <Button type="button" variant="secondary" onClick={() => window.print()}>
                  {t("print")}
                </Button>
              </div>
            </div>
          </Panel>
          <div className={w.noPrint}>
            <Button
              type="button"
              variant="secondary"
              onClick={async () => {
                await api("/auth/logout", { method: "POST" }).catch(() => undefined);
                router.replace("/inloggen");
              }}
            >
              {common("signOut")}
            </Button>
          </div>
        </div>
        <aside className={w.sticky} aria-label={t("preview")}>
          <span className={w.muted}>{t("preview")}</span>
          <Pass business={v.name} programName={v.program_name} palette={preview} stamps={Math.min(3, v.stamps_required)} total={v.stamps_required} />
        </aside>
      </div>
    </>
  );
}
