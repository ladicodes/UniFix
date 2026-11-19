"use client";

import Link from "next/link";
import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  AnimatePresence,
  MotionConfig,
  animate,
  motion,
  useInView,
  useReducedMotion,
  type Variants,
} from "motion/react";
import {
  ArrowRight,
  Bell,
  Car,
  Check,
  Droplets,
  FileCheck2,
  Fuel,
  Hammer,
  Lock,
  PaintRoller,
  PenLine,
  Scale,
  Snowflake,
  Sparkles,
  Zap,
  type LucideIcon,
} from "lucide-react";
import { CATEGORIES, cn } from "@/lib/format";
import type { CategoryId } from "@/lib/types";

const EASE = [0.22, 1, 0.36, 1] as const;

/**
 * Content is visible by default. Only when an element starts below the fold
 * does it hide, so it can animate in as it scrolls into view. Nothing stays
 * blank if an animation or observer never fires.
 */
function useScrollReveal<T extends Element>() {
  const ref = useRef<T>(null);
  const [state, setState] = useState<"idle" | "waiting" | "shown">("idle");
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof IntersectionObserver === "undefined") return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    let first = true;
    const io = new IntersectionObserver(
      ([entry]) => {
        const below = entry.boundingClientRect.top > (entry.rootBounds?.height ?? window.innerHeight);
        if (first) {
          first = false;
          if (!entry.isIntersecting && below) {
            setState("waiting");
            return;
          }
          io.disconnect();
          return;
        }
        if (entry.isIntersecting) {
          setState("shown");
          io.disconnect();
        }
      },
      { threshold: 0.12 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);
  return { ref, hidden: state === "waiting", played: state === "shown" };
}

const fadeUp: Variants = {
  hidden: { opacity: 0, y: 24 },
  show: { opacity: 1, y: 0 },
};

/** Fades and lifts its children in when they scroll into view. */
export function Reveal({ children, className, delay = 0 }: { children: ReactNode; className?: string; delay?: number }) {
  const { ref, hidden } = useScrollReveal<HTMLDivElement>();
  return (
    <MotionConfig reducedMotion="user">
      <motion.div
        ref={ref}
        className={className}
        variants={fadeUp}
        initial={false}
        animate={hidden ? "hidden" : "show"}
        transition={{ duration: hidden ? 0 : 0.7, ease: EASE, delay: hidden ? 0 : delay }}
      >
        {children}
      </motion.div>
    </MotionConfig>
  );
}

/* ------------------------------------------------------------------ */
/* How a job works: one stage, four steps, auto-advancing.             */
/* ------------------------------------------------------------------ */

const bubble: Variants = {
  hidden: { opacity: 0, y: 12, scale: 0.96 },
  show: { opacity: 1, y: 0, scale: 1, transition: { duration: 0.45, ease: EASE } },
};

function ChatStage() {
  return (
    <motion.div
      className="flex flex-col gap-3 text-sm"
      initial="hidden"
      animate="show"
      variants={{ show: { transition: { staggerChildren: 0.55, delayChildren: 0.15 } } }}
    >
      <motion.p variants={bubble} className="max-w-xs self-end rounded-2xl rounded-br-md bg-stellar px-4 py-3 text-white">
        My bedroom AC is blowing warm air since Sunday.
      </motion.p>
      <motion.p variants={bubble} className="max-w-xs rounded-2xl rounded-bl-md bg-paper px-4 py-3 shadow-lift">
        Is the outdoor fan spinning? Any frost on the pipes?
      </motion.p>
      <motion.p variants={bubble} className="max-w-xs self-end rounded-2xl rounded-br-md bg-stellar px-4 py-3 text-white">
        Fan spins. Bit of frost near the valve.
      </motion.p>
      <motion.span variants={bubble} className="flex w-16 items-center justify-center gap-1 rounded-2xl rounded-bl-md bg-paper px-4 py-4 shadow-lift">
        {[0, 1, 2].map((i) => (
          <motion.span
            key={i}
            className="size-1.5 rounded-full bg-ink-4"
            animate={{ y: [0, -4, 0] }}
            transition={{ duration: 0.9, repeat: Infinity, delay: i * 0.15 }}
          />
        ))}
      </motion.span>
    </motion.div>
  );
}

