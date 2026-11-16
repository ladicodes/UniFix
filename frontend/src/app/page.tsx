import Link from "next/link";
import { BadgeCheck, Check, Lock } from "lucide-react";
import { HeroDemo } from "@/components/landing/hero-demo";
import { HeroSearch } from "@/components/landing/hero-search";
import { LandingNav } from "@/components/landing/nav";
import { Logo } from "@/components/ui";
import { CATEGORIES } from "@/lib/format";

/* Small, static copies of real Handi screens, used to show each step. */

function ChatFragment() {
  return (
    <div className="flex flex-col gap-2 text-sm">
      <p className="max-w-xs self-end rounded-2xl rounded-br-md bg-stellar px-3 py-2 text-white">
        My bedroom AC is blowing warm air since Sunday.
      </p>
      <p className="max-w-xs rounded-2xl rounded-bl-md border border-line bg-paper px-3 py-2">
        Is the outdoor fan spinning? Any frost on the pipes?
      </p>
    </div>
  );
}

function QuoteFragment() {
  return (
    <div className="rounded-lg border border-line bg-paper p-3 text-sm">
      <div className="flex justify-between text-ink-3">
        <span>Labour</span>
        <span className="tnum">₦38,000</span>
      </div>
      <div className="mt-1 flex justify-between text-ink-3">
        <span>Materials</span>
        <span className="tnum">₦9,500</span>
      </div>
      <div className="mt-2 flex items-baseline justify-between border-t border-line pt-2">
        <span className="font-semibold">Total</span>
        <span className="font-wide tnum text-lg font-bold">₦47,500</span>
      </div>
      <span className="mt-3 flex h-9 items-center justify-center rounded-lg bg-stellar font-semibold text-white">Accept quotation</span>
    </div>
  );
}

function HeldFragment() {
  return (
    <div className="overflow-hidden rounded-lg bg-paper text-sm">
      <div className="flex items-baseline justify-between p-3">
        <span className="text-ink-3">Escrow</span>
        <span className="tnum font-semibold">30.65 USDC</span>
      </div>
      <div className="hazard h-2" />
      <div className="flex items-center gap-2 bg-danfo px-3 py-2 font-semibold">
        <Lock className="size-4" aria-hidden />
        Held in Stellar escrow
      </div>
    </div>
  );
}

function PaidFragment() {
  return (
    <div className="relative rounded-lg border border-line bg-paper p-3 text-sm">
      <ul className="space-y-1 text-ink-2">
        {["Leak found and fixed", "Gas refilled", "Cooling at 18°C"].map((x) => (
          <li key={x} className="flex items-center gap-2">
            <Check className="size-4 text-lagoon" aria-hidden />
            {x}
          </li>
        ))}
      </ul>
      <p className="mt-3 border-t border-line pt-2 text-ink-3">
        Released to Tunde <span className="tnum font-semibold text-ink">30.65 USDC</span>
      </p>
      <span className="font-wide absolute right-3 top-3 -rotate-6 rounded-lg border-2 border-lagoon px-2 text-sm font-bold text-lagoon">Paid</span>
    </div>
  );
}

const STEPS = [
  {
    title: "Find and talk",
    body: "Compare ratings left by customers with a paid booking, then chat or call to describe the job.",
    fragment: <ChatFragment />,
  },
  {
    title: "Agree on a quotation",
    body: "Labour, materials, date and terms. When you accept, that version is locked.",
    fragment: <QuoteFragment />,
  },
  {
    title: "Hold the payment",
    body: "You fund a Soroban escrow contract from your Stellar wallet. The professional sees the money is there before they start.",
    fragment: <HeldFragment />,
  },
  {
    title: "Approve and release",
    body: "They send photos and a checklist. The contract pays them only after you approve.",
    fragment: <PaidFragment />,
  },
];

const CATEGORY_JOBS: Record<string, string> = {
  electrician: "Wiring, breakers, inverter and solar backup",
  plumber: "Leaks, borehole pumps, water heaters",
  "ac-technician": "Gas refill, leak repair, installation",
  mechanic: "Diagnostics, brakes, servicing at your gate",
  generator: "Servicing, rewinding, changeover switches",
  carpenter: "Wardrobes, kitchen cabinets, doors",
  cleaner: "Deep cleans, post-construction, move-out",
  painter: "Interior, exterior, POP ceilings",
};

const SAFEGUARDS = [
  { t: "Evidence stays with the booking", d: "Photos, checklists and the locked quotation are kept for the resolver to review." },
  { t: "No silent price changes", d: "A new price needs a new quotation and your acceptance. Funded terms never change." },
  { t: "You sign every payment", d: "Handi never holds your keys. Your wallet shows the asset and amount before you approve." },
];

