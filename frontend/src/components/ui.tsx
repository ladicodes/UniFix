"use client";

import Link from "next/link";
import { forwardRef, useEffect, useId, useRef, useSyncExternalStore } from "react";
import { createPortal } from "react-dom";
import { AnimatePresence, motion } from "motion/react";
import { Loader2, Star, X } from "lucide-react";
import { cn, initials } from "@/lib/format";

/* ---------- Button ---------- */

type Variant = "primary" | "accent" | "outline" | "ghost" | "danger" | "chain";
type Size = "sm" | "md" | "lg";

const variants: Record<Variant, string> = {
  primary: "bg-stellar text-white hover:bg-stellar-ink disabled:opacity-50",
  accent: "bg-stellar text-white hover:bg-stellar-ink disabled:opacity-50",
  outline: "border border-line-2 bg-paper text-ink hover:border-ink-3 disabled:opacity-50",
  ghost: "text-ink hover:bg-plaster-2 disabled:opacity-50",
  danger: "border border-clay/40 bg-paper text-clay hover:bg-clay-soft disabled:opacity-50",
  chain: "bg-stellar text-white hover:bg-stellar-ink disabled:opacity-60",
};
const sizes: Record<Size, string> = {
  sm: "h-9 px-4 text-sm gap-2 rounded-lg",
  md: "h-11 px-5 text-base gap-2 rounded-lg",
  lg: "h-14 px-8 text-base gap-3 rounded-2xl",
};

interface BtnProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
  href?: string;
}

export const Button = forwardRef<HTMLButtonElement, BtnProps>(function Button(
  { variant = "primary", size = "md", loading, className, children, href, disabled, ...rest },
  ref,
) {
  const cls = cn(
    "inline-flex shrink-0 select-none items-center justify-center font-semibold transition-[background,filter,border-color,opacity] duration-150 disabled:cursor-not-allowed",
    variants[variant],
    sizes[size],
    className,
  );
  if (href) {
    return (
      <Link href={href} className={cls}>
        {children}
      </Link>
    );
  }
  return (
    <button ref={ref} className={cls} disabled={disabled || loading} {...rest}>
      {loading && <Loader2 className="size-4 animate-spin" aria-hidden />}
      {children}
    </button>
  );
});

/* ---------- Badge ---------- */

type Tone = "neutral" | "danfo" | "lagoon" | "clay" | "stellar" | "ink";
const tones: Record<Tone, string> = {
  neutral: "bg-plaster-2 text-ink-2",
  danfo: "bg-danfo-soft text-danfo-ink",
  lagoon: "bg-lagoon-soft text-lagoon-ink",
  clay: "bg-clay-soft text-clay-ink",
  stellar: "bg-stellar-soft text-stellar-ink",
  ink: "bg-stellar text-white",
};

export function Badge({ tone = "neutral", className, children }: { tone?: Tone; className?: string; children: React.ReactNode }) {
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-lg px-2 py-0.5 text-xs font-semibold", tones[tone], className)}>
      {children}
    </span>
  );
}

/* ---------- Avatar ---------- */


export function Avatar({ name, size = 44, className }: { name: string; size?: number; className?: string }) {
  return (
    <span
      aria-hidden
      className={cn("inline-grid shrink-0 place-items-center rounded-full bg-plaster-2 font-semibold text-ink-2", className)}
      style={{ width: size, height: size, fontSize: size * 0.34 }}
    >
      {initials(name)}
    </span>
  );
}

/* ---------- Stars ---------- */

export function Stars({ value, size = 14, className }: { value: number; size?: number; className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-0.5", className)} aria-label={`${value.toFixed(1)} out of 5`}>
      {[1, 2, 3, 4, 5].map((i) => {
        const fill = Math.max(0, Math.min(1, value - (i - 1)));
        return (
          <span key={i} className="relative inline-block" style={{ width: size, height: size }}>
            <Star className="absolute inset-0 text-line-2" style={{ width: size, height: size }} strokeWidth={0} fill="currentColor" />
            <span className="absolute inset-0 overflow-hidden" style={{ width: `${fill * 100}%` }}>
              <Star className="text-danfo-ink" style={{ width: size, height: size }} strokeWidth={1.5} fill="var(--color-danfo)" />
            </span>
          </span>
        );
      })}
    </span>
  );
}

export function StarInput({ value, onChange, label }: { value: number; onChange: (v: number) => void; label: string }) {
  return (
    <div role="radiogroup" aria-label={label} className="flex gap-1">
      {[1, 2, 3, 4, 5].map((i) => (
        <button
          key={i}
          type="button"
          role="radio"
          aria-checked={value === i}
          aria-label={`${i} star${i > 1 ? "s" : ""}`}
          onClick={() => onChange(i)}
          className="grid size-9 place-items-center rounded-lg transition-transform hover:scale-110"
        >
          <Star className={cn("size-6", i <= value ? "text-danfo-ink" : "text-line-2")} strokeWidth={1.5} fill={i <= value ? "var(--color-danfo)" : "transparent"} />
        </button>
      ))}
    </div>
  );
}

