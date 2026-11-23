"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { api, ApiError, type Palette } from "./api";

export type Me = { name: string; role: "owner" | "manager" | "staff"; business: { name: string; slug: string; palette: Palette } };

export function useMe(): Me | null {
  const [me, setMe] = useState<Me | null>(null);
  const router = useRouter();
  useEffect(() => {
    api<Me>("/me")
      .then(setMe)
      .catch((e) => {
        if (e instanceof ApiError && e.status === 401) router.replace("/inloggen");
      });
  }, [router]);
  return me;
}