const PRO_FEED = [
  { t: "Quotation accepted", d: "Adaeze accepted your quotation for the bedroom AC.", when: "Tue 09:14" },
  { t: "Payment secured", d: "30.65 USDC is held in escrow. You can start the job.", when: "Tue 09:16", held: true },
  { t: "Payment released", d: "30.65 USDC sent to your Stellar wallet.", when: "Thu 14:05", paid: true },
];

const pad = "px-4 sm:px-6 lg:px-10";

export default function Home() {
  return (
    <div className="min-h-dvh bg-paper">
      <LandingNav />

      <main>
        <section className={`grid gap-10 pb-16 pt-6 md:pt-10 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)] lg:items-stretch lg:gap-12 ${pad}`}>
          <div className="flex flex-col justify-center lg:py-10">
            <h1 className="font-wide text-5xl font-bold leading-none tracking-tight sm:text-6xl lg:text-5xl xl:text-6xl 2xl:text-7xl">
              <span className="block">Agree on the job.</span>
              <span className="block">Pay when it&apos;s done.</span>
            </h1>
            <p className="mt-6 max-w-xl text-lg leading-relaxed text-ink-2">
              Hire electricians, plumbers, AC technicians and mechanics in Nigeria and Ghana. Your payment waits in a Stellar escrow
              contract until you approve the finished work.
            </p>
            <div className="mt-8">
              <HeroSearch />
            </div>
            <ul className="mt-8 grid max-w-xl gap-4 border-t border-line pt-6 sm:grid-cols-3">
              {[
                { t: "Escrow on Stellar", d: "A Soroban contract holds your payment until you approve the work." },
                { t: "Verified reviews", d: "Only customers with a paid booking can rate." },
                { t: "Dispute review", d: "A Handi resolver checks the evidence before any refund or release." },
              ].map((x) => (
                <li key={x.t}>
                  <p className="flex items-center gap-2 font-semibold">
                    <BadgeCheck className="size-4 shrink-0 text-lagoon" aria-hidden />
                    {x.t}
                  </p>
                  <p className="mt-1 text-sm leading-relaxed text-ink-3">{x.d}</p>
                </li>
              ))}
            </ul>
          </div>
          <div className="flex items-center rounded-2xl bg-plaster px-4 py-10 sm:px-8 lg:py-12">
            <HeroDemo />
          </div>
        </section>

        {/* A real sequence, so it is numbered */}
        <section id="how" className={`border-t border-line py-20 ${pad}`}>
          <div className="flex flex-wrap items-end justify-between gap-4">
            <h2 className="font-semiwide text-3xl font-bold">How a job works</h2>
            <p className="max-w-md text-ink-3">The same four steps for every booking, whether it&apos;s a small leak or a full rewire.</p>
          </div>
          <ol className="mt-12 grid gap-6 sm:grid-cols-2 xl:grid-cols-4">
            {STEPS.map((s, i) => (
              <li key={s.title} className="flex flex-col">
                <div className="flex min-h-44 flex-col justify-center border-b border-line pb-6" aria-hidden>
                  {s.fragment}
                </div>
                <p className="tnum mt-5 text-sm font-semibold text-ink-3">Step {i + 1}</p>
                <h3 className="mt-1 text-lg font-semibold">{s.title}</h3>
                <p className="mt-2 leading-relaxed text-ink-2">{s.body}</p>
              </li>
            ))}
          </ol>
        </section>

        <section className={`grid gap-10 border-t border-line py-20 lg:grid-cols-[1fr_2fr] lg:gap-16 ${pad}`}>
          <div>
            <h2 className="font-semiwide text-3xl font-bold">What do you need fixed?</h2>
            <p className="mt-4 max-w-sm leading-relaxed text-ink-2">
              Eight trades across Lagos, Abuja, Accra and Kumasi. Every professional shows their verification, rating and starting price
              before you message them.
            </p>
            <Link href="/discover" className="mt-6 inline-flex h-12 items-center rounded-lg bg-stellar px-6 font-semibold text-white hover:bg-stellar-ink">
              Browse all professionals
            </Link>
          </div>
          <ul className="grid gap-x-8 border-t border-line sm:grid-cols-2">
            {CATEGORIES.map((c) => (
              <li key={c.id} className="border-b border-line">
                <Link href={`/discover?category=${c.id}`} className="group flex items-center justify-between gap-4 py-5">
                  <span>
                    <span className="block text-lg font-semibold group-hover:text-stellar">{c.plural}</span>
                    <span className="mt-1 block text-sm text-ink-3">{CATEGORY_JOBS[c.id]}</span>
                  </span>
                  <span className="shrink-0 text-sm font-semibold text-ink-3 group-hover:text-stellar">See all</span>
                </Link>
              </li>
            ))}
          </ul>
        </section>

        <section className="border-t border-line bg-plaster">
          <div className={`grid items-center gap-12 py-20 lg:grid-cols-2 lg:gap-16 ${pad}`}>
            <div>
              <h2 className="font-semiwide text-3xl font-bold leading-tight">If the job isn&apos;t right, the money doesn&apos;t move.</h2>
              <p className="mt-5 max-w-xl text-lg leading-relaxed text-ink-2">
                Raise a dispute instead of approving. The escrow contract locks the funds so neither side can withdraw them. A Handi
                resolver reviews the agreement, the chat and the completion photos, then authorises a release, a refund or a split.
              </p>
              <dl className="mt-10 grid gap-6 sm:grid-cols-3 lg:grid-cols-1 xl:grid-cols-3">
                {SAFEGUARDS.map((x) => (
                  <div key={x.t}>
                    <dt className="font-semibold">{x.t}</dt>
                    <dd className="mt-1 text-sm leading-relaxed text-ink-2">{x.d}</dd>
                  </div>
                ))}
              </dl>
            </div>

            {/* Copy of the resolver's settlement view */}
            <div className="mx-auto w-full max-w-lg rounded-2xl bg-paper p-6 shadow-lift" aria-hidden>
              <div className="flex items-center justify-between gap-3">
                <p className="font-semibold">Post-construction clean, East Legon</p>
                <span className="rounded-lg bg-clay-soft px-2 py-0.5 text-xs font-semibold text-clay-ink">Locked</span>
              </div>
              <p className="mt-2 text-sm text-ink-2">
                &ldquo;Balcony tiles still have cement stains. Happy to release most of it.&rdquo;
              </p>
              <div className="mt-5 grid grid-cols-3 gap-2 text-sm font-semibold">
                <span className="rounded-lg border border-line px-3 py-2 text-center text-ink-3">Release</span>
                <span className="rounded-lg border-2 border-stellar bg-stellar-soft px-3 py-2 text-center text-stellar-ink">Split</span>
                <span className="rounded-lg border border-line px-3 py-2 text-center text-ink-3">Refund</span>
              </div>
              <div className="mt-5 flex h-3 overflow-hidden rounded-full">
                <span className="w-4/5 bg-stellar" />
                <span className="w-1/5 bg-ink-4" />
              </div>
              <div className="mt-3 flex justify-between text-sm">
                <span>
                  <span className="tnum font-semibold">85.71 USDC</span> <span className="text-ink-3">to Ama</span>
                </span>
                <span>
                  <span className="tnum font-semibold">21.43 USDC</span> <span className="text-ink-3">back to Kofi</span>
                </span>
              </div>
              <p className="mt-5 border-t border-line pt-4 text-sm text-ink-3">Settled by the escrow contract once the resolver signs.</p>
            </div>
          </div>
        </section>

        <section id="pros" className={`grid items-center gap-12 border-t border-line py-20 lg:grid-cols-2 lg:gap-16 ${pad}`}>
          <div>
            <h2 className="font-semiwide text-3xl font-bold leading-tight">Professionals start every job with the money already held.</h2>
            <p className="mt-4 max-w-xl text-lg leading-relaxed text-ink-2">
              Every booking is funded before you leave home. Send clear quotations, get paid to your Stellar wallet on approval, and
              build a rating from customers who paid for the work.
            </p>
            <div className="mt-8 flex flex-wrap items-center gap-4">
              <Link href="/sign-up?role=professional" className="inline-flex h-12 items-center rounded-lg bg-stellar px-6 font-semibold text-white hover:bg-stellar-ink">
                Join as a professional
              </Link>
              <Link href="/sign-in" className="font-semibold text-ink-2 underline-offset-4 hover:underline">
                Sign in
              </Link>
            </div>
          </div>

          {/* What a professional's notifications look like during one job */}
          <ul className="mx-auto w-full max-w-lg divide-y divide-line overflow-hidden rounded-2xl border border-line" aria-label="Example notifications">
            {PRO_FEED.map((n) => (
              <li key={n.t} className="flex gap-4 bg-paper p-5">
                <span
                  aria-hidden
                  className={`mt-2 size-2 shrink-0 rounded-full ${n.held ? "bg-danfo" : n.paid ? "bg-lagoon" : "bg-stellar"}`}
                />
                <div className="min-w-0 flex-1">
                  <div className="flex items-baseline justify-between gap-3">
                    <p className="font-semibold">{n.t}</p>
                    <span className="tnum shrink-0 text-sm text-ink-3">{n.when}</span>
                  </div>
                  <p className="mt-1 text-sm text-ink-2">{n.d}</p>
                </div>
              </li>
            ))}
          </ul>
        </section>
      </main>

      <footer className="border-t border-line">
        <div className={`flex w-full flex-col gap-4 py-10 text-sm text-ink-3 sm:flex-row sm:items-center sm:justify-between ${pad}`}>
          <Logo className="text-lg" />
          <p>Built for the Stellar Buildathon. Payments run on Stellar testnet.</p>
        </div>
      </footer>
    </div>
  );
}