/* ---------- Form fields ---------- */

export function Field({
  label,
  hint,
  error,
  children,
  className,
}: {
  label: string;
  hint?: string;
  error?: string;
  children: (id: string) => React.ReactNode;
  className?: string;
}) {
  const id = useId();
  return (
    <div className={cn("flex flex-col gap-2", className)}>
      <label htmlFor={id} className="text-sm font-semibold text-ink">
        {label}
      </label>
      {children(id)}
      {error ? <p className="text-sm text-clay">{error}</p> : hint ? <p className="text-sm text-ink-3">{hint}</p> : null}
    </div>
  );
}

const inputCls =
  "w-full rounded-lg border border-line-2 bg-paper px-4 text-base text-ink placeholder:text-ink-3 transition-colors focus:border-stellar";

export const Input = forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(function Input(
  { className, ...p },
  ref,
) {
  return <input ref={ref} className={cn(inputCls, "h-11", className)} {...p} />;
});

export function Textarea({ className, ...p }: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={cn(inputCls, "min-h-24 py-3 leading-relaxed", className)} {...p} />;
}

export function Select({ className, children, ...p }: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select className={cn(inputCls, "h-11 appearance-none bg-[length:16px] bg-[right_12px_center] bg-no-repeat pr-9", className)} style={{ backgroundImage: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%236a6890' stroke-width='2'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E")` }} {...p}>
      {children}
    </select>
  );
}

/* ---------- Surfaces ---------- */

/** A list or block that sits on the page: horizontal rules only, no frame. */
export function Panel({ className, children, as: As = "section" }: { className?: string; children: React.ReactNode; as?: "section" | "div" | "article" | "aside" }) {
  return <As className={cn("border-y border-line", className)}>{children}</As>;
}

/** The one filled surface on a screen: the thing you act on. */
export function Surface({ className, children, as: As = "section" }: { className?: string; children: React.ReactNode; as?: "section" | "div" | "aside" }) {
  return <As className={cn("rounded-2xl bg-plaster", className)}>{children}</As>;
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded-lg bg-plaster-2", className)} />;
}

export function Empty({ title, body, action }: { title: string; body: string; action?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-start gap-3 border-t border-line py-8">
      <p className="text-lg font-semibold">{title}</p>
      <p className="max-w-md text-ink-3">{body}</p>
      {action}
    </div>
  );
}

export function ErrorNote({ error }: { error: unknown }) {
  if (!error) return null;
  return (
    <p role="alert" className="rounded-lg border border-clay/30 bg-clay-soft px-4 py-3 text-sm text-clay-ink">
      {error instanceof Error ? error.message : String(error)}
    </p>
  );
}

/* ---------- Dialog ---------- */

export function Dialog({
  open,
  onClose,
  title,
  children,
  wide,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    ref.current?.querySelector<HTMLElement>("input,textarea,select,button")?.focus();
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [open, onClose]);

  const mounted = useSyncExternalStore(
    () => () => {},
    () => true,
    () => false,
  );
  if (!mounted) return null;

  // Portal to <body> so a dialog opened from inside another (transformed) dialog still covers the screen.
  return createPortal(
    <AnimatePresence>
      {open && (
        <div className="fixed inset-0 z-50 flex items-end justify-center sm:items-center sm:p-6">
          <motion.div
            className="absolute inset-0 bg-ink/30"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
          />
          <motion.div
            ref={ref}
            role="dialog"
            aria-modal="true"
            aria-label={title}
            initial={{ y: 40, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            exit={{ y: 30, opacity: 0 }}
            transition={{ type: "spring", damping: 30, stiffness: 380 }}
            className={cn(
              "relative max-h-[92dvh] w-full overflow-y-auto rounded-t-2xl bg-paper p-5 shadow-ticket sm:rounded-2xl sm:p-8",
              wide ? "sm:max-w-2xl" : "sm:max-w-lg",
            )}
          >
            <div className="mb-5 flex items-start justify-between gap-4">
              <h2 className="text-xl font-semibold">{title}</h2>
              <button onClick={onClose} aria-label="Close" className="-mr-1 -mt-1 grid size-9 place-items-center rounded-lg text-ink-3 hover:bg-plaster">
                <X className="size-5" />
              </button>
            </div>
            {children}
          </motion.div>
        </div>
      )}
    </AnimatePresence>,
    document.body,
  );
}

/* ---------- Logo ---------- */

export function Logo({ className, light }: { className?: string; light?: boolean }) {
  return (
    <span className={cn("font-wide inline-flex items-center gap-2 text-2xl font-bold tracking-tight", light ? "text-white" : "text-ink", className)}>
      <svg width="26" height="26" viewBox="0 0 26 26" aria-hidden>
        <rect width="26" height="26" rx="7" className="fill-danfo" />
        <path d="M7 6.5v13M19 6.5v13M7 13h12" className="stroke-ink" strokeWidth="3" strokeLinecap="round" />
      </svg>
      handi
    </span>
  );
}
