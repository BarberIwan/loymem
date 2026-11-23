"use client";

import { useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";

import { Pass, passStyles } from "@/components/Pass";
import { LinkButton, Notice } from "@/components/ui";
import { api, type CardData } from "@/lib/api";
import { useErrorText } from "@/lib/useErrorText";

import styles from "../../../public.module.css";

const seenKey = (slug: string) => `loymem.seen.${slug}`;

function readSeen(slug: string): number | null {
  try {
    const v = window.localStorage.getItem(seenKey(slug));
    return v === null ? null : Number(v);
  } catch {
    return null;
  }
}

function writeSeen(slug: string, n: number) {
  try {
    window.localStorage.setItem(seenKey(slug), String(n));
  } catch {
    /* private mode: no animation memory, nothing else lost */
  }
}

export function CardView({ slug, secret }: { slug: string; secret: string }) {
  const t = useTranslations("card");
  const errorText = useErrorText();
  const [data, setData] = useState<CardData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [fresh, setFresh] = useState(0);
  const path = `/public/${slug}/card/${secret}`;

  const load = useCallback(
    () =>
      api<CardData>(path).then(
        (d) => {
          const seen = readSeen(slug);
          setFresh(seen !== null && d.stamps > seen ? d.stamps - seen : 0);
          writeSeen(slug, d.stamps);
          setData(d);
          setError(null);
        },
        (e) => setError(errorText(e)),
      ),
    [path, slug, errorText],
  );

  useEffect(() => {
    const first = window.setTimeout(load, 0);
    const onFocus = () => document.visibilityState === "visible" && void load();
    document.addEventListener("visibilitychange", onFocus);
    return () => {
      window.clearTimeout(first);
      document.removeEventListener("visibilitychange", onFocus);
    };
  }, [load]);

  if (error && !data) {
    return (
      <main className={styles.page}>
        <div className={styles.column}>
          <Notice tone="danger">{error}</Notice>
          <a className={styles.link} href={`/k/${slug}/kwijt`}>
            {t("lostLink")}
          </a>
        </div>
      </main>
    );
  }
  if (!data) return <main className={styles.page} aria-busy />;

  const total = data.program.stamps_required;
  const toGo = total - data.stamps;
  const reward = data.rewards[0];

  return (
    <main className={styles.page}>
      <div className={styles.column}>
        <Pass
          business={data.business.name}
          programName={data.program.name}
          palette={data.business.palette}
          stamps={data.stamps}
          total={total}
          fresh={fresh}
          scanToken={data.scan_token}
          scanHint={t("scanHint")}
        >
          {reward ? <RewardStrip path={path} reward={reward} onDone={load} /> : null}
        </Pass>
        {!reward && <p className={styles.muted}>{t("toGo", { count: toGo, reward: data.program.reward })}</p>}
        {data.business.booking_url && (
          <LinkButton href={data.business.booking_url} rel="noopener noreferrer" target="_blank" size="large" variant="secondary">
            {t("book")}
          </LinkButton>
        )}
        <Messages path={path} business={data.business.name} on={data.marketing} onChange={load} />
        <p className={styles.muted}>{t("saveTip")}</p>
        <a className={styles.link} href={`/k/${slug}/kwijt`}>
          {t("lost")} {t("lostLink")}
        </a>
      </div>
    </main>
  );
}

function RewardStrip({ path, reward, onDone }: { path: string; reward: { id: string; description: string }; onDone: () => void }) {
  const t = useTranslations("card");
  const errorText = useErrorText();
  const [code, setCode] = useState<string | null>(null);
  const [left, setLeft] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!code) return;
    const timer = window.setInterval(() => setLeft((s) => s - 1), 1000);
    const poll = window.setInterval(onDone, 5000);
    return () => {
      window.clearInterval(timer);
      window.clearInterval(poll);
    };
  }, [code, onDone]);

  async function show() {
    try {
      const r = await api<{ code: string; valid_seconds: number }>(`${path}/reward-code`, {
        method: "POST",
        json: { reward_id: reward.id },
      });
      setCode(r.code);
      setLeft(r.valid_seconds);
      setError(null);
    } catch (e) {
      setError(errorText(e));
    }
  }

  const expired = code !== null && left <= 0;
  return (
    <div className={passStyles.reward}>
      <span className={passStyles.label}>{t("rewardReady")}</span>
      <span className={passStyles.rewardName}>{reward.description}</span>
      {code && !expired ? (
        <>
          <span className={passStyles.code} aria-live="polite">
            {code.slice(0, 3)} {code.slice(3)}
          </span>
          <span className={passStyles.hint}>
            {t("codeHint")} {t("codeSeconds", { seconds: left })}
          </span>
        </>
      ) : (
        <button type="button" className={passStyles.passButton} onClick={show}>
          {expired ? t("newCode") : t("showCode")}
        </button>
      )}
      {error && <span className={passStyles.hint}>{error}</span>}
    </div>
  );
}

function Messages({ path, business, on, onChange }: { path: string; business: string; on: boolean; onChange: () => void }) {
  const t = useTranslations("card");
  async function flip() {
    await api(`${path}/consent`, { method: "PUT", json: { marketing: !on } }).catch(() => undefined);
    onChange();
  }
  return (
    <div className={styles.row}>
      <span>{t("messages", { business })}</span>
      <button type="button" className={styles.toggle} aria-pressed={on} onClick={flip}>
        {on ? t("messagesOn") : t("messagesOff")}
      </button>
    </div>
  );
}
