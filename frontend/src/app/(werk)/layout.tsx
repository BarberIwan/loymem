"use client";

import { useTranslations } from "next-intl";
import { usePathname, useRouter } from "next/navigation";

import { Wordmark } from "@/components/ui";
import { api } from "@/lib/api";
import { useMe } from "@/lib/useMe";

import s from "./shell.module.css";

export default function WorkLayout({ children }: { children: React.ReactNode }) {
  const t = useTranslations("nav");
  const common = useTranslations("common");
  const me = useMe();
  const path = usePathname();
  const router = useRouter();
  const links = [
    { href: "/vandaag", label: t("today"), roles: ["owner", "manager"] },
    { href: "/scan", label: t("scan"), roles: ["owner", "manager", "staff"] },
    { href: "/plekken", label: t("slots"), roles: ["owner", "manager"] },
    { href: "/abonnementen", label: t("plans"), roles: ["owner"] },
    { href: "/overzicht", label: t("overview"), roles: ["owner", "manager"] },
    { href: "/instellingen", label: t("settings"), roles: ["owner", "manager"] },
  ].filter((l) => me && l.roles.includes(me.role));

  async function signOut() {
    await api("/auth/logout", { method: "POST" }).catch(() => undefined);
    router.replace("/inloggen");
  }

  if (path === "/scan") return <>{children}</>;
  return (
    <div className={s.shell}>
      <header className={s.bar}>
        <div className={s.left}>
          <Wordmark />
          {me && <span className={s.business}>{me.business.name}</span>}
        </div>
        <nav className={s.nav}>
          {links.map((l) => (
            <a key={l.href} href={l.href} className={s.navLink} aria-current={path === l.href ? "page" : undefined}>
              {l.label}
            </a>
          ))}
          <button type="button" className={s.signOut} onClick={signOut}>
            {common("signOut")}
          </button>
        </nav>
      </header>
      <main className={s.main}>{children}</main>
    </div>
  );
}
