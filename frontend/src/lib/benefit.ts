"use client";

import { useTranslations } from "next-intl";

export type Benefit = { benefit: string; benefit_value: number; benefit_text: string | null };

export function useBenefitText() {
  const t = useTranslations("slot");
  return (b: Benefit) =>
    b.benefit === "stamps"
      ? t("benefitStamps", { count: b.benefit_value })
      : b.benefit === "discount"
        ? t("benefitDiscount", { percent: b.benefit_value })
        : (b.benefit_text ?? "");
}
