import { cookies, headers } from "next/headers";
import { getRequestConfig } from "next-intl/server";

const LOCALES = ["nl", "en"] as const;
type Locale = (typeof LOCALES)[number];

function pick(value: string | undefined | null): Locale | null {
  const v = (value ?? "").slice(0, 2).toLowerCase();
  return (LOCALES as readonly string[]).includes(v) ? (v as Locale) : null;
}

export default getRequestConfig(async () => {
  const store = await cookies();
  const accept = (await headers()).get("accept-language");
  const locale = pick(store.get("locale")?.value) ?? pick(accept) ?? "nl";
  return {
    locale,
    messages: (await import(`../../messages/${locale}.json`)).default,
    timeZone: "Europe/Amsterdam",
  };
});
