"use client";

import { useEffect, useState } from "react";
import { AnimatePresence, MotionConfig, motion, useReducedMotion } from "motion/react";
import { Check, Lock, MessageCircle, ShieldCheck } from "lucide-react";
import { cn } from "@/lib/format";
import { Avatar, LogoMark } from "./ui";

const EASE = [0.22, 1, 0.36, 1] as const;
const STEP_MS = 4200;

const FLOW = [
  { Icon: MessageCircle, t: "Agree on a price", d: "Chat with the professional and accept a locked quotation." },
  { Icon: Lock, t: "Payment is held", d: "Your money waits in a Stellar escrow contract, not with anyone." },
  { Icon: Check, t: "Release when done", d: "Approve the finished job and the contract pays them." },
];

function CardHead({ status, tone }: { status: string; tone: string }) {
  return (
    <div className="flex items-center gap-3 border-b border-line px-6 py-4">
      <Avatar name="Tunde Bakare" size={36} />
      <span className="min-w-0 flex-1">
        <span className="block font-semibold">Bedroom AC: gas refill and leak fix</span>
        <span className="block text-ink-3">Tunde Bakare for Adaeze Okafor</span>
      </span>
      <span className={cn("shrink-0 rounded-full px-2.5 py-1 text-xs font-semibold", tone)}>{status}</span>
    </div>
  );
}

function StageCard({ i }: { i: number }) {
  if (i === 0)
    return (
      <div className="overflow-hidden rounded-2xl bg-paper text-sm text-ink shadow-ticket">
        <CardHead status="Version 2" tone="bg-stellar-soft text-stellar-ink" />
        <dl className="grid grid-cols-2 gap-y-2 px-6 pt-5">
          <dt className="text-ink-3">Labour</dt>
          <dd className="tnum text-right">₦38,000</dd>
          <dt className="text-ink-3">Materials</dt>
          <dd className="tnum text-right">₦9,500</dd>
          <dt className="text-ink-3">Finish by</dt>
          <dd className="text-right">Thursday</dd>
        </dl>
        <div className="mx-6 mt-4 flex items-baseline justify-between border-t border-line pt-4">
          <span className="font-semibold">Total</span>
          <span className="font-wide tnum text-3xl font-bold">₦47,500</span>
        </div>
        <div className="p-6 pt-5">
          <span className="flex h-11 items-center justify-center gap-2 rounded-lg bg-ink font-semibold text-white">
            <Lock className="size-4" aria-hidden /> Accepted and locked
          </span>
        </div>
      </div>
    );
  if (i === 1)
    return (
      <div className="overflow-hidden rounded-2xl bg-paper text-sm text-ink shadow-ticket">
        <CardHead status="Funded" tone="bg-danfo-soft text-danfo-ink" />
        <div className="px-6 py-5">
          <p className="text-ink-3">Held in escrow</p>
          <p className="font-wide tnum mt-1 text-3xl font-bold">30.65 USDC</p>
          <p className="mt-1 text-ink-3">₦47,500 at the agreed rate</p>
          <dl className="mt-4 grid grid-cols-2 gap-y-2 border-t border-line pt-4">
            <dt className="text-ink-3">Contract</dt>
            <dd className="tnum text-right font-semibold">CDUNI…4HGSU</dd>
            <dt className="text-ink-3">Confirmed</dt>
            <dd className="text-right">Ledger 1,194,208</dd>
          </dl>
        </div>
        <div className="hazard h-2 animate-stripe" />
        <div className="flex items-center gap-2 bg-danfo px-6 py-3.5 font-semibold">
          <Lock className="size-4" aria-hidden /> Nobody can move it without your approval
        </div>
      </div>
    );
  return (
    <div className="relative overflow-hidden rounded-2xl bg-paper text-sm text-ink shadow-ticket">
      <CardHead status="Completed" tone="bg-lagoon-soft text-lagoon-ink" />
      <div className="px-6 py-5">
        <ul className="space-y-2 text-ink-2">
          {["Leak found and fixed", "Gas refilled", "Cooling at 18°C"].map((x) => (
            <li key={x} className="flex items-center gap-2.5">
              <span className="grid size-5 place-items-center rounded-full bg-lagoon text-white">
                <Check className="size-3" strokeWidth={3} aria-hidden />
              </span>
              {x}
            </li>
          ))}
        </ul>
        <div className="mt-4 flex items-baseline justify-between border-t border-line pt-4">
          <span className="text-ink-3">Released to Tunde</span>
          <span className="font-wide tnum text-3xl font-bold">30.65 USDC</span>
        </div>
      </div>
      <motion.span
        className="font-wide absolute bottom-24 right-6 rounded-lg border-2 border-lagoon bg-paper px-2.5 text-lg font-bold text-lagoon"
        initial={{ scale: 2, rotate: -20, opacity: 0 }}
        animate={{ scale: 1, rotate: -8, opacity: 1 }}
        transition={{ delay: 0.35, type: "spring", stiffness: 420, damping: 14 }}
      >
        Paid
      </motion.span>
    </div>
  );
}

