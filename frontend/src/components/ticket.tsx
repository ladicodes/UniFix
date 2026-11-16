"use client";

import { AnimatePresence, motion } from "motion/react";
import { Lock, ShieldAlert } from "lucide-react";
import { cn, money, shortHash, usdc } from "@/lib/format";
import type { Currency } from "@/lib/types";

export type TicketStage = "agreed" | "held" | "submitted" | "released" | "disputed" | "refunded";

const STEPS: { key: TicketStage; label: string }[] = [
  { key: "agreed", label: "Agreed" },
  { key: "held", label: "Held" },
  { key: "submitted", label: "Done" },
  { key: "released", label: "Paid" },
];

const stepIndex = (s: TicketStage) => (s === "disputed" ? 2 : s === "refunded" ? 1 : STEPS.findIndex((x) => x.key === s));

export interface TicketProps {
  title: string;
  professional: string;
  customer: string;
  labour: number;
  materials: number;
  currency: Currency;
  usdcAmount: number;
  stage: TicketStage;
  version?: number;
  agreementHash?: string;
  txHash?: string;
  className?: string;
  compact?: boolean;
  /** Background colour class behind the ticket, used for the perforation notches. */
  notch?: string;
}

/**
 * The Handi agreement ticket. One object that follows the job from accepted
 * quotation to released payment. The hazard band appears only while money is held.
 */
export function AgreementTicket(p: TicketProps) {
  const idx = stepIndex(p.stage);
  const held = p.stage === "held" || p.stage === "submitted";
  return (
    <div className={cn("relative overflow-hidden rounded-2xl bg-paper shadow-ticket", p.className)}>
      <div className={cn("px-6 pt-6", p.compact ? "pb-4" : "pb-5")}>
        <div className="flex items-center justify-between text-sm text-ink-3">
          <span className="font-semibold text-ink-2">Service agreement</span>
          {p.version && <span>Version {p.version}, locked</span>}
        </div>
        <h3 className={cn("mt-3 font-semibold leading-snug text-ink", p.compact ? "text-lg" : "text-xl")}>{p.title}</h3>
        <p className="mt-2 text-sm text-ink-3">
          {p.professional} for {p.customer}
        </p>

        {!p.compact && (
          <dl className="mt-5 grid grid-cols-2 gap-y-2 text-sm">
            <dt className="text-ink-3">Labour</dt>
            <dd className="tnum text-right font-normal">{money(p.labour, p.currency)}</dd>
            <dt className="text-ink-3">Materials</dt>
            <dd className="tnum text-right font-normal">{money(p.materials, p.currency)}</dd>
          </dl>
        )}
      </div>

      <div className="relative h-4">
        <span className={cn("absolute -left-2.5 top-0 size-5 rounded-full", p.notch ?? "bg-paper")} />
        <span className="perf absolute inset-x-5 top-1/2 h-1 -translate-y-1/2" />
        <span className={cn("absolute -right-2.5 top-0 size-5 rounded-full", p.notch ?? "bg-paper")} />
      </div>

      <div className="px-6 pb-5 pt-3">
        <div className="flex items-end justify-between gap-4">
          <div>
            <p className="text-sm text-ink-3">Total</p>
            <p className="font-wide tnum text-3xl font-bold leading-none tracking-tight">{money(p.labour + p.materials, p.currency)}</p>
          </div>
          <p className="tnum pb-0.5 text-right text-sm font-semibold text-stellar">{usdc(p.usdcAmount)}</p>
        </div>

        <ol className="mt-5 grid grid-cols-4 gap-2" aria-label="Progress">
          {STEPS.map((s, i) => (
            <li key={s.key} className="flex flex-col gap-2">
              <span
                className={cn(
                  "h-1.5 rounded-full transition-colors duration-500",
                  p.stage === "disputed" && i === 2 ? "bg-clay" : i <= idx ? (p.stage === "released" ? "bg-lagoon" : "bg-stellar") : "bg-plaster-2",
                )}
              />
              <span className={cn("text-xs", i <= idx ? "font-semibold text-ink" : "text-ink-3")}>{s.label}</span>
            </li>
          ))}
        </ol>
      </div>

      <AnimatePresence initial={false} mode="popLayout">
        {held && (
          <motion.div
            key="held"
            initial={{ height: 0 }}
            animate={{ height: "auto" }}
            exit={{ height: 0 }}
            transition={{ duration: 0.45, ease: [0.2, 0.8, 0.2, 1] }}
            className="overflow-hidden"
          >
            <div className="hazard animate-stripe h-2.5" />
            <div className="flex items-center gap-3 bg-danfo px-6 py-3 text-sm text-ink">
              <Lock className="size-4" aria-hidden />
              <span className="font-semibold">Held in Stellar escrow</span>
              {p.txHash && <span className="tnum ml-auto text-ink-2">{shortHash(p.txHash)}</span>}
            </div>
          </motion.div>
        )}
        {p.stage === "disputed" && (
          <motion.div key="disputed" initial={{ height: 0 }} animate={{ height: "auto" }} exit={{ height: 0 }} className="overflow-hidden">
            <div className="flex items-center gap-3 bg-clay px-6 py-3 text-sm text-white">
              <ShieldAlert className="size-4" aria-hidden />
              <span className="font-semibold">Locked while Handi reviews the dispute</span>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {(p.stage === "released" || p.stage === "refunded") && (
          <motion.div
            key="stamp"
            initial={{ scale: 1.6, opacity: 0, rotate: -18 }}
            animate={{ scale: 1, opacity: 1, rotate: -9 }}
            exit={{ opacity: 0 }}
            transition={{ type: "spring", damping: 14, stiffness: 260 }}
            className={cn(
              "font-wide pointer-events-none absolute right-5 top-14 rounded-lg border-[3px] px-3 py-1 text-lg font-bold",
              p.stage === "released" ? "border-lagoon text-lagoon" : "border-ink-3 text-ink-3",
            )}
          >
            {p.stage === "released" ? "Paid" : "Refunded"}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
