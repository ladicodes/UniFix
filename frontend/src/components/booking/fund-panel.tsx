"use client";

import Link from "next/link";
import { useState } from "react";
import { AlertTriangle, Check, Lock, Wallet } from "lucide-react";
import { api, IS_DEMO } from "@/lib/api";
import { cn, money, NETWORK_FEE_XLM, RATES, shortAddress, toUsdc, usdc } from "@/lib/format";
import { NETWORK, signXdr } from "@/lib/stellar";
import type { BookingBundle } from "@/lib/types";
import { useToast, useWallet } from "../providers";
import { Button, ErrorNote } from "../ui";

function Step({ n, title, done, active, children }: { n: number; title: string; done?: boolean; active?: boolean; children?: React.ReactNode }) {
  return (
    <li className="relative flex gap-4 pb-8 last:pb-0">
      <span
        className={cn(
          "tnum relative z-10 grid size-8 shrink-0 place-items-center rounded-full text-sm font-semibold",
          done ? "bg-lagoon text-white" : active ? "bg-stellar text-white" : "bg-paper text-ink-3 ring-1 ring-line",
        )}
      >
        {done ? <Check className="size-4" aria-hidden /> : n}
      </span>
      <div className="min-w-0 flex-1 pt-1">
        <p className={cn("font-semibold", !active && !done && "text-ink-3")}>{title}</p>
        {children && <div className="mt-3">{children}</div>}
      </div>
    </li>
  );
}

export function FundPanel({ b }: { b: BookingBundle }) {
  const w = useWallet();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [ack, setAck] = useState(false);
  const escrow = b.escrow;
  const pending = escrow?.reconciliation === "PENDING_CONFIRMATION";
  const amountUsdc = escrow?.amount ?? toUsdc(b.quote.total, b.quote.currency);
  const usdcBal = w.balances?.find((x) => x.asset === "USDC")?.balance;
  const short = usdcBal !== undefined && usdcBal < amountUsdc;

  async function fund() {
    if (!w.address) return;
    setBusy(true);
    setError(null);
    try {
      const prepared = await api.prepareEscrow(b.booking.id, w.address);
      if (prepared.unsignedXdr) {
        if (w.source !== "freighter") throw new Error("Connect Freighter to sign this payment.");
        const signed = await signXdr(prepared.unsignedXdr, w.address);
        await api.submitFunding(prepared.escrow.id, signed);
      } else {
        await api.submitFunding(prepared.escrow.id);
      }
      toast({ title: "Payment submitted", body: "Waiting for Stellar to confirm the escrow funding.", tone: "info" });
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  if (pending) {
    return (
      <div className="flex items-start gap-4">
        <span className="relative mt-1 grid size-10 shrink-0 place-items-center rounded-full bg-danfo">
          <Lock className="size-5 text-ink" aria-hidden />
          <span className="hidden" />
        </span>
        <div>
          <p className="text-lg font-semibold">Confirming your payment on Stellar</p>
          <p className="mt-1 text-ink-2">
            UniFix checks the escrow contract directly. The booking moves to funded only after the ledger confirms it, usually within
            10 seconds. You can leave this page.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div>
      <p className="text-lg font-semibold">Fund the escrow to confirm this booking</p>
      <p className="mt-1 text-ink-2">
        {b.professional.name.split(" ")[0]} starts once the money is held. It is released only when you approve the work.
      </p>

      <ol className="relative mt-6 before:absolute before:bottom-4 before:left-4 before:top-4 before:w-px before:bg-line-2">
        <Step n={1} title={w.address ? `Wallet connected: ${shortAddress(w.address)}` : "Connect a Stellar wallet"} done={!!w.address && !w.wrongNetwork} active={!w.address || w.wrongNetwork}>
          {!w.address ? (
            <div className="flex flex-wrap gap-2">
              <Button variant="chain" onClick={() => w.connect()} loading={w.status === "connecting"}>
                <Wallet className="size-4" aria-hidden />
                Connect Freighter
              </Button>
              {IS_DEMO && (
                <Button variant="outline" onClick={() => w.connectDemo()}>
                  Use demo wallet
                </Button>
              )}
              {w.freighterAvailable === false && (
                <p className="w-full text-sm text-ink-3">
                  Freighter not detected.{" "}
                  <a href="https://www.freighter.app/" target="_blank" rel="noreferrer" className="font-semibold text-stellar hover:underline">
                    Install Freighter
                  </a>{" "}
                  and switch it to Testnet.
                </p>
              )}
              {w.error && <p className="w-full text-sm text-clay">{w.error}</p>}
            </div>
          ) : w.wrongNetwork ? (
            <p className="flex items-start gap-2 rounded-lg bg-clay-soft px-3 py-3 text-sm text-clay-ink">
              <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
              Your wallet is not on {NETWORK.label}. Switch networks in Freighter, then reconnect.
            </p>
          ) : null}
        </Step>

        <Step n={2} title="Check what you are paying" active={!!w.address && !w.wrongNetwork}>
          {w.address && !w.wrongNetwork && (
            <div className="overflow-hidden rounded-lg bg-paper">
              <dl className="grid grid-cols-[1fr_auto] gap-y-2 p-4 text-sm">
                <dt className="text-ink-3">Agreed price</dt>
                <dd className="tnum text-right">{money(b.quote.total, b.quote.currency)}</dd>
                <dt className="text-ink-3">Indicative rate</dt>
                <dd className="tnum text-right">{money(RATES[b.quote.currency], b.quote.currency)} per USDC</dd>
                <dt className="text-ink-3">Network fee</dt>
                <dd className="tnum text-right">about {NETWORK_FEE_XLM} XLM</dd>
                <dt className="text-ink-3">UniFix fee</dt>
                <dd className="tnum text-right">None during the pilot</dd>
                <dt className="mt-1 border-t border-line pt-3 font-semibold">You send to escrow</dt>
                <dd className="font-wide tnum mt-1 border-t border-line pt-3 text-right text-xl font-bold">{usdc(amountUsdc)}</dd>
              </dl>
              <div className="border-t border-line px-4 py-3 text-sm text-ink-2">
                Asset USDC on {NETWORK.label}. Your wallet shows this same amount before you sign.
              </div>
            </div>
          )}
          {short && (
            <p className="mt-3 text-sm text-clay">
              Your wallet has {usdc(usdcBal!)}. Add USDC before funding.{" "}
              <Link href="/wallet" className="font-semibold underline">
                Open wallet
              </Link>
            </p>
          )}
        </Step>

        <Step n={3} title="Sign and send" active={!!w.address && !w.wrongNetwork}>
          {w.address && !w.wrongNetwork && (
            <div className="space-y-3">
              <label className="flex cursor-pointer items-start gap-3 text-sm">
                <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} className="mt-0.5 size-5 shrink-0 accent-ink" />
                <span className="text-ink-2">
                  I understand the funds stay locked in the contract until I approve the work, or a dispute is resolved.
                </span>
              </label>
              <ErrorNote error={error} />
              <Button variant="accent" size="lg" onClick={fund} loading={busy} disabled={!ack} className="w-full sm:w-auto">
                <Lock className="size-5" aria-hidden />
                Fund {usdc(amountUsdc)}
              </Button>
              {IS_DEMO && <p className="text-xs text-ink-3">Demo mode simulates the transaction. With the live backend, Freighter asks you to sign a real testnet transaction.</p>}
            </div>
          )}
        </Step>
      </ol>
    </div>
  );
}