function QuoteStage() {
  const [accepted, setAccepted] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => setAccepted(true), 1900);
    return () => clearTimeout(t);
  }, []);
  const rows = [
    ["Labour", "₦38,000"],
    ["Materials", "₦9,500"],
  ];
  return (
    <div className="w-full max-w-sm rounded-2xl bg-paper p-5 text-sm shadow-lift">
      <div className="flex items-center justify-between">
        <p className="font-semibold">Bedroom AC gas leak repair</p>
        <span className="text-xs font-semibold text-ink-3">v2</span>
      </div>
      <div className="mt-4 space-y-2">
        {rows.map(([k, v], i) => (
          <motion.div
            key={k}
            className="flex justify-between text-ink-3"
            initial={{ opacity: 0, x: -8 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: 0.15 + i * 0.2, duration: 0.4, ease: EASE }}
          >
            <span>{k}</span>
            <span className="tnum">{v}</span>
          </motion.div>
        ))}
      </div>
      <motion.div
        className="mt-3 flex items-baseline justify-between border-t border-line pt-3"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 0.6 }}
      >
        <span className="font-semibold">Total</span>
        <span className="font-wide tnum text-2xl font-bold">₦47,500</span>
      </motion.div>
      <motion.div
        className={cn(
          "mt-4 flex h-11 items-center justify-center gap-2 overflow-hidden rounded-lg font-semibold text-white transition-colors duration-300",
          accepted ? "bg-ink" : "bg-stellar",
        )}
        animate={accepted ? { scale: [1, 0.95, 1] } : {}}
        transition={{ duration: 0.3 }}
      >
        <AnimatePresence mode="wait" initial={false}>
          {accepted ? (
            <motion.span key="a" className="flex items-center gap-2" initial={{ y: 16, opacity: 0 }} animate={{ y: 0, opacity: 1 }}>
              <Lock className="size-4" aria-hidden />
              Accepted and locked
            </motion.span>
          ) : (
            <motion.span key="b" exit={{ y: -16, opacity: 0 }}>
              Accept quotation
            </motion.span>
          )}
        </AnimatePresence>
      </motion.div>
    </div>
  );
}

function HeldStage() {
  return (
    <div className="w-full max-w-sm overflow-hidden rounded-2xl bg-paper text-sm shadow-lift">
      <div className="flex items-baseline justify-between p-5">
        <span className="text-ink-3">Escrow contract</span>
        <CountUp to={30.65} className="font-wide tnum text-2xl font-bold" suffix=" USDC" />
      </div>
      <motion.div
        className="origin-left"
        initial={{ scaleX: 0 }}
        animate={{ scaleX: 1 }}
        transition={{ duration: 0.9, ease: EASE, delay: 0.2 }}
      >
        <div className="hazard h-2 animate-stripe" />
        <div className="flex items-center gap-2 bg-danfo px-5 py-3 font-semibold">
          <motion.span initial={{ rotate: -20, scale: 0.6 }} animate={{ rotate: 0, scale: 1 }} transition={{ delay: 0.9, type: "spring" }}>
            <Lock className="size-4" aria-hidden />
          </motion.span>
          Held in Stellar escrow
        </div>
      </motion.div>
      <p className="px-5 py-4 text-ink-3">Tunde can see the money is there. Nobody can move it without you.</p>
    </div>
  );
}

function PaidStage() {
  const items = ["Leak found and fixed", "Gas refilled", "Cooling at 18°C"];
  return (
    <div className="relative w-full max-w-sm rounded-2xl bg-paper p-5 text-sm shadow-lift">
      <ul className="space-y-2.5 text-ink-2">
        {items.map((x, i) => (
          <motion.li
            key={x}
            className="flex items-center gap-3"
            initial={{ opacity: 0, x: -8 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: 0.2 + i * 0.35, duration: 0.35 }}
          >
            <motion.span
              className="grid size-5 place-items-center rounded-full bg-lagoon text-white"
              initial={{ scale: 0 }}
              animate={{ scale: 1 }}
              transition={{ delay: 0.35 + i * 0.35, type: "spring", stiffness: 500, damping: 18 }}
            >
              <Check className="size-3" strokeWidth={3} aria-hidden />
            </motion.span>
            {x}
          </motion.li>
        ))}
      </ul>
      <p className="mt-4 border-t border-line pt-3 text-ink-3">
        Released to Tunde <span className="tnum font-semibold text-ink">30.65 USDC</span>
      </p>
      <motion.span
        className="font-wide absolute right-4 top-4 rounded-lg border-2 border-lagoon px-2 text-base font-bold text-lagoon"
        initial={{ scale: 2.2, rotate: -24, opacity: 0 }}
        animate={{ scale: 1, rotate: -8, opacity: 1 }}
        transition={{ delay: 1.45, type: "spring", stiffness: 420, damping: 14 }}
      >
        Paid
      </motion.span>
    </div>
  );
}