export function AuthAside() {
  const reduce = useReducedMotion();
  const [i, setI] = useState(0);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (reduce) return;
    const t = setTimeout(() => setI((x) => (x + 1) % FLOW.length), STEP_MS);
    return () => clearTimeout(t);
  }, [i, tick, reduce]);

  const pick = (n: number) => {
    setI(n);
    setTick((x) => x + 1);
  };

  return (
    <MotionConfig reducedMotion="user">
      <aside className="relative hidden overflow-hidden bg-ink text-white lg:flex lg:flex-col">
        <LogoMark size={520} light className="pointer-events-none absolute -right-36 -top-32 opacity-[0.05]" />
        <div className="relative flex flex-1 flex-col justify-center px-10 py-12 xl:px-16">
          <div className="mx-auto w-full max-w-lg">
            <p className="text-sm font-semibold text-danfo">How payment works on UniFix</p>
            <h2 className="font-semiwide mt-3 text-4xl font-bold leading-tight">Pay when the job is done.</h2>
            <p className="mt-3 max-w-md leading-relaxed text-mist">
              Every booking follows the same three steps. The money only moves when the customer approves, or a resolver settles a
              dispute.
            </p>

            <div className="relative mt-10 min-h-88">
              <AnimatePresence mode="wait" initial={false}>
                <motion.div
                  key={i}
                  initial={{ opacity: 0, y: 24, rotate: -1.5 }}
                  animate={{ opacity: 1, y: 0, rotate: 0 }}
                  exit={{ opacity: 0, y: -16 }}
                  transition={{ duration: 0.45, ease: EASE }}
                  aria-hidden
                >
                  <StageCard i={i} />
                </motion.div>
              </AnimatePresence>
            </div>

            <ol className="mt-8 grid grid-cols-3 gap-4">
              {FLOW.map(({ Icon, t, d }, n) => {
                const on = n === i;
                return (
                  <li key={t}>
                    <button type="button" onClick={() => pick(n)} className="group w-full text-left" aria-current={on ? "step" : undefined}>
                      <span className="block h-1 overflow-hidden rounded-full bg-ink-2">
                        {n < i && <span className="block h-full bg-danfo" />}
                        {on && (
                          <motion.span
                            key={`${i}-${tick}`}
                            className="block h-full origin-left bg-danfo"
                            initial={{ scaleX: reduce ? 1 : 0 }}
                            animate={{ scaleX: 1 }}
                            transition={{ duration: reduce ? 0 : STEP_MS / 1000, ease: "linear" }}
                          />
                        )}
                      </span>
                      <span className="mt-4 flex items-center gap-2">
                        <Icon className={cn("size-4 transition-colors", on ? "text-danfo" : "text-mist-2")} aria-hidden />
                        <span className={cn("text-sm font-semibold transition-colors", on ? "text-white" : "text-mist-2 group-hover:text-white")}>{t}</span>
                      </span>
                      <span className={cn("mt-1 block text-xs leading-relaxed transition-colors", on ? "text-mist" : "text-mist-2")}>{d}</span>
                    </button>
                  </li>
                );
              })}
            </ol>
          </div>
        </div>
        <div className="relative flex items-center justify-between border-t border-ink-2 px-10 py-5 text-sm text-mist-2 xl:px-16">
          <span className="flex items-center gap-2">
            <ShieldCheck className="size-4 text-lagoon-soft" aria-hidden />
            Escrow runs on a Soroban smart contract
          </span>
          <span>Stellar testnet</span>
        </div>
      </aside>
    </MotionConfig>
  );
}
