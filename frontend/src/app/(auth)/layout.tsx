import Link from "next/link";
import { Logo } from "@/components/ui";

const FLOW = [
  "You agree a price with the professional in chat.",
  "Your payment is held in a Stellar escrow contract.",
  "It is released only when you approve the work.",
];

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid min-h-dvh bg-paper lg:grid-cols-[1fr_minmax(0,480px)]">
      <div className="flex flex-col px-4 py-6 sm:px-10">
        <Link href="/" aria-label="Handi home" className="self-start">
          <Logo />
        </Link>
        <div className="flex flex-1 items-center py-10">
          <div className="mx-auto w-full max-w-md">{children}</div>
        </div>
      </div>
      <aside className="hidden border-l border-line bg-plaster p-12 lg:flex lg:flex-col lg:justify-end">
        <p className="text-sm font-semibold text-ink-3">How payment works on Handi</p>
        <ol className="mt-4 space-y-4">
          {FLOW.map((f, i) => (
            <li key={f} className="flex gap-4">
              <span className="tnum font-semibold text-ink-3">{i + 1}</span>
              <span className="text-lg leading-snug">{f}</span>
            </li>
          ))}
        </ol>
      </aside>
    </div>
  );
}
