"use client";

import { useTranslations } from "next-intl";
import { useCallback } from "react";

import { ApiError } from "./api";

export function useErrorText() {
  const t = useTranslations("errors");
  return useCallback(
    (err: unknown): string => {
      const code = err instanceof ApiError ? err.code : "generic";
      return t.has(code) ? t(code) : t("generic");
    },
    [t],
  );
}
