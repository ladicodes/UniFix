"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { CalendarDays, Lock } from "lucide-react";
import { api } from "@/lib/api";
import { cn, money, shortDate, shortHash, toUsdc, usdc, RATES } from "@/lib/format";
import type { Quote } from "@/lib/types";
import { useToast } from "./providers";
import { Badge, Button, Dialog, ErrorNote } from "./ui";

export const QUOTE_STATUS: Record<Quote["status"], { label: string; tone: "neutral" | "stellar" | "lagoon" | "clay" }> = {
  PENDING: { label: "Waiting for your answer", tone: "stellar" },
  ACCEPTED: { label: "Accepted and locked", tone: "lagoon" },
  REJECTED: { label: "Declined", tone: "neutral" },
  SUPERSEDED: { label: "Replaced by a newer version", tone: "neutral" },
};

export function quoteStatus(quote: Quote, viewerIsCustomer: boolean) {
  return quote.status === "PENDING" && !viewerIsCustomer ? { label: "Sent, waiting for customer", tone: "stellar" as const } : QUOTE_STATUS[quote.status];
}

export function QuoteCard({
  quote,
  viewerIsCustomer,
  bookingId,
  bare,
}: {
  quote: Quote;
  viewerIsCustomer: boolean;
  bookingId?: string;
  /** Without its own frame, for use inside a panel or dialog. */
  bare?: boolean;
}) {
  const router = useRouter();
  const toast = useToast();
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState<"accept" | "reject" | null>(null);
  const [error, setError] = useState<unknown>(null);
  const inactive = quote.status === "SUPERSEDED" || quote.status === "REJECTED";
  const status = quoteStatus(quote, viewerIsCustomer);

  async function accept() {
    setBusy("accept");
    setError(null);
    try {
      const b = await api.acceptQuote(quote.id);
      toast({ title: "Quotation accepted", body: "The agreement is locked. Fund the escrow to confirm the booking.", tone: "ok" });
      router.push(`/bookings/${b.id}`);
    } catch (e) {
      setError(e);
      setBusy(null);
    }
  }
  async function reject() {
    setBusy("reject");
    try {
      await api.rejectQuote(quote.id);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className={cn("w-full bg-paper", !bare && "max-w-md overflow-hidden rounded-2xl border border-line", inactive && "opacity-60")}>
      <div className={cn("flex items-center justify-between gap-3", bare ? "pb-3" : "border-b border-line px-4 py-3")}>
        <span className="text-sm font-semibold text-ink-3">Version {quote.version}</span>
        <Badge tone={status.tone}>{status.label}</Badge>
      </div>
      <div className={bare ? "" : "p-4"}>
        <h4 className="font-semibold leading-snug">{quote.title}</h4>
        <p className="mt-2 text-sm leading-relaxed text-ink-2">{quote.description}</p>
        <dl className="mt-4 grid grid-cols-[1fr_auto] gap-y-2 text-sm">
          <dt className="text-ink-3">Labour</dt>
          <dd className="tnum text-right">{money(quote.labour, quote.currency)}</dd>
          <dt className="text-ink-3">Materials</dt>
          <dd className="tnum text-right">{money(quote.materials, quote.currency)}</dd>
          <dt className="mt-2 border-t border-line pt-2 font-semibold">Total</dt>
          <dd className="font-wide tnum mt-2 border-t border-line pt-2 text-right text-lg font-bold">{money(quote.total, quote.currency)}</dd>
          <dt className="text-ink-3">Paid into escrow as</dt>
          <dd className="tnum text-right font-semibold text-stellar">{usdc(toUsdc(quote.total, quote.currency))}</dd>
        </dl>
        {quote.milestones.length > 0 && (
          <div className="mt-4">
            <p className="text-sm font-semibold">Milestones</p>
            <ol className="mt-2 space-y-1 text-sm">
              {quote.milestones.map((m, i) => (
                <li key={i} className="flex justify-between gap-3">
                  <span className="text-ink-2">
                    {i + 1}. {m.title}
                  </span>
                  <span className="tnum font-semibold">{m.percent}%</span>
                </li>
              ))}
            </ol>
          </div>
        )}
        <p className="mt-4 flex items-center gap-2 text-sm text-ink-2">
          <CalendarDays className="size-4 text-ink-3" aria-hidden />
          Done by {shortDate(quote.completionDate)}
        </p>
        <p className="mt-2 text-sm text-ink-3">{quote.paymentTerms}</p>
        {quote.agreementHash && (
          <p className="mt-3 flex items-center gap-2 text-xs text-ink-3">
            <Lock className="size-3.5" aria-hidden />
            Agreement fingerprint <span className="tnum font-semibold text-ink-2">{shortHash(quote.agreementHash)}</span>
          </p>
        )}

        {quote.status === "PENDING" && viewerIsCustomer && (
          <div className="mt-4 flex gap-2">
            <Button variant="accent" className="flex-1" onClick={() => setConfirm(true)}>
              Accept quotation
            </Button>
            <Button variant="outline" onClick={reject} loading={busy === "reject"}>
              Decline
            </Button>
          </div>
        )}
        {quote.status === "ACCEPTED" && bookingId && (
          <Button href={`/bookings/${bookingId}`} variant="outline" className="mt-4 w-full">
            Open booking
          </Button>
        )}
        {!confirm && <div className="mt-2"><ErrorNote error={error} /></div>}
      </div>

      <Dialog open={confirm} onClose={() => setConfirm(false)} title="Accept this quotation?">
        <ul className="space-y-3 text-base leading-relaxed text-ink-2">
          <li>
            The price of <strong className="text-ink">{money(quote.total, quote.currency)}</strong> and the scope above are locked. Any change needs a new
            quotation that you accept again.
          </li>
          <li>
            Next you fund <strong className="text-ink">{usdc(toUsdc(quote.total, quote.currency))}</strong> into the escrow contract at an indicative rate of{" "}
            {money(RATES[quote.currency], quote.currency)} per USDC.
          </li>
          <li>The money stays in escrow until you approve the finished job or a dispute is resolved.</li>
        </ul>
        <ErrorNote error={error} />
        <div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button variant="ghost" onClick={() => setConfirm(false)}>
            Not yet
          </Button>
          <Button variant="accent" onClick={accept} loading={busy === "accept"}>
            Accept and lock agreement
          </Button>
        </div>
        <p className="mt-4 text-xs text-ink-3">
          <Link href="/#how" className="underline">
            How escrow works
          </Link>
        </p>
      </Dialog>
    </div>
  );
}
