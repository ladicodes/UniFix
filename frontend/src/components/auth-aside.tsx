"use client";

import { useEffect, useState } from "react";
import { AnimatePresence, MotionConfig, motion, useReducedMotion } from "motion/react";
import { Check, Lock, MessageCircle } from "lucide-react";
import { cn } from "@/lib/format";
import { LogoMark } from "./ui";

const EASE = [0.22, 1, 0.36, 1] as const;

const FLOW = [
  { Icon: MessageCircle, t: "Agree on a price", d: "Chat with the professional and accept a locked quotation." },
  { Icon: Lock, t: "Payment is held", d: "Your money waits in a Stellar escrow contract, not with anyone." },
  { Icon: Check, t: "Release when done", d: "Approve the finished job and the contract pays them." },
];

function StageCard({ i }: { i: number }) {
  if (i === 0)
    return (
      <div className="rounded-2xl bg-paper p-5 text-sm text-ink">
        <div className="flex justify-between text-ink-3">
          <span>Bedroom AC repair</span>
          <span>v2</span>
        </div>
        <div className="mt-3 flex items-baseline justify-between border-t border-line pt-3">
          <span className="font-semibold">Total</span>
          <span className="font-wide tnum text-2xl font-bold">₦47,500</span>
        </div>
        <span className="mt-4 flex h-10 items-center justify-center gap-2 rounded-lg bg-ink font-semibold text-white">
          <Lock className="size-4" aria-hidden /> Accepted and locked
        </span>
      </div>
    );
  if (i === 1)
    return (
      <div className="overflow-hidden rounded-2xl bg-paper text-sm text-ink">
        <div className="flex items-baseline justify-between p-5">
          <span className="text-ink-3">Escrow contract</span>
          <span className="font-wide tnum text-2xl font-bold">30.65 USDC</span>
        </div>
        <div className="hazard h-2 animate-stripe" />
        <div className="flex items-center gap-2 bg-danfo px-5 py-3 font-semibold">
          <Lock className="size-4" aria-hidden /> Held in Stellar escrow
        </div>
      </div>
    );
  return (
    <div className="relative rounded-2xl bg-paper p-5 text-sm text-ink">
      <p className="text-ink-3">Released to Tunde</p>
      <p className="font-wide tnum mt-1 text-2xl font-bold">30.65 USDC</p>
      <motion.span
        className="font-wide absolute right-5 top-5 rounded-lg border-2 border-lagoon px-2 font-bold text-lagoon"
        initial={{ scale: 2, rotate: -20, opacity: 0 }}
        animate={{ scale: 1, rotate: -8, opacity: 1 }}
        transition={{ delay: 0.35, type: "spring", stiffness: 420, damping: 14 }}
      >
        Paid
      </motion.span>
      <p className="mt-4 flex items-center gap-2 border-t border-line pt-3 text-lagoon-ink">
        <Check className="size-4" aria-hidden /> Customer approved the work
      </p>
    </div>
  );
}

export function AuthAside() {
  const reduce = useReducedMotion();
  const [i, setI] = useState(0);
  useEffect(() => {
    if (reduce) return;
    const t = setInterval(() => setI((x) => (x + 1) % FLOW.length), 3400);
    return () => clearInterval(t);
  }, [reduce]);

  return (
    <MotionConfig reducedMotion="user">
      <aside className="relative hidden overflow-hidden bg-ink p-12 text-white lg:flex lg:flex-col lg:justify-center xl:p-16">
        <LogoMark size={420} light className="pointer-events-none absolute -right-28 -top-24 opacity-[0.05]" />
        <div className="relative mx-auto w-full max-w-sm">
          <p className="text-sm font-semibold text-danfo">How payment works on UniFix</p>
          <h2 className="font-semiwide mt-3 text-3xl font-bold leading-tight">Pay when the job is done.</h2>

          <div className="relative mt-10 h-44">
            <AnimatePresence mode="wait">
              <motion.div
                key={i}
                className="absolute inset-x-0 top-0"
                initial={{ opacity: 0, y: 20, rotate: -1.5 }}
                animate={{ opacity: 1, y: 0, rotate: 0 }}
                exit={{ opacity: 0, y: -14 }}
                transition={{ duration: 0.45, ease: EASE }}
                aria-hidden
              >
                <StageCard i={i} />
              </motion.div>
            </AnimatePresence>
          </div>

          <ol className="mt-10 space-y-1">
            {FLOW.map(({ Icon, t, d }, n) => {
              const on = n === i;
              return (
                <li key={t}>
                  <button type="button" onClick={() => setI(n)} className="flex w-full gap-4 rounded-lg p-3 text-left transition-colors hover:bg-white/5">
                    <span
                      className={cn(
                        "grid size-9 shrink-0 place-items-center rounded-full transition-colors duration-300",
                        on ? "bg-danfo text-ink" : "bg-white/10 text-white/70",
                      )}
                    >
                      <Icon className="size-4" aria-hidden />
                    </span>
                    <span>
                      <span className={cn("block font-semibold transition-colors", on ? "text-white" : "text-white/70")}>{t}</span>
                      <span className={cn("mt-0.5 block text-sm leading-relaxed transition-colors", on ? "text-white/80" : "text-white/50")}>{d}</span>
                    </span>
                  </button>
                </li>
              );
            })}
          </ol>
        </div>
      </aside>
    </MotionConfig>
  );
}
