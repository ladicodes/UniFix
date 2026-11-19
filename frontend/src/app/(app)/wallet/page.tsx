"use client";

import { useState } from "react";
import { AlertTriangle, BadgeCheck, Copy, ExternalLink, Lock, RefreshCw, ShieldCheck, Wallet } from "lucide-react";
import { api, IS_DEMO } from "@/lib/api";
import { shortAddress } from "@/lib/format";
import { explorerAccount, fundWithFriendbot, NETWORK, signOwnershipMessage } from "@/lib/stellar";
import { useSession, useToast, useWallet } from "@/components/providers";
import { Badge, Button, ErrorNote } from "@/components/ui";

export default function WalletPage() {
  const w = useWallet();
  const { user, refresh } = useSession();
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const verified = user?.walletAddress === w.address && user?.walletVerified;

  async function verify() {
    if (!w.address) return;
    setBusy("verify");
    setError(null);
    try {
      const { message } = await api.walletChallenge(w.address);
      const sig = w.source === "freighter" ? await signOwnershipMessage(message, w.address) : "demo";
      await api.registerWallet(w.address, message, sig);
      await refresh();
      toast({ title: w.source === "freighter" ? "Wallet verified" : "Demo wallet linked", body: shortAddress(w.address), tone: "ok" });
    } catch (e) {
      setError(e);
    } finally {
      setBusy(null);
    }
  }

  async function friendbot() {
    if (!w.address) return;
    setBusy("friendbot");
    setError(null);
    try {
      await fundWithFriendbot(w.address);
      await w.reloadBalances();
      toast({ title: "Testnet XLM added", body: "Friendbot sent 10,000 test XLM.", tone: "ok" });
    } catch (e) {
      setError(e);
    } finally {
      setBusy(null);
    }
  }

  const STEPS = [
    { t: "Install Freighter", d: "The Stellar wallet extension for Chrome, Brave and Firefox.", href: "https://www.freighter.app/" },
    { t: "Switch it to Testnet", d: "Settings → Network → Testnet. Payments in this pilot use test funds." },
    { t: "Connect here", d: "Approve the connection in Freighter. Nothing moves without your signature." },
  ];

  return (
    <div>
      <header>
        <h1 className="font-semiwide text-3xl font-bold sm:text-4xl">Wallet</h1>
        <p className="mt-2 text-ink-2">
          {user?.role === "professional"
            ? "Released payments go straight to this Stellar address."
            : "You pay into escrow from this Stellar wallet. UniFix never sees your secret key."}
        </p>
      </header>

      <div className="mt-8 grid gap-6 xl:grid-cols-[minmax(0,1fr)_24rem]">
        {!w.address ? (
          <section className="overflow-hidden rounded-2xl border border-line bg-paper shadow-xs">
            <div className="flex flex-col gap-6 bg-ink p-6 text-white sm:flex-row sm:items-center sm:justify-between sm:p-8">
              <div className="flex items-center gap-4">
                <span className="grid size-12 shrink-0 place-items-center rounded-xl bg-ink-2">
                  <Wallet className="size-6" aria-hidden />
                </span>
                <div>
                  <h2 className="text-xl font-semibold">Connect a Stellar wallet</h2>
                  <p className="mt-1 text-sm text-mist">Freighter on {NETWORK.label}. You approve every transaction.</p>
                </div>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button variant="accent" onClick={() => w.connect()} loading={w.status === "connecting"}>
                  Connect Freighter
                </Button>
                {IS_DEMO && (
                  <Button variant="outline" onClick={() => w.connectDemo()} className="border-mist-2 bg-transparent text-white hover:bg-ink-2">
                    Use demo wallet
                  </Button>
                )}
              </div>
            </div>
            <ol className="grid divide-y divide-line sm:grid-cols-3 sm:divide-x sm:divide-y-0">
              {STEPS.map((x, i) => (
                <li key={x.t} className="p-6">
                  <span className="tnum grid size-8 place-items-center rounded-full bg-stellar-soft text-sm font-bold text-stellar-ink">{i + 1}</span>
                  <p className="mt-4 font-semibold">
                    {x.href ? (
                      <a href={x.href} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 hover:text-stellar">
                        {x.t} <ExternalLink className="size-3.5" aria-hidden />
                      </a>
                    ) : (
                      x.t
                    )}
                  </p>
                  <p className="mt-1 text-sm leading-relaxed text-ink-3">{x.d}</p>
                </li>
              ))}
            </ol>
            {(w.freighterAvailable === false || w.error) && (
              <p className="border-t border-line px-6 py-4 text-sm text-clay-ink">{w.error ?? "Freighter is not installed in this browser yet."}</p>
            )}
          </section>
        ) : (
          <div className="min-w-0 space-y-6">
            <section className="rounded-2xl border border-line bg-paper p-6 shadow-xs sm:p-8">
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone={w.source === "demo" ? "neutral" : "stellar"}>{w.source === "demo" ? "Demo wallet" : "Freighter"}</Badge>
                {w.wrongNetwork ? <Badge tone="clay">Wrong network</Badge> : <Badge tone="lagoon">{NETWORK.label}</Badge>}
                {verified && (
                  <Badge tone="lagoon">
                    <BadgeCheck className="size-3.5" aria-hidden /> Ownership verified
                  </Badge>
                )}
              </div>
              <p className="mt-5 text-sm text-ink-3">Address</p>
              <p className="tnum mt-1 break-all rounded-xl bg-plaster px-4 py-3 font-mono text-sm font-semibold leading-relaxed">{w.address}</p>
              <div className="mt-4 flex flex-wrap gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    navigator.clipboard.writeText(w.address!);
                    toast({ title: "Address copied", tone: "info" });
                  }}
                >
                  <Copy className="size-4" aria-hidden /> Copy
                </Button>
                {w.source === "freighter" && (
                  <Button variant="outline" size="sm" href={explorerAccount(w.address)}>
                    <ExternalLink className="size-4" aria-hidden /> Stellar Expert
                  </Button>
                )}
                <Button variant="ghost" size="sm" onClick={w.disconnect}>
                  Disconnect
                </Button>
              </div>
              {w.wrongNetwork && (
                <p className="mt-4 flex items-start gap-2 rounded-lg bg-clay-soft px-4 py-3 text-sm text-clay-ink">
                  <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
                  Freighter is on another network. Switch to Testnet in Freighter settings and reconnect.
                </p>
              )}
            </section>

            <section className="rounded-2xl border border-line bg-paper shadow-xs">
              <div className="flex items-center justify-between border-b border-line px-6 py-4">
                <h2 className="font-semibold">Balances</h2>
                <Button variant="ghost" size="sm" onClick={w.reloadBalances} aria-label="Refresh balances">
                  <RefreshCw className="size-4" />
                </Button>
              </div>
              <div className="p-6">
                {w.balances === null ? (
                  <div>
                    <p className="text-ink-2">This account does not exist on testnet yet. Fund it with free test XLM to activate it.</p>
                    <Button variant="chain" size="sm" className="mt-3" onClick={friendbot} loading={busy === "friendbot"}>
                      Fund with Friendbot
                    </Button>
                  </div>
                ) : w.balances?.length ? (
                  <ul className="grid gap-3 sm:grid-cols-2">
                    {w.balances.map((b) => (
                      <li key={`${b.asset}${b.issuer ?? ""}`} className="rounded-xl border border-line p-4">
                        <p className="text-sm font-semibold text-ink-3">{b.asset}</p>
                        <p className="font-wide tnum mt-1 text-2xl font-bold">{b.balance.toLocaleString("en-US", { maximumFractionDigits: 2 })}</p>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-sm text-ink-3">Could not load balances from Horizon.</p>
                )}
                {w.balances && !w.balances.some((b) => b.asset === "USDC") && (
                  <p className="mt-4 text-sm text-ink-3">Add a USDC trustline in Freighter to receive and pay with testnet USDC.</p>
                )}
              </div>
            </section>
          </div>
        )}

        <aside className="space-y-6">
          {w.address && !verified && (
            <section className="rounded-2xl border border-stellar bg-paper p-6 shadow-xs ring-4 ring-stellar-soft">
              <h2 className="text-lg font-semibold">Link this wallet</h2>
              <p className="mt-2 text-sm leading-relaxed text-ink-2">
                Sign a short message to prove you own the address. It costs nothing and does not move any funds.
              </p>
              <ErrorNote error={error} />
              <Button className="mt-4 w-full" onClick={verify} loading={busy === "verify"} disabled={w.wrongNetwork}>
                Sign and link wallet
              </Button>
            </section>
          )}
          {verified && <ErrorNote error={error} />}
          <section className="rounded-2xl border border-line bg-paper p-6 shadow-xs">
            <h2 className="font-semibold">How UniFix uses your wallet</h2>
            <ul className="mt-4 space-y-4 text-sm">
              {[
                { Icon: Lock, t: "You fund escrow", d: "The agreed amount moves into a Soroban contract, not to UniFix or the professional." },
                { Icon: BadgeCheck, t: "You approve release", d: "The contract pays the professional only after you approve the finished job." },
                { Icon: ShieldCheck, t: "Your keys stay yours", d: "Freighter signs on your device. UniFix never sees your secret key." },
              ].map(({ Icon, t, d }) => (
                <li key={t} className="flex gap-3">
                  <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-plaster text-ink-2">
                    <Icon className="size-4" aria-hidden />
                  </span>
                  <span>
                    <span className="block font-semibold">{t}</span>
                    <span className="mt-0.5 block leading-relaxed text-ink-3">{d}</span>
                  </span>
                </li>
              ))}
            </ul>
          </section>
        </aside>
      </div>
    </div>
  );
}
