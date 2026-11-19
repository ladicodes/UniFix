import Link from "next/link";
import { Lock } from "lucide-react";
import { Logo } from "./ui";

const COLUMNS = [
  {
    title: "Product",
    links: [
      { href: "/#how", label: "How it works" },
      { href: "/#services", label: "Services" },
      { href: "/discover", label: "Find professionals" },
      { href: "/#safety", label: "Disputes" },
    ],
  },
  {
    title: "Professionals",
    links: [
      { href: "/sign-up?role=professional", label: "Join as a professional" },
      { href: "/#pros", label: "How you get paid" },
      { href: "/sign-in", label: "Sign in" },
    ],
  },
  {
    title: "Legal",
    links: [
      { href: "/terms", label: "Terms and conditions" },
      { href: "/privacy", label: "Privacy policy" },
    ],
  },
];

export function SiteFooter() {
  return (
    <footer className="border-t border-line bg-paper">
      <div className="grid gap-10 px-4 py-14 sm:px-6 lg:grid-cols-[minmax(0,1.4fr)_repeat(3,minmax(0,1fr))] lg:px-10">
        <div className="max-w-sm">
          <Logo />
          <p className="mt-4 leading-relaxed text-ink-2">
            Hire verified professionals in Nigeria and Ghana. Agree on a price, hold the payment in escrow, and release it when the job is done.
          </p>
          <p className="mt-5 inline-flex items-center gap-2 rounded-full bg-danfo-soft px-3 py-1.5 text-sm font-semibold text-danfo-ink">
            <Lock className="size-4" aria-hidden />
            Payments held in a Soroban escrow contract
          </p>
        </div>
        {COLUMNS.map((c) => (
          <nav key={c.title} aria-label={c.title}>
            <p className="text-sm font-semibold text-ink">{c.title}</p>
            <ul className="mt-4 space-y-3">
              {c.links.map((l) => (
                <li key={l.href}>
                  <Link href={l.href} className="text-ink-2 transition-colors hover:text-stellar">
                    {l.label}
                  </Link>
                </li>
              ))}
            </ul>
          </nav>
        ))}
      </div>
      <div className="flex flex-col gap-2 border-t border-line px-4 py-6 text-sm text-ink-3 sm:flex-row sm:items-center sm:justify-between sm:px-6 lg:px-10">
        <p>© 2026 UniFix. Built for the Stellar Buildathon.</p>
        <p>Pilot: payments run on Stellar testnet with test funds.</p>
      </div>
    </footer>
  );
}