const STEPS = [
  {
    title: "Find and talk",
    body: "Compare ratings left by customers with a paid booking, then chat or call to describe the job.",
    Stage: ChatStage,
  },
  {
    title: "Agree on a quotation",
    body: "Labour, materials, date and terms. When you accept, that version is locked.",
    Stage: QuoteStage,
  },
  {
    title: "Hold the payment",
    body: "You fund a Soroban escrow contract from your Stellar wallet. The professional sees the money is there before they start.",
    Stage: HeldStage,
  },
  {
    title: "Approve and release",
    body: "They send photos and a checklist. The contract pays them only after you approve.",
    Stage: PaidStage,
  },
];

const STEP_MS = 5200;

export function HowItWorks() {
  const reduce = useReducedMotion();
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { margin: "-120px" });
  const [active, setActive] = useState(0);
  const [hover, setHover] = useState(false);
  const running = !reduce && inView && !hover;
  const { Stage } = STEPS[active];

  return (
    <MotionConfig reducedMotion="user">
      <div
        ref={ref}
        className="mt-12 grid gap-8 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] lg:gap-16"
        onMouseEnter={() => setHover(true)}
        onMouseLeave={() => setHover(false)}
      >
        <ol className="order-2 lg:order-1">
          {STEPS.map((s, i) => {
            const on = i === active;
            return (
              <li key={s.title} className="relative border-b border-line last:border-b-0">
                <button
                  type="button"
                  onClick={() => setActive(i)}
                  aria-current={on ? "step" : undefined}
                  className="group flex w-full gap-5 py-5 text-left"
                >
                  <span
                    className={cn(
                      "tnum grid size-9 shrink-0 place-items-center rounded-full text-sm font-semibold transition-colors duration-300",
                      on ? "bg-stellar text-white" : "bg-plaster text-ink-3 group-hover:bg-stellar-soft group-hover:text-stellar-ink",
                    )}
                  >
                    {i + 1}
                  </span>
                  <span className="min-w-0 flex-1 pt-1.5">
                    <span className={cn("block text-lg font-semibold transition-colors", on ? "text-ink" : "text-ink-3 group-hover:text-ink")}>
                      {s.title}
                    </span>
                    <AnimatePresence initial={false}>
                      {on && (
                        <motion.span
                          className="block overflow-hidden"
                          initial={{ height: 0, opacity: 0 }}
                          animate={{ height: "auto", opacity: 1 }}
                          exit={{ height: 0, opacity: 0 }}
                          transition={{ duration: 0.4, ease: EASE }}
                        >
                          <span className="block pt-2 leading-relaxed text-ink-2">{s.body}</span>
                        </motion.span>
                      )}
                    </AnimatePresence>
                  </span>
                </button>
                {on && (
                  <span className="absolute inset-x-0 -bottom-px h-0.5 overflow-hidden bg-line" aria-hidden>
                    <motion.span
                      key={`${active}-${running}`}
                      className="block h-full origin-left bg-stellar"
                      initial={{ scaleX: running ? 0 : 1 }}
                      animate={{ scaleX: 1 }}
                      transition={{ duration: running ? STEP_MS / 1000 : 0, ease: "linear" }}
                      onAnimationComplete={() => running && setActive((x) => (x + 1) % STEPS.length)}
                    />
                  </span>
                )}
              </li>
            );
          })}
        </ol>

        <div
          className="relative order-1 flex min-h-[22rem] items-center justify-center overflow-hidden rounded-2xl bg-plaster px-6 py-10 sm:min-h-[26rem] lg:order-2"
          aria-hidden
        >
          <div
            className="pointer-events-none absolute inset-0 opacity-60 [background-image:radial-gradient(var(--color-line)_1px,transparent_1px)] [background-size:20px_20px]"
          />
          <span className="tnum absolute left-6 top-5 text-sm font-semibold text-ink-3">
            Step {active + 1} of {STEPS.length}
          </span>
          <AnimatePresence mode="wait" initial={false}>
            <motion.div
              key={active}
              className="relative flex w-full max-w-sm justify-center"
              initial={{ opacity: 0, y: 24, filter: "blur(6px)" }}
              animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
              exit={{ opacity: 0, y: -16, filter: "blur(6px)" }}
              transition={{ duration: 0.45, ease: EASE }}
            >
              <Stage />
            </motion.div>
          </AnimatePresence>
        </div>
      </div>
    </MotionConfig>
  );
}

