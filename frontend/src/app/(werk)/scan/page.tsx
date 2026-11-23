"use client";

import { useTranslations } from "next-intl";
import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "@/lib/api";
import { type Benefit, useBenefitText } from "@/lib/benefit";
import { useErrorText } from "@/lib/useErrorText";
import { useMe } from "@/lib/useMe";

import s from "./scan.module.css";

type Found = {
  customer_id: string;
  first_name: string | null;
  stamps: number;
  program: { stamps_required: number; reward: string };
  rewards: { id: string; description: string }[];
  services: { id: string; name: string }[];
  claimed_offer: Benefit | null;
};

type StampResult = { stamped: boolean; stamps: number; rewards_earned?: number; applied_offer: Benefit | null };

type Detector = { detect: (v: HTMLVideoElement) => Promise<{ rawValue: string }[]> };
declare global {
  interface Window {
    BarcodeDetector?: new (o: { formats: string[] }) => Detector;
  }
}

/** Point the camera at the card, then one tap to stamp. Works one-handed in a dark shop. */
export default function ScanPage() {
  const t = useTranslations("scan");
  const nav = useTranslations("nav");
  const me = useMe();
  const [tab, setTab] = useState<"stamp" | "redeem">("stamp");
  const back = me && me.role !== "staff" ? "/vandaag" : null;

  return (
    <div className={s.screen}>
      <header className={s.top}>
        <span>{me?.business.name}</span>
        {back && <a href={back}>{nav("today")}</a>}
      </header>
      <div className={s.body}>{tab === "stamp" ? <StampFlow /> : <RedeemFlow />}</div>
      <div className={s.tabs} role="tablist">
        <button type="button" role="tab" className={s.tab} aria-selected={tab === "stamp"} onClick={() => setTab("stamp")}>
          {t("tabStamp")}
        </button>
        <button type="button" role="tab" className={s.tab} aria-selected={tab === "redeem"} onClick={() => setTab("redeem")}>
          {t("tabRedeem")}
        </button>
      </div>
    </div>
  );
}

function StampFlow() {
  const t = useTranslations("scan");
  const benefitText = useBenefitText();
  const errorText = useErrorText();
  const [found, setFound] = useState<Found | null>(null);
  const [service, setService] = useState<string | null>(null);
  const [result, setResult] = useState<StampResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const lookup = useCallback(
    async (token: string) => {
      setError(null);
      try {
        setFound(await api<Found>("/scan", { method: "POST", json: { scan_token: token.trim() } }));
      } catch (e) {
        setError(errorText(e));
      }
    },
    [errorText],
  );

  async function stamp() {
    if (!found) return;
    setBusy(true);
    try {
      setResult(
        await api<StampResult>("/stamps", {
          method: "POST",
          json: { customer_id: found.customer_id, service_id: service },
        }),
      );
    } catch (e) {
      setError(errorText(e));
    }
    setBusy(false);
  }

  function reset() {
    setFound(null);
    setResult(null);
    setService(null);
    setError(null);
  }

  if (!found) {
    return (
      <>
        <Camera onCode={lookup} />
        <ManualEntry label={t("manual")} button={t("lookup")} onSubmit={lookup} />
        {error && <p className={s.error}>{error}</p>}
      </>
    );
  }

  const name = found.first_name ?? t("customer");
  const total = found.program.stamps_required;
  return (
    <>
      <div className={s.person}>
        <span className={s.label}>{t("customer")}</span>
        <span className={s.name}>{name}</span>
        <span className={s.meta}>{`${found.stamps} / ${total}`}</span>
        {found.claimed_offer && !result && <span className={s.offer}>{t("offerClaimed", { benefit: benefitText(found.claimed_offer) })}</span>}
      </div>
      {result ? (
        <div className={s.result} role="status">
          <span className={s.resultTitle}>{result.stamped ? t("stamped") : t("already", { name })}</span>
          {result.applied_offer && <span className={s.offer}>{t("offerApplied", { benefit: benefitText(result.applied_offer) })}</span>}
          {result.stamped && (
            <span className={s.meta}>
              {result.rewards_earned
                ? t("rewardEarned", { name, reward: found.program.reward })
                : t("stampedBody", { name, count: result.stamps, total })}
            </span>
          )}
        </div>
      ) : (
        found.services.length > 0 && (
          <div className={s.chips} role="group" aria-label={t("service")}>
            {found.services.map((sv) => (
              <button
                key={sv.id}
                type="button"
                className={s.chip}
                aria-pressed={service === sv.id}
                onClick={() => setService(service === sv.id ? null : sv.id)}
              >
                {sv.name}
              </button>
            ))}
          </div>
        )
      )}
      {error && <p className={s.error}>{error}</p>}
      {result ? (
        <button type="button" className={s.primary} onClick={reset} autoFocus>
          {t("next")}
        </button>
      ) : (
        <>
          <button type="button" className={s.primary} onClick={stamp} disabled={busy}>
            {t("stamp")}
          </button>
          <button type="button" className={s.ghost} onClick={reset}>
            {t("next")}
          </button>
        </>
      )}
    </>
  );
}

