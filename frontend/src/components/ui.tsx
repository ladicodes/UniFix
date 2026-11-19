"use client";

import Link from "next/link";
import { forwardRef, useEffect, useId, useRef, useState, useSyncExternalStore } from "react";
import { createPortal } from "react-dom";
import { AnimatePresence, motion } from "motion/react";
import { AlertCircle, ChevronDown, Loader2, Star, X } from "lucide-react";
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


/* Quiet tints with no meaning: they only keep people apart at a glance. */
const TINTS = ["var(--tint-1)", "var(--tint-2)", "var(--tint-3)", "var(--tint-4)", "var(--tint-5)"];

export function Avatar({ name, size = 44, className }: { name: string; size?: number; className?: string }) {
  let h = 0;
  for (const ch of name) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return (
    <span
      aria-hidden
      className={cn("inline-grid shrink-0 place-items-center rounded-full font-semibold text-ink", className)}
      style={{ width: size, height: size, fontSize: size * 0.34, background: TINTS[h % TINTS.length] }}
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
  optional,
  children,
  className,
}: {
  label: string;
  hint?: string;
  error?: string;
  optional?: boolean;
  children: (id: string, describedBy?: string) => React.ReactNode;
  className?: string;
}) {
  const id = useId();
  const noteId = `${id}-note`;
  const note = error ?? hint;
  return (
    <div className={cn("flex flex-col gap-2", className)}>
      <label htmlFor={id} className="flex items-baseline justify-between gap-3 text-sm font-semibold text-ink">
        {label}
        {optional && <span className="font-normal text-ink-3">Optional</span>}
      </label>
      {children(id, note ? noteId : undefined)}
      {error ? (
        <p id={noteId} className="flex items-center gap-1.5 text-sm text-clay-ink">
          <AlertCircle className="size-4 shrink-0" aria-hidden />
          {error}
        </p>
      ) : hint ? (
        <p id={noteId} className="text-sm text-ink-3">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

/** One look for every text control: quiet border, clear hover, a visible focus ring. */
const inputCls =
  "w-full rounded-xl border border-line bg-paper px-4 text-base text-ink shadow-xs outline-none transition placeholder:text-ink-3 hover:border-line-2 focus-visible:border-stellar focus-visible:ring-4 focus-visible:ring-stellar-soft aria-invalid:border-clay aria-invalid:ring-clay-soft disabled:cursor-not-allowed disabled:bg-plaster disabled:text-ink-3";

type InputProps = React.InputHTMLAttributes<HTMLInputElement> & {
  /** Icon shown inside the field, on the left. */
  icon?: React.ComponentType<{ className?: string; "aria-hidden"?: boolean }>;
  /** Element pinned inside the field, on the right (a unit, a show/hide button). */
  trailing?: React.ReactNode;
};

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input({ className, icon: Icon, trailing, ...p }, ref) {
  const input = <input ref={ref} className={cn(inputCls, "h-12", Icon ? "pl-11" : undefined, trailing ? "pr-16" : undefined, className)} {...p} />;
  if (!Icon && !trailing) return input;
  return (
    <div className="relative">
      {Icon && <Icon className="pointer-events-none absolute left-4 top-1/2 size-4 -translate-y-1/2 text-ink-3" aria-hidden />}
      {input}
      {trailing && <span className="absolute right-2 top-1/2 flex -translate-y-1/2 items-center">{trailing}</span>}
    </div>
  );
});

export function Textarea({ className, ...p }: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={cn(inputCls, "min-h-28 resize-y py-3 leading-relaxed", className)} {...p} />;
}

export function Select({ className, children, ...p }: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <div className="relative">
      <select className={cn(inputCls, "h-12 cursor-pointer appearance-none pr-11", className)} {...p}>
        {children}
      </select>
      <ChevronDown className="pointer-events-none absolute right-4 top-1/2 size-4 -translate-y-1/2 text-ink-3" aria-hidden />
    </div>
  );
}

/** Pick one of a few options shown side by side. Use instead of a select when there are 2 to 5 short choices. */
export function Segmented<T extends string>({
  value,
  onChange,
  options,
  label,
  className,
}: {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: string; hint?: string }[];
  label: string;
  className?: string;
}) {
  return (
    <div role="radiogroup" aria-label={label} className={cn("grid gap-2", className)} style={{ gridTemplateColumns: `repeat(${options.length}, minmax(0, 1fr))` }}>
      {options.map((o) => {
        const on = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={on}
            onClick={() => onChange(o.value)}
            className={cn(
              "flex min-h-12 flex-col items-center justify-center rounded-xl border px-3 py-2 text-center text-sm font-semibold transition",
              on ? "border-stellar bg-stellar-soft text-stellar-ink ring-1 ring-stellar" : "border-line bg-paper text-ink-2 hover:border-line-2 hover:text-ink",
            )}
          >
            {o.label}
            {o.hint && <span className={cn("text-xs font-normal", on ? "text-stellar-ink" : "text-ink-3")}>{o.hint}</span>}
          </button>
        );
      })}
    </div>
  );
}