/* ------------------------------------------------------------------ */
/* Trades                                                             */
/* ------------------------------------------------------------------ */

const TRADE_ICON: Record<CategoryId, LucideIcon> = {
  electrician: Zap,
  plumber: Droplets,
  "ac-technician": Snowflake,
  mechanic: Car,
  generator: Fuel,
  carpenter: Hammer,
  cleaner: Sparkles,
  painter: PaintRoller,
};

const TRADE_JOBS: Record<CategoryId, string> = {
  electrician: "Wiring, breakers, inverter and solar backup",
  plumber: "Leaks, borehole pumps, water heaters",
  "ac-technician": "Gas refill, leak repair, installation",
  mechanic: "Diagnostics, brakes, servicing at your gate",
  generator: "Servicing, rewinding, changeover switches",
  carpenter: "Wardrobes, kitchen cabinets, doors",
  cleaner: "Deep cleans, post-construction, move-out",
  painter: "Interior, exterior, POP ceilings",
};

export function TradeGrid() {
  const { ref, hidden } = useScrollReveal<HTMLUListElement>();
  return (
    <MotionConfig reducedMotion="user">
      <motion.ul
        ref={ref}
        className="mt-10 grid gap-3 sm:grid-cols-2 lg:grid-cols-4"
        initial={false}
        animate={hidden ? "hidden" : "show"}
        variants={{ show: { transition: { staggerChildren: 0.06 } } }}
      >
        {CATEGORIES.map((c) => {
          const Icon = TRADE_ICON[c.id];
          return (
            <motion.li
              key={c.id}
              variants={{
                hidden: { opacity: 0, y: 20, transition: { duration: 0 } },
                show: { opacity: 1, y: 0, transition: { duration: 0.5, ease: EASE } },
              }}
            >
              <Link
                href={`/discover?category=${c.id}`}
                className="group flex h-full flex-col rounded-2xl border border-line bg-paper p-5 transition duration-300 hover:-translate-y-1 hover:border-stellar hover:shadow-lift"
              >
                <span className="grid size-11 place-items-center rounded-lg bg-plaster text-ink-2 transition-colors duration-300 group-hover:bg-stellar group-hover:text-white">
                  <Icon className="size-5" aria-hidden />
                </span>
                <span className="mt-5 text-lg font-semibold">{c.plural}</span>
                <span className="mt-1 text-sm leading-relaxed text-ink-3">{TRADE_JOBS[c.id]}</span>
                <span className="mt-auto flex items-center gap-1 pt-5 text-sm font-semibold text-stellar">
                  See professionals
                  <ArrowRight className="size-4 transition-transform duration-300 group-hover:translate-x-1" aria-hidden />
                </span>
              </Link>
            </motion.li>
          );
        })}
      </motion.ul>
    </MotionConfig>
  );
}

/* ------------------------------------------------------------------ */
/* Dispute settlement                                                  */
/* ------------------------------------------------------------------ */

function CountUp({ to, className, suffix = "", decimals = 2 }: { to: number; className?: string; suffix?: string; decimals?: number }) {
  const [v, setV] = useState(0);
  const from = useRef(0);
  const reduce = useReducedMotion();
  useEffect(() => {
    if (reduce) return;
    const c = animate(from.current, to, {
      duration: 0.8,
      ease: EASE,
      onUpdate: (x) => {
        from.current = x;
        setV(x);
      },
    });
    return () => c.stop();
  }, [to, reduce]);
  return (
    <span className={className}>
      {(reduce ? to : v).toFixed(decimals)}
      {suffix}
    </span>
  );
}

