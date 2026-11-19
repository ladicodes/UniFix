import { BadgeCheck, Lock, Scale, Star } from "lucide-react";
import { HeroSearch } from "./hero-search";

/* Entrance uses CSS keyframes, so the hero shows even before JavaScript runs. */

const PROOF = [
  { Icon: Lock, t: "Escrow on Stellar", d: "A Soroban contract holds the money" },
  { Icon: Star, t: "Verified reviews", d: "Only paying customers can rate" },
  { Icon: Scale, t: "Fair disputes", d: "A resolver checks the evidence" },
];

export function HeroCopy() {
  return (
          <div>
        <span className="animate-rise inline-flex items-center gap-2 rounded-full border border-line bg-paper py-1 pl-1 pr-3 text-sm font-semibold text-ink-2 shadow-lift" style={{ animationDelay: "0s" }}
        >
          <span className="rounded-full bg-stellar px-2 py-0.5 text-xs text-white">New</span>
          Payments held in Stellar escrow
        </span>

        <h1 className="font-wide mt-6 text-5xl font-bold leading-none tracking-tight sm:text-6xl lg:text-5xl xl:text-5xl 2xl:text-6xl min-[1800px]:text-7xl">
          <span className="animate-rise block" style={{ animationDelay: "0.05s" }}>
            Agree on the job.
          </span>
          <span className="animate-rise block" style={{ animationDelay: "0.15s" }}>
            Pay when it&apos;s{" "}
            <span className="relative inline-block">
              <span className="relative z-10">done.</span>
              <span
                aria-hidden
                className="animate-underline absolute inset-x-0 bottom-1 h-3 origin-left rounded-sm bg-danfo"
                style={{ animationDelay: "0.7s" }}
              />
            </span>
          </span>
        </h1>

        <p className="animate-rise mt-6 max-w-xl text-lg leading-relaxed text-ink-2" style={{ animationDelay: "0.25s" }}>
          Hire electricians, plumbers, AC technicians and mechanics in Nigeria and Ghana. Your payment waits in an escrow contract
          until you approve the finished work.
        </p>

        <div className="animate-rise mt-8" style={{ animationDelay: "0.35s" }}>
          <HeroSearch />
        </div>

        <ul className="animate-rise mt-8 grid gap-4 sm:grid-cols-3" style={{ animationDelay: "0.45s" }}>
          {PROOF.map(({ Icon, t, d }) => (
            <li key={t} className="flex gap-3">
              <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-lagoon-soft text-lagoon-ink">
                <Icon className="size-4" aria-hidden />
              </span>
              <span>
                <span className="flex items-center gap-1 text-sm font-semibold">
                  {t}
                  <BadgeCheck className="size-3.5 text-lagoon" aria-hidden />
                </span>
                <span className="mt-0.5 block text-sm leading-snug text-ink-3">{d}</span>
              </span>
            </li>
          ))}
        </ul>
      </div>
  );
}