/** Free-text tags: type and press Enter or comma to add, Backspace on an empty field removes the last one. */
export function ChipInput({
  id,
  value,
  onChange,
  placeholder,
  describedBy,
}: {
  id: string;
  value: string[];
  onChange: (v: string[]) => void;
  placeholder?: string;
  describedBy?: string;
}) {
  const [draft, setDraft] = useState("");
  const add = (raw: string) => {
    const parts = raw.split(",").map((x) => x.trim()).filter(Boolean);
    if (!parts.length) return;
    onChange([...value, ...parts.filter((x) => !value.some((v) => v.toLowerCase() === x.toLowerCase()))]);
    setDraft("");
  };
  return (
    <div className="flex min-h-12 w-full flex-wrap items-center gap-2 rounded-xl border border-line bg-paper px-2 py-2 shadow-xs transition hover:border-line-2 focus-within:border-stellar focus-within:ring-4 focus-within:ring-stellar-soft">
      {value.map((v) => (
        <span key={v} className="flex items-center gap-1 rounded-lg bg-plaster py-1 pl-2.5 pr-1 text-sm font-semibold text-ink">
          {v}
          <button
            type="button"
            onClick={() => onChange(value.filter((x) => x !== v))}
            className="grid size-5 place-items-center rounded-md text-ink-3 hover:bg-plaster-2 hover:text-ink"
            aria-label={`Remove ${v}`}
          >
            <X className="size-3.5" aria-hidden />
          </button>
        </span>
      ))}
      <input
        id={id}
        value={draft}
        aria-describedby={describedBy}
        onChange={(e) => (e.target.value.includes(",") ? add(e.target.value) : setDraft(e.target.value))}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            add(draft);
          } else if (e.key === "Backspace" && !draft && value.length) {
            onChange(value.slice(0, -1));
          }
        }}
        onBlur={() => add(draft)}
        placeholder={value.length ? "" : placeholder}
        className="min-w-32 flex-1 bg-transparent px-2 text-base text-ink outline-none placeholder:text-ink-3"
      />
    </div>
  );
}

/* ---------- Surfaces ---------- */

/** A list or block on the page: a white card, rows divide inside it. */
export function Panel({ className, children, as: As = "section" }: { className?: string; children: React.ReactNode; as?: "section" | "div" | "article" | "aside" }) {
  return <As className={cn("rounded-2xl border border-line bg-paper px-5 shadow-xs", className)}>{children}</As>;
}

/** A framed block on the page with an optional header row. Use to group one topic. */
export function Card({
  title,
  action,
  className,
  bodyClassName,
  children,
}: {
  title?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
  bodyClassName?: string;
  children: React.ReactNode;
}) {
  return (
    <section className={cn("overflow-hidden rounded-2xl border border-line bg-paper shadow-xs", className)}>
      {(title || action) && (
        <header className="flex items-center justify-between gap-4 border-b border-line px-5 py-4">
          {title && <h2 className="font-semibold">{title}</h2>}
          {action}
        </header>
      )}
      <div className={bodyClassName}>{children}</div>
    </section>
  );
}

/** The one filled surface on a screen: the thing you act on. */
export function Surface({ className, children, as: As = "section" }: { className?: string; children: React.ReactNode; as?: "section" | "div" | "aside" }) {
  return <As className={cn("rounded-2xl border border-line bg-paper shadow-xs", className)}>{children}</As>;
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded-lg bg-plaster-2", className)} />;
}

export function Empty({ title, body, action }: { title: string; body: string; action?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-start gap-3 rounded-2xl border border-dashed border-line-2/50 bg-paper p-8">
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
              "relative max-h-dvh w-full overflow-y-auto rounded-t-2xl bg-paper p-5 shadow-ticket sm:rounded-2xl sm:p-8",
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

/**
 * UniFix mark: the U is an open spanner jaw gripping a hex nut. One colour, so it
 * reads the same on paper, on ink and at 16px; the nut's bore is cut out.
 */
export function LogoMark({ size = 28, className, light }: { size?: number; className?: string; light?: boolean }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden className={cn(light ? "text-white" : "text-ink", className)}>
      <path d="M4 9 L11.5 6.5 V17 A4.5 4.5 0 0 0 20.5 17 V6.5 L28 9 V17 A12 12 0 0 1 4 17 Z" fill="currentColor" />
      <path fillRule="evenodd" d="M16 8.93 L19.7 11.07 V15.33 L16 17.47 L12.3 15.33 V11.07 Z M16 11.6 a1.6 1.6 0 1 0 0.001 0 Z" fill="currentColor" />
    </svg>
  );
}

export function Logo({ className, light }: { className?: string; light?: boolean }) {
  return (
    <span className={cn("font-wide inline-flex items-center gap-2 text-2xl font-bold", light ? "text-white" : "text-ink", className)}>
      <LogoMark className="size-7" light={light} />
      unifix
    </span>
  );
}