const TOTAL = 107.14;
const OUTCOMES = [
  { id: "release", label: "Release", pro: 1 },
  { id: "split", label: "Split", pro: 0.8 },
  { id: "refund", label: "Refund", pro: 0 },
] as const;

const SAFEGUARDS = [
  { Icon: FileCheck2, t: "Evidence stays with the booking", d: "Photos, checklists and the locked quotation are kept for the resolver to review." },
  { Icon: Scale, t: "No silent price changes", d: "A new price needs a new quotation and your acceptance. Funded terms never change." },
  { Icon: PenLine, t: "You sign every payment", d: "UniFix never holds your keys. Your wallet shows the asset and amount before you approve." },
];

export function Safeguards() {
  const { ref, hidden } = useScrollReveal<HTMLDListElement>();
  return (
    <MotionConfig reducedMotion="user">
      <motion.dl
        ref={ref}
        className="mt-10 grid gap-6 sm:grid-cols-3 lg:grid-cols-1 xl:grid-cols-3"
        initial={false}
        animate={hidden ? "hidden" : "show"}
        variants={{ show: { transition: { staggerChildren: 0.12 } } }}
      >
        {SAFEGUARDS.map(({ Icon, t, d }) => (
          <motion.div
            key={t}
            variants={{ hidden: { opacity: 0, y: 16, transition: { duration: 0 } }, show: { opacity: 1, y: 0, transition: { duration: 0.5, ease: EASE } } }}
          >
            <span className="grid size-9 place-items-center rounded-lg bg-paper text-stellar shadow-lift">
              <Icon className="size-4" aria-hidden />
            </span>
            <dt className="mt-3 font-semibold">{t}</dt>
            <dd className="mt-1 text-sm leading-relaxed text-ink-2">{d}</dd>
          </motion.div>
        ))}
      </motion.dl>
    </MotionConfig>
  );
}

export function DisputeDemo() {
  const [pick, setPick] = useState<(typeof OUTCOMES)[number]["id"]>("split");
  const o = OUTCOMES.find((x) => x.id === pick)!;
  const toPro = Math.round(TOTAL * o.pro * 100) / 100;
  const toCustomer = Math.round((TOTAL - toPro) * 100) / 100;
  const { ref, hidden } = useScrollReveal<HTMLDivElement>();

  return (
    <MotionConfig reducedMotion="user">
      <motion.div
        ref={ref}
        className="w-full max-w-xl rounded-2xl bg-paper p-6 shadow-ticket sm:p-8 lg:justify-self-end"
        initial={false}
        animate={hidden ? { opacity: 0, y: 32, rotate: 1.5 } : { opacity: 1, y: 0, rotate: 0 }}
        transition={{ duration: hidden ? 0 : 0.8, ease: EASE }}
      >
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-sm text-ink-3">Dispute on booking</p>
            <p className="mt-0.5 font-semibold">Post-construction clean, East Legon</p>
          </div>
          <span className="flex items-center gap-1.5 rounded-full bg-clay-soft px-2.5 py-1 text-xs font-semibold text-clay-ink">
            <Lock className="size-3" aria-hidden />
            Locked
          </span>
        </div>
        <p className="mt-4 rounded-lg bg-plaster px-4 py-3 text-sm text-ink-2">
          &ldquo;Balcony tiles still have cement stains. Happy to release most of it.&rdquo;
        </p>

        <div role="radiogroup" aria-label="Settlement" className="mt-6 grid grid-cols-3 gap-1 rounded-lg bg-plaster p-1 text-sm font-semibold">
          {OUTCOMES.map((x) => (
            <button
              key={x.id}
              type="button"
              role="radio"
              aria-checked={pick === x.id}
              onClick={() => setPick(x.id)}
              className={cn("relative rounded-md px-3 py-2.5 transition-colors", pick === x.id ? "text-white" : "text-ink-3 hover:text-ink")}
            >
              {pick === x.id && (
                <motion.span layoutId="outcome-pill" className="absolute inset-0 rounded-md bg-stellar" transition={{ type: "spring", stiffness: 420, damping: 34 }} />
              )}
              <span className="relative">{x.label}</span>
            </button>
          ))}
        </div>

        <div className="mt-6 flex h-3 gap-1 overflow-hidden rounded-full">
          <motion.span className="rounded-full bg-stellar" animate={{ flexGrow: Math.max(o.pro, 0.0001) }} style={{ flexBasis: 0 }} transition={{ duration: 0.6, ease: EASE }} />
          <motion.span className="rounded-full bg-ink-4" animate={{ flexGrow: Math.max(1 - o.pro, 0.0001) }} style={{ flexBasis: 0 }} transition={{ duration: 0.6, ease: EASE }} />
        </div>
        <div className="mt-3 flex justify-between text-sm">
          <span>
            <CountUp to={toPro} className="tnum font-semibold" suffix=" USDC" /> <span className="text-ink-3">to Ama</span>
          </span>
          <span className="text-right">
            <CountUp to={toCustomer} className="tnum font-semibold" suffix=" USDC" /> <span className="text-ink-3">back to Kofi</span>
          </span>
        </div>
        <p className="mt-6 border-t border-line pt-4 text-sm text-ink-3">Try it. The escrow contract settles the chosen split once the resolver signs.</p>
      </motion.div>
    </MotionConfig>
  );
}

