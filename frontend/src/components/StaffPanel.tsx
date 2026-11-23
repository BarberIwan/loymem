"use client";

import { useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";

import { api } from "@/lib/api";
import { useErrorText } from "@/lib/useErrorText";

import { Button, Field, Notice, Panel } from "./ui";
import s from "./ui.module.css";

type Member = { id: string; name: string; email: string; role: "owner" | "manager" | "staff"; active: boolean };
const ROLE = { owner: "rOwner", manager: "rManager", staff: "rStaff" } as const;

/** Owner only; the server refuses anyone else, and the panel then stays hidden. */
export function StaffPanel() {
  const t = useTranslations("staffPanel");
  const errorText = useErrorText();
  const [list, setList] = useState<Member[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [f, setF] = useState({ name: "", email: "", role: "staff", password: "" });

  const load = useCallback(() => {
    api<Member[]>("/staff").then(setList, () => setList(null));
  }, []);
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

  if (!list) return null;
  return (
    <Panel title={t("title")}>
      <div className={s.empty}>
        <p className={s.emptyBody}>{t("lead")}</p>
        {list.map((m) => (
          <div key={m.id} className={s.row}>
            <span>
              <strong>{m.name}</strong> <span className={s.help}>{t(ROLE[m.role])}{m.active ? "" : ` · ${t("inactive")}`}</span>
            </span>
            {m.role !== "owner" && (
              <Button type="button" variant="secondary" onClick={() => run(() => api(`/staff/${m.id}`, { method: "PATCH", json: { active: !m.active } }))}>
                {m.active ? t("deactivate") : t("activate")}
              </Button>
            )}
          </div>
        ))}
        <form
          className={s.empty}
          onSubmit={(e) => {
            e.preventDefault();
            run(async () => {
              await api("/staff", { method: "POST", json: f });
              setF({ name: "", email: "", role: "staff", password: "" });
            });
          }}
        >
          <Field label={t("name")} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} required minLength={2} />
          <Field label={t("email")} type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} required />
          <label className={s.field}>
            <span className={s.label}>{t("role")}</span>
            <select className={s.input} value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })}>
              <option value="staff">{t("roleStaff")}</option>
              <option value="manager">{t("roleManager")}</option>
            </select>
          </label>
          <Field label={t("password")} help={t("passwordHint")} type="password" autoComplete="new-password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} required minLength={10} />
          {error && <Notice tone="danger">{error}</Notice>}
          <Button type="submit" variant="secondary">
            {t("add")}
          </Button>
        </form>
      </div>
    </Panel>
  );
}
