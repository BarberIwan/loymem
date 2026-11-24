import Link from "next/link";
import type React from "react";
import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode } from "react";
import { useId } from "react";

import s from "./ui.module.css";

const cx = (...c: (string | false | undefined)[]) => c.filter(Boolean).join(" ");

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "danger";
  size?: "normal" | "large";
  block?: boolean;
};

export function Button({ variant = "primary", size = "normal", block, className, ...rest }: ButtonProps) {
  return (
    <button
      className={cx(s.button, variant !== "primary" && s[variant], size === "large" && s.large, block && s.block, className)}
      {...rest}
    />
  );
}

type FieldProps = InputHTMLAttributes<HTMLInputElement> & {
  label: string;
  optional?: string;
  help?: string;
  error?: string | null;
};

export function Field({ label, optional, help, error, ...input }: FieldProps) {
  const id = useId();
  const hint = help || error ? `${id}-hint` : undefined;
  return (
    <div className={s.field}>
      <label className={s.label} htmlFor={id}>
        {label} {optional && <span className={s.labelMuted}>({optional})</span>}
      </label>
      <input
        id={id}
        className={s.input}
        inputMode={input.type === "number" ? "numeric" : undefined}
        aria-invalid={error ? true : undefined}
        aria-describedby={hint}
        {...input}
      />
      {error ? (
        <p id={hint} className={s.error} role="alert">
          {error}
        </p>
      ) : (
        help && (
          <p id={hint} className={s.help}>
            {help}
          </p>
        )
      )}
    </div>
  );
}

export function Notice({ tone = "ok", children }: { tone?: "ok" | "danger"; children: ReactNode }) {
  return (
    <p className={cx(s.notice, tone === "danger" && s.noticeDanger)} role={tone === "danger" ? "alert" : "status"}>
      {children}
    </p>
  );
}

export function Panel({ title, children }: { title?: string; children: ReactNode }) {
  return (
    <section className={s.panel}>
      {title && <h2 className={s.panelTitle}>{title}</h2>}
      {children}
    </section>
  );
}

export function Stat({ label, value, note }: { label: string; value: number | string; note?: string }) {
  return (
    <div className={s.stat}>
      <span className={s.statLabel}>{label}</span>
      <span className={s.statValue}>{value}</span>
      {note && <span className={s.statNote}>{note}</span>}
    </div>
  );
}

export function EmptyState({ title, body, example, action }: { title: string; body: string; example?: string; action?: ReactNode }) {
  return (
    <div className={s.empty}>
      <h2 className={s.emptyTitle}>{title}</h2>
      <p className={s.emptyBody}>{body}</p>
      {example && <p className={s.example}>{example}</p>}
      {action}
    </div>
  );
}

export function Wordmark() {
  return (
    <Link href="/" className={s.wordmark}>
      Loymem
    </Link>
  );
}

export { s as uiStyles, cx };

type LinkButtonProps = React.AnchorHTMLAttributes<HTMLAnchorElement> & {
  variant?: "primary" | "secondary";
  size?: "normal" | "large";
};

export function LinkButton({ variant = "primary", size = "normal", className, ...rest }: LinkButtonProps) {
  return <a className={cx(s.button, variant !== "primary" && s[variant], size === "large" && s.large, className)} {...rest} />;
}