function RedeemFlow() {
  const t = useTranslations("scan");
  const errorText = useErrorText();
  const [done, setDone] = useState<{ description: string; first_name: string | null } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [code, setCode] = useState("");

  async function redeem(value: string) {
    setError(null);
    try {
      setDone(await api("/redeem", { method: "POST", json: { code: value } }));
    } catch (e) {
      setError(errorText(e));
    }
  }

  if (done) {
    return (
      <>
        <div className={s.result} role="status">
          <span className={s.resultTitle}>{t("redeemed")}</span>
          <span className={s.meta}>{t("redeemedBody", { reward: done.description, name: done.first_name ?? t("customer") })}</span>
        </div>
        <button
          type="button"
          className={s.primary}
          onClick={() => {
            setDone(null);
            setCode("");
          }}
        >
          {t("next")}
        </button>
      </>
    );
  }

  return (
    <form
      className={s.person}
      onSubmit={(e) => {
        e.preventDefault();
        void redeem(code);
      }}
    >
      <span className={s.resultTitle} id="redeem-title">
        {t("redeemTitle")}
      </span>
      <span className={s.meta}>{t("redeemHint")}</span>
      <input
        id="code"
        aria-labelledby="redeem-title"
        className={s.codeInput}
        inputMode="numeric"
        autoComplete="one-time-code"
        pattern="[0-9]{6}"
        maxLength={6}
        value={code}
        onChange={(e) => {
          const v = e.target.value.replace(/\D/g, "").slice(0, 6);
          setCode(v);
          if (v.length === 6) void redeem(v);
        }}
        autoFocus
      />
      {error && <p className={s.error}>{error}</p>}
      <button type="submit" className={s.primary} disabled={code.length !== 6}>
        {t("redeem")}
      </button>
    </form>
  );
}

function ManualEntry({ label, button, onSubmit }: { label: string; button: string; onSubmit: (v: string) => void }) {
  const [value, setValue] = useState("");
  return (
    <form
      className={s.manual}
      onSubmit={(e) => {
        e.preventDefault();
        if (value.trim()) onSubmit(value);
      }}
    >
      <label className="visually-hidden" htmlFor="manual">
        {label}
      </label>
      <input id="manual" className={s.input} placeholder={label} value={value} onChange={(e) => setValue(e.target.value)} autoComplete="off" />
      <button type="submit" className={s.ghost}>
        {button}
      </button>
    </form>
  );
}

function Camera({ onCode }: { onCode: (v: string) => void }) {
  const t = useTranslations("scan");
  const video = useRef<HTMLVideoElement>(null);
  const [state, setState] = useState<"starting" | "on" | "off">("starting");

  useEffect(() => {
    let stream: MediaStream | null = null;
    let raf = 0;
    let stopped = false;
    const Detector = window.BarcodeDetector;
    if (!Detector || !navigator.mediaDevices?.getUserMedia) {
      void Promise.resolve().then(() => setState("off"));
      return;
    }
    const detector = new Detector({ formats: ["qr_code"] });
    navigator.mediaDevices
      .getUserMedia({ video: { facingMode: "environment" }, audio: false })
      .then(async (s) => {
        stream = s;
        if (!video.current || stopped) return;
        video.current.srcObject = s;
        await video.current.play();
        setState("on");
        const tick = async () => {
          if (stopped || !video.current) return;
          const codes = await detector.detect(video.current).catch(() => []);
          if (codes[0]?.rawValue) {
            stopped = true;
            navigator.vibrate?.(30);
            onCode(codes[0].rawValue);
            return;
          }
          raf = window.setTimeout(tick, 180);
        };
        void tick();
      })
      .catch(() => setState("off"));
    return () => {
      stopped = true;
      window.clearTimeout(raf);
      stream?.getTracks().forEach((tr) => tr.stop());
    };
  }, [onCode]);

  return (
    <>
      <div className={s.viewport} hidden={state === "off"}>
        <video ref={video} muted playsInline aria-hidden />
        <div className={s.frame} />
      </div>
      <p className={s.hint}>{state === "off" ? t("noCamera") : t("aim")}</p>
    </>
  );
}
