"use client";

import { Printer } from "lucide-react";
import { dateTime, money, shortAddress, usdc } from "@/lib/format";
import { NETWORK } from "@/lib/stellar";
import type { BookingBundle } from "@/lib/types";
import { TxLink } from "./escrow-card";
import { Button } from "../ui";

export function Receipt({ b }: { b: BookingBundle }) {
  const e = b.escrow;
  if (!e) return null;
  const release = e.transactions.find((t) => t.kind === "RELEASE" && t.status === "CONFIRMED");
  const fund = e.transactions.find((t) => t.kind === "FUND");
  return (
    <div className="print:text-black">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold">Payment receipt</h2>
          <p className="mt-1 text-sm text-ink-3">Booking {b.booking.id}</p>
        </div>
        <Button variant="outline" size="sm" onClick={() => window.print()} className="print:hidden">
          <Printer className="size-4" aria-hidden /> Print
        </Button>
      </div>
      <dl className="mt-5 grid gap-x-6 gap-y-3 text-sm sm:grid-cols-[auto_1fr]">
        <dt className="text-ink-3">Service</dt>
        <dd>{b.booking.title}</dd>
        <dt className="text-ink-3">Professional</dt>
        <dd>{b.professional.name}</dd>
        <dt className="text-ink-3">Customer</dt>
        <dd>{b.customer.name}</dd>
        <dt className="text-ink-3">Agreed price</dt>
        <dd className="tnum">{money(b.quote.total, b.quote.currency)}</dd>
        <dt className="text-ink-3">Settled on-chain</dt>
        <dd className="font-wide tnum text-lg font-bold">{usdc(e.amount)}</dd>
        <dt className="text-ink-3">Network</dt>
        <dd>{NETWORK.label}</dd>
        {e.professionalWallet && (
          <>
            <dt className="text-ink-3">Paid to wallet</dt>
            <dd className="tnum">{shortAddress(e.professionalWallet)}</dd>
          </>
        )}
        {fund && (
          <>
            <dt className="text-ink-3">Funding transaction</dt>
            <dd>
              <TxLink hash={fund.hash} simulated={fund.simulated} />
            </dd>
          </>
        )}
        {release && (
          <>
            <dt className="text-ink-3">Release transaction</dt>
            <dd>
              <TxLink hash={release.hash} simulated={release.simulated} /> <span className="text-ink-3">{dateTime(release.at)}</span>
            </dd>
          </>
        )}
      </dl>
    </div>
  );
}
