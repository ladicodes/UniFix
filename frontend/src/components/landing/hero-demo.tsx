"use client";

import { useEffect, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { BadgeCheck, Bell, Phone } from "lucide-react";
import { AgreementTicket, type TicketStage } from "@/components/ticket";
import { Avatar } from "@/components/ui";
import { cn, toUsdc } from "@/lib/format";

const SCRIPT: { stage: TicketStage; label: string; note: string; to: string }[] = [
  { stage: "agreed", label: "Agreed", note: "Adaeze accepted your quotation. Price and scope are locked.", to: "To Tunde" },
  { stage: "held", label: "Held", note: "30.65 USDC is held in escrow. You can start the job.", to: "To Tunde" },
  { stage: "submitted", label: "Done", note: "Tunde sent photos and a finished checklist. Approve to pay.", to: "To Adaeze" },
  { stage: "released", label: "Paid", note: "30.65 USDC released to your Stellar wallet.", to: "To Tunde" },
];

const CHAT = [
  { me: true, t: "My bedroom AC is blowing warm air since Sunday." },
  { me: false, t: "Is the outdoor fan spinning? Any frost on the pipes?" },
  { me: true, t: "Fan spins. Bit of frost near the valve." },
];

/** The hero scene: the chat where the job was agreed, the agreement ticket, and the notification each side gets. */
export function HeroDemo() {
  const reduce = useReducedMotion();
  const [i, setI] = useState(1);
  const [paused, setPaused] = useState(false);

  useEffect(() => {
    if (reduce || paused) return;
    const t = setInterval(() => setI((x) => (x + 1) % SCRIPT.length), 3200);
    return () => clearInterval(t);
  }, [reduce, paused]);

  const s = SCRIPT[i];

  return (
    <div className="w-full">
      <div className="relative mx-auto w-full max-w-[40rem] sm:h-[36rem] 2xl:max-w-[44rem]">
        {/* Chat window */}
        <div className="hidden overflow-hidden rounded-2xl border border-line bg-paper shadow-lift sm:absolute sm:left-0 sm:top-6 sm:block sm:w-[70%]">
          <div className="flex items-center gap-3 border-b border-line px-4 py-3">
            <span className="relative">
              <Avatar name="Tunde Bakare" size={36} />
              <span className="absolute bottom-0 right-0 size-2 rounded-full border-2 border-paper bg-lagoon" aria-hidden />
            </span>
            <span className="min-w-0 flex-1">
              <span className="flex items-center gap-1 text-sm font-semibold">
                Tunde Bakare <BadgeCheck className="size-4 text-lagoon" aria-hidden />
              </span>
              <span className="block text-xs text-ink-3">AC technician in Yaba, 4.8 from 214 jobs</span>
            </span>
            <Phone className="size-4 text-ink-3" aria-hidden />
          </div>
          <div className="space-y-2 bg-plaster/60 p-4 pb-48 text-sm">
            {CHAT.map((m) => (
              <p
                key={m.t}
                className={cn(
                  "w-fit max-w-[85%] rounded-2xl px-3 py-2",
                  m.me ? "ml-auto rounded-br-md bg-stellar text-white" : "rounded-bl-md border border-line bg-paper",
                )}
              >
                {m.t}
              </p>
            ))}
            <span className="flex w-14 items-center justify-center gap-1 rounded-2xl rounded-bl-md border border-line bg-paper px-3 py-3" aria-hidden>
              {[0, 1, 2].map((d) => (
                <span key={d} className="size-1.5 animate-bounce rounded-full bg-ink-4" style={{ animationDelay: `${d * 0.15}s` }} />
              ))}
            </span>
          </div>
        </div>

        {/* Agreement ticket over the chat */}
        <div className="relative sm:absolute sm:bottom-0 sm:right-0 sm:w-[62%]">
          <AgreementTicket
            compact
            title="Bedroom 1.5HP split AC: gas refill and leak fix"
            professional="Tunde Bakare"
            customer="Adaeze Okafor"
            labour={38000}
            materials={9500}
            currency="NGN"
            usdcAmount={toUsdc(47500, "NGN")}
            stage={s.stage}
            notch="bg-plaster"
            version={1}
          />
        </div>

        {/* Notification for the current step */}
        <div className="mb-4 sm:absolute sm:-right-2 sm:top-0 sm:z-10 sm:mb-0 sm:w-64" aria-live="polite">
          <AnimatePresence mode="wait" initial={false}>
            <motion.div
              key={i}
              initial={{ opacity: 0, y: -8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.2 }}
              className="flex gap-3 rounded-xl border border-line bg-paper p-3 shadow-ticket"
            >
              <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-stellar text-white">
                <Bell className="size-4" aria-hidden />
              </span>
              <span className="text-sm">
                <span className="block text-xs text-ink-3">{s.to}, just now</span>
                <span className="block leading-snug">{s.note}</span>
              </span>
            </motion.div>
          </AnimatePresence>
        </div>
      </div>

      {/* Step through the example */}
      <div className="mx-auto mt-6 flex w-fit gap-1 rounded-full border border-line bg-paper p-1 shadow-lift" role="group" aria-label="Example booking steps">
        {SCRIPT.map((x, n) => (
          <button
            key={x.stage}
            type="button"
            aria-pressed={n === i}
            onClick={() => {
              setI(n);
              setPaused(true);
            }}
            className={cn(
              "rounded-full px-4 py-2 text-sm font-semibold transition-colors",
              n === i ? "bg-stellar text-white" : "text-ink-2 hover:bg-plaster",
            )}
          >
            {x.label}
          </button>
        ))}
      </div>
    </div>
  );
}
