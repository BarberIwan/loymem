"use client";

import { useTranslations } from "next-intl";
import type { CSSProperties, ReactNode } from "react";

import type { Palette } from "@/lib/api";

import styles from "./Pass.module.css";
import { Qr } from "./Qr";

type Props = {
  business: string;
  programName: string;
  palette: Palette;
  stamps: number;
  total: number;
  fresh?: number;
  scanToken?: string;
  scanHint?: string;
  /** Prepaid euro balance, already formatted; shown only when there is one. */
  balance?: string;
  children?: ReactNode;
};

/** The customer card. Brand colour in front, text colour chosen for contrast by the server. */
export function Pass({ business, programName, palette, stamps, total, fresh = 0, scanToken,
  scanHint, balance, children }: Props) {
  const t = useTranslations("card");
  const cols = total <= 6 ? total : total <= 12 ? Math.ceil(total / 2) : 6;
  const vars = { "--pass-bg": palette.background, "--pass-fg": palette.text, "--cols": cols } as CSSProperties;
  return (
    <article className={styles.pass} style={vars} aria-label={business}>
      <header className={styles.head}>
        <span className={styles.business}>{business}</span>
        <span className={styles.label}>{programName}</span>
      </header>
      <div className={styles.count} aria-label={t("progress", { count: stamps, total })}>
        <span className={styles.number}>{stamps}</span>
        <span className={styles.of}>/ {total}</span>
      </div>
      <ol className={styles.stamps} aria-hidden>
        {Array.from({ length: total }, (_, i) => (
          <li
            key={i}
            className={[styles.stamp, i < stamps && styles.filled, i < stamps && i >= stamps - fresh && styles.fresh]
              .filter(Boolean)
              .join(" ")}
          />
        ))}
      </ol>
      {balance && (
        <div className={styles.balance}>
          <span className={styles.label}>{t("balance")}</span>
          <span className={styles.balanceAmount}>{balance}</span>
        </div>
      )}
      {children}
      {scanToken && (
        <footer className={styles.foot}>
          <div className={styles.qr}>
            <Qr value={scanToken} label={scanHint ?? ""} />
          </div>
          <span className={styles.manual} aria-label={scanToken.split("").join(" ")}>
            {scanToken.slice(0, 5)} {scanToken.slice(5)}
          </span>
          {scanHint && <p className={styles.hint}>{scanHint}</p>}
        </footer>
      )}
    </article>
  );
}

export const passStyles = styles;
