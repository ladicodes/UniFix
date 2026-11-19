import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { HeroDemo } from "@/components/landing/hero-demo";
import { HeroCopy } from "@/components/landing/hero-copy";
import { LandingNav } from "@/components/landing/nav";
import { DisputeDemo, HowItWorks, ProFeed, Reveal, Safeguards, TradeGrid } from "@/components/landing/sections";
import { Logo } from "@/components/ui";

const pad = "px-4 sm:px-6 lg:px-10";

export default function Home() {
  return (
    <div className="min-h-dvh bg-paper">
      <LandingNav />

      <main>
        <section className="relative overflow-hidden">
          <div
            aria-hidden
            className="pointer-events-none absolute inset-0 [background-image:radial-gradient(var(--color-line)_1px,transparent_1px)] [background-size:22px_22px] [mask-image:linear-gradient(to_bottom,black,transparent_85%)]"
          />
          <div className={`relative grid items-center gap-12 pb-20 pt-8 md:pt-14 lg:grid-cols-2 lg:gap-10 xl:gap-16 ${pad}`}>
            <HeroCopy />
            <div className="relative">
              <HeroDemo />
            </div>
          </div>
        </section>

        <section id="how" className={`border-t border-line py-20 lg:py-28 ${pad}`}>
          <Reveal className="flex flex-wrap items-end justify-between gap-4">
            <div>
              <p className="text-sm font-semibold text-stellar">How it works</p>
              <h2 className="font-semiwide mt-2 text-3xl font-bold sm:text-4xl">Four steps, every job.</h2>
            </div>
            <p className="max-w-md text-ink-3">The same flow whether it&apos;s a small leak or a full rewire. Pick a step or let it play.</p>
          </Reveal>
          <HowItWorks />
        </section>

        <section className={`border-t border-line py-20 lg:py-28 ${pad}`}>
          <Reveal className="flex flex-wrap items-end justify-between gap-6">
            <div className="max-w-xl">
              <h2 className="font-semiwide text-3xl font-bold sm:text-4xl">What do you need fixed?</h2>
              <p className="mt-4 leading-relaxed text-ink-2">
                Eight trades across Lagos, Abuja, Accra and Kumasi. Every professional shows their verification, rating and starting
                price before you message them.
              </p>
            </div>
            <Link
              href="/discover"
              className="group inline-flex h-12 items-center gap-2 rounded-lg bg-stellar px-6 font-semibold text-white transition-colors hover:bg-stellar-ink"
            >
              Browse all professionals
              <ArrowRight className="size-4 transition-transform group-hover:translate-x-1" aria-hidden />
            </Link>
          </Reveal>
          <TradeGrid />
        </section>

        <section className="border-t border-line bg-plaster">
          <div className={`grid items-center gap-12 py-20 lg:grid-cols-2 lg:gap-16 lg:py-28 ${pad}`}>
            <Reveal>
              <p className="text-sm font-semibold text-clay">Disputes</p>
              <h2 className="font-semiwide mt-2 text-3xl font-bold leading-tight sm:text-4xl">
                If the job isn&apos;t right, the money doesn&apos;t move.
              </h2>
              <p className="mt-5 max-w-xl text-lg leading-relaxed text-ink-2">
                Raise a dispute instead of approving. The escrow contract locks the funds so neither side can withdraw them. A UniFix
                resolver reviews the agreement, the chat and the completion photos, then authorises a release, a refund or a split.
              </p>
              <Safeguards />
            </Reveal>
            <DisputeDemo />
          </div>
        </section>

        <section id="pros" className={`grid items-center gap-12 border-t border-line py-20 lg:grid-cols-2 lg:gap-16 lg:py-28 ${pad}`}>
          <Reveal>
            <p className="text-sm font-semibold text-lagoon">For professionals</p>
            <h2 className="font-semiwide mt-2 text-3xl font-bold leading-tight sm:text-4xl">
              Start every job with the money already held.
            </h2>
            <p className="mt-4 max-w-xl text-lg leading-relaxed text-ink-2">
              Every booking is funded before you leave home. Send clear quotations, get paid to your Stellar wallet on approval, and
              build a rating from customers who paid for the work.
            </p>
            <div className="mt-8 flex flex-wrap items-center gap-4">
              <Link
                href="/sign-up?role=professional"
                className="group inline-flex h-12 items-center gap-2 rounded-lg bg-stellar px-6 font-semibold text-white transition-colors hover:bg-stellar-ink"
              >
                Join as a professional
                <ArrowRight className="size-4 transition-transform group-hover:translate-x-1" aria-hidden />
              </Link>
              <Link href="/sign-in" className="font-semibold text-ink-2 underline-offset-4 hover:underline">
                Sign in
              </Link>
            </div>
          </Reveal>
          <ProFeed />
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
