"use client";

import { useLocale, useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";

import { Pass, passStyles } from "@/components/Pass";
import { Button, LinkButton, Notice } from "@/components/ui";
import { api, type CardData } from "@/lib/api";
import { euros } from "@/lib/money";
import { useErrorText } from "@/lib/useErrorText";

import styles from "../../../public.module.css";
import { Memberships } from "./Memberships";
import { Waitlist } from "./Waitlist";

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

const clock = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;

export function CardView({ slug, secret }: { slug: string; secret: string }) {
  const t = useTranslations("card");
  const locale = useLocale();
  const errorText = useErrorText();
  const [data, setData] = useState<CardData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [fresh, setFresh] = useState(0);
  const [code, setCode] = useState<{ value: string; left: number } | null>(null);
  const path = `/public/${slug}/card/${secret}`;

  const load = useCallback(
    () =>
      api<CardData>(path).then(
        (d) => {
          // While a reward waits, the card stays full: that is the moment worth seeing.
          const shown = d.rewards.length ? d.program.stamps_required : d.stamps;
          const seen = readSeen(slug);
          setFresh(seen !== null && shown > seen ? shown - seen : 0);
          writeSeen(slug, shown);
          setData(d);
          setError(null);
          if (!d.rewards.length) setCode(null);
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

  const active = code !== null && code.left > 0;
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => setCode((c) => (c ? { ...c, left: c.left - 1 } : c)), 1000);
    const poll = window.setInterval(load, 5000);
    return () => {
      window.clearInterval(timer);
      window.clearInterval(poll);
    };
  }, [active, load]);

  async function showCode(rewardId: string) {
    try {
      const r = await api<{ code: string; valid_seconds: number }>(`${path}/reward-code`, {
        method: "POST",
        json: { reward_id: rewardId },
      });
      setCode({ value: r.code, left: r.valid_seconds });
    } catch (e) {
      setError(errorText(e));
    }
  }

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
  const reward = data.rewards[0];

  return (
    <main className={styles.page}>
      <div className={styles.column}>
        <Pass
          business={data.business.name}
          programName={data.program.name}
          palette={data.business.palette}
          stamps={reward ? total : data.stamps}
          total={total}
          fresh={fresh}
          scanToken={active ? undefined : data.scan_token}
          scanHint={t("scanHint")}
          balance={data.memberships.balance.cents > 0 ? euros(data.memberships.balance.cents, locale) : undefined}
        >
          {reward && (
            <div className={passStyles.reward}>
              <span className={passStyles.label}>{t("rewardReady")}</span>
              <span className={passStyles.rewardName}>{reward.description}</span>
              {active ? (
                <>
                  <span className={passStyles.code} aria-live="polite">
                    {code.value.slice(0, 3)} {code.value.slice(3)}
                  </span>
                  <span className={passStyles.hint}>
                    {t("codeHint")} {t("codeLeft", { time: clock(code.left) })}
                  </span>
                </>
              ) : (
                <button type="button" className={passStyles.passButton} onClick={() => showCode(reward.id)}>
                  {code ? t("newCode") : t("showCode")}
                </button>
              )}
            </div>
          )}
        </Pass>
        {!reward && <p className={styles.muted}>{t("toGo", { count: total - data.stamps, reward: data.program.reward })}</p>}
        {error && <Notice tone="danger">{error}</Notice>}
        {data.business.booking_url && (
          <LinkButton href={data.business.booking_url} rel="noopener noreferrer" target="_blank" size="large" variant="secondary">
            {t("book")}
          </LinkButton>
        )}
        {(data.wallet.apple || data.wallet.google) && (
          <div className={styles.inline}>
            {data.wallet.apple && (
              <LinkButton variant="secondary" href={`/api/v1${path}/wallet/apple`}>
                {t("apple")}
              </LinkButton>
            )}
            {data.wallet.google && (
              <Button
                type="button"
                variant="secondary"
                onClick={async () => {
                  const r = await api<{ url: string }>(`${path}/wallet/google`).catch(() => null);
                  if (r) window.location.href = r.url;
                }}
              >
                {t("google")}
              </Button>
            )}
            <p className={styles.muted}>{t("walletNote")}</p>
          </div>
        )}
        <Memberships
          path={path}
          plans={data.memberships.plans}
          subscriptions={data.memberships.subscriptions}
          balance={data.memberships.balance}
          history={data.memberships.balance_history}
          onChange={load}
        />
        <Waitlist path={path} current={data.waitlist} hasEmail={data.has_email} services={data.services} onChange={load} />
        <Messages path={path} business={data.business.name} on={data.marketing} onChange={load} />
        <p className={styles.muted}>{t("saveTip")}</p>
        <a className={styles.link} href={`/k/${slug}/kwijt`}>
          {t("lostLink")}
        </a>
      </div>
    </main>
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
      <span id="messages-label">{t("messages", { business })}</span>
      <button type="button" role="switch" aria-checked={on} aria-labelledby="messages-label" className={styles.switch} onClick={flip}>
        <span className={styles.knob} />
      </button>
    </div>
  );
}
