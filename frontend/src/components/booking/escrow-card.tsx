"use client";

import { ExternalLink, Loader2 } from "lucide-react";
import { cn, dateTime, money, shortAddress, shortHash, usdc } from "@/lib/format";
import { explorerContract, explorerTx, NETWORK } from "@/lib/stellar";
import type { Escrow } from "@/lib/types";
import { EscrowBadge, RECONCILIATION } from "../status";
import { Badge } from "../ui";

const TX_LABEL = { FUND: "Funding", RELEASE: "Release", REFUND: "Refund" };

export function TxLink({ hash, simulated }: { hash: string; simulated?: boolean }) {
  if (simulated) return <span className="tnum font-semibold text-ink-2">{shortHash(hash)}</span>;
  return (
    <a href={explorerTx(hash)} target="_blank" rel="noreferrer" className="tnum inline-flex items-center gap-1 font-semibold text-stellar hover:underline">
      {shortHash(hash)}
      <ExternalLink className="size-3.5" aria-hidden />
      <span className="sr-only">(opens Stellar Expert)</span>
    </a>
  );
}

export function EscrowCard({ escrow }: { escrow: Escrow }) {
  const pending = escrow.reconciliation === "PENDING_CONFIRMATION";
  const simulated = escrow.transactions.some((t) => t.simulated);
  return (
    <section className="border-t border-line pt-2">
      <div className="flex items-center justify-between gap-3 py-3">
        <h2 className="font-semibold">Escrow on Stellar</h2>
        <EscrowBadge state={escrow.state} />
      </div>
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-3 py-3 text-sm">
        <dt className="text-ink-3">Amount</dt>
        <dd className="tnum text-right font-semibold">{usdc(escrow.amount)}</dd>
        <dt className="text-ink-3">Agreed price</dt>
        <dd className="tnum text-right">{money(escrow.localAmount, escrow.currency)}</dd>
        <dt className="text-ink-3">Rate used</dt>
        <dd className="tnum text-right">
          {money(escrow.rate, escrow.currency)} per USDC
        </dd>
        <dt className="text-ink-3">Network</dt>
        <dd className="text-right">{NETWORK.label}</dd>
        <dt className="text-ink-3">Contract</dt>
        <dd className="text-right">
          {simulated ? (
            <span className="tnum">{shortAddress(escrow.contractId)}</span>
          ) : (
            <a href={explorerContract(escrow.contractId)} target="_blank" rel="noreferrer" className="tnum font-semibold text-stellar hover:underline">
              {shortAddress(escrow.contractId)}
            </a>
          )}
        </dd>
        {escrow.customerWallet && (
          <>
            <dt className="text-ink-3">Paid from</dt>
            <dd className="tnum text-right">{shortAddress(escrow.customerWallet)}</dd>
          </>
        )}
        {escrow.professionalWallet && (
          <>
            <dt className="text-ink-3">Pays to</dt>
            <dd className="tnum text-right">{shortAddress(escrow.professionalWallet)}</dd>
          </>
        )}
      </dl>
      <div className={cn("flex items-center gap-2 border-t border-line py-3 text-sm", pending ? "text-stellar-ink" : "text-ink-2")}>
        {pending && <Loader2 className="size-4 animate-spin" aria-hidden />}
        <span className="font-semibold">{RECONCILIATION[escrow.reconciliation]}</span>
      </div>
      {escrow.transactions.length > 0 && (
        <ul className="divide-y divide-line border-t border-line">
          {escrow.transactions.map((t) => (
            <li key={t.hash} className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 py-3 text-sm">
              <span>
                <span className="font-semibold">{TX_LABEL[t.kind]}</span>
                <span className="ml-2 text-ink-3">{dateTime(t.at)}</span>
              </span>
              <span className="flex items-center gap-2">
                {t.status === "PENDING" ? <Badge tone="stellar">Pending</Badge> : t.status === "FAILED" ? <Badge tone="clay">Failed</Badge> : t.ledger ? <span className="tnum text-xs text-ink-3">Ledger {t.ledger.toLocaleString()}</span> : null}
                <TxLink hash={t.hash} simulated={t.simulated} />
              </span>
            </li>
          ))}
        </ul>
      )}
      {simulated && <p className="border-t border-line py-3 text-xs text-ink-3">Demo transactions are simulated and do not appear on Stellar Expert.</p>}
    </section>
  );
}
