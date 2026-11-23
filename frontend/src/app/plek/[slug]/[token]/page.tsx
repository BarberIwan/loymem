"use client";

import { useFormatter, useTranslations } from "next-intl";
import { useParams } from "next/navigation";
import type { CSSProperties } from "react";
import { useCallback, useEffect, useState } from "react";

import { Button, LinkButton, Notice } from "@/components/ui";
import { api, type Palette } from "@/lib/api";
import { useBenefitText } from "@/lib/benefit";
import { useErrorText } from "@/lib/useErrorText";

import styles from "../../../public.module.css";
import s from "./plek.module.css";

type Offer = {
  business: { name: string; palette: Palette };
  service: string | null;
  staff_name: string | null;
  starts_at: string;
  book_by: string;
  benefit: string;
  benefit_value: number;
  benefit_text: string | null;
  available: boolean;
  claimed: boolean;
  booking_url: string | null;
};

// Times are shown as the shop's own clock time, so the string is used as is.
const clock = (iso: string) => iso.slice(11, 16);

export default function SlotPage() {
  const t = useTranslations("slot");
  const format = useFormatter();
  const benefitText = useBenefitText();
  const errorText = useErrorText();
  const { slug, token } = useParams<{ slug: string; token: string }>();
  const [offer, setOffer] = useState<Offer | null>(null);
  const [error, setError] = useState<string | null>(null);
  const path = `/public/${slug}/plek/${token}`;

  const load = useCallback(() => {
    api<Offer>(path).then(setOffer, (e) => setError(errorText(e)));
  }, [path, errorText]);
  useEffect(load, [load]);

  async function claim() {
    try {
      await api(`${path}/claim`, { method: "POST" });
    } catch (e) {
      setError(errorText(e));
    }
    load();
  }

  if (!offer) {
    return <main className={styles.page}>{error && <div className={styles.column}><Notice tone="danger">{error}</Notice></div>}</main>;
  }
  const day = format.dateTime(new Date(offer.starts_at), { weekday: "long", day: "numeric", month: "long" });
  const vars = { "--pass-bg": offer.business.palette.background, "--pass-fg": offer.business.palette.text } as CSSProperties;

  return (
    <main className={styles.page}>
      <div className={styles.column}>
        <article className={s.ticket} style={vars}>
          <span className={s.business}>{offer.business.name}</span>
          <span className={s.label}>{t("title")}</span>
          <span className={s.time}>{clock(offer.starts_at)}</span>
          <span className={s.meta}>
            {day}
            {offer.service ? ` · ${offer.service}` : ""}
            {offer.staff_name ? ` · ${t("with", { name: offer.staff_name })}` : ""}
          </span>
          <span className={s.benefit}>{benefitText(offer)}</span>
          <span className={s.deadline}>{t("bookBy", { time: clock(offer.book_by) })}</span>
        </article>
        {offer.claimed ? (
          <>
            <Notice>{t("claimed")}</Notice>
            {offer.booking_url && (
              <LinkButton href={offer.booking_url} rel="noopener noreferrer" target="_blank" size="large">
                {t("book")}
              </LinkButton>
            )}
            <p className={styles.muted}>{t("benefitNote")}</p>
          </>
        ) : offer.available ? (
          <>
            <Button type="button" size="large" onClick={claim}>
              {t("claim")}
            </Button>
            <p className={styles.muted}>{t("benefitNote")}</p>
          </>
        ) : (
          <>
            <h1 className={styles.title}>{t("gone")}</h1>
            <p className={styles.muted}>{t("goneBody")}</p>
          </>
        )}
        {error && offer.available && <Notice tone="danger">{error}</Notice>}
      </div>
    </main>
  );
}