/* ------------------------------------------------------------------ */
/* Professional notification feed                                      */
/* ------------------------------------------------------------------ */

const PRO_FEED = [
  { t: "Quotation accepted", d: "Adaeze accepted your quotation for the bedroom AC.", when: "Tue 09:14", dot: "bg-stellar" },
  { t: "Payment secured", d: "30.65 USDC is held in escrow. You can start the job.", when: "Tue 09:16", dot: "bg-danfo" },
  { t: "Payment released", d: "30.65 USDC sent to your Stellar wallet.", when: "Thu 14:05", dot: "bg-lagoon" },
];

export function ProFeed() {
  // Every notification is visible unless the card starts below the fold;
  // then they arrive one by one as it scrolls into view.
  const { ref, hidden, played } = useScrollReveal<HTMLDivElement>();
  const [count, setCount] = useState(0);

  useEffect(() => {
    if (!played) return;
    const timers = PRO_FEED.map((_, i) => setTimeout(() => setCount(i + 1), 300 + i * 900));
    return () => timers.forEach(clearTimeout);
  }, [played]);

  const shown = hidden ? 0 : played ? count : PRO_FEED.length;

  return (
    <MotionConfig reducedMotion="user">
      <div ref={ref} className="w-full max-w-xl lg:justify-self-end" aria-label="Example notifications">
        <div className="overflow-hidden rounded-2xl border border-line bg-paper shadow-lift">
          <div className="flex items-center justify-between border-b border-line px-5 py-4">
            <span className="flex items-center gap-2 font-semibold">
              <Bell className="size-4 text-ink-3" aria-hidden />
              Notifications
            </span>
            <span className="tnum text-sm text-ink-3">{shown} new</span>
          </div>
          <ul className="min-h-[18rem]">
            <AnimatePresence initial={false}>
              {PRO_FEED.slice(0, shown)
                .map((n, i) => ({ ...n, i }))
                .reverse()
                .map((n) => (
                  <motion.li
                    key={n.t}
                    layout
                    className="flex gap-4 border-b border-line p-5 last:border-b-0"
                    initial={{ opacity: 0, y: -20, scale: 0.98 }}
                    animate={{ opacity: 1, y: 0, scale: 1 }}
                    transition={{ type: "spring", stiffness: 380, damping: 30 }}
                  >
                    <span className="relative mt-2 size-2 shrink-0" aria-hidden>
                      {n.i === shown - 1 && <span className={cn("absolute inset-0 animate-ping rounded-full opacity-60", n.dot)} />}
                      <span className={cn("relative block size-2 rounded-full", n.dot)} />
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-baseline justify-between gap-3">
                        <p className="font-semibold">{n.t}</p>
                        <span className="tnum shrink-0 text-sm text-ink-3">{n.when}</span>
                      </div>
                      <p className="mt-1 text-sm text-ink-2">{n.d}</p>
                    </div>
                  </motion.li>
                ))}
            </AnimatePresence>
          </ul>
        </div>
      </div>
    </MotionConfig>
  );
}
