"use client";

import { useState } from "react";
import { AlertTriangle, BadgeCheck, Check, Copy, ExternalLink, Lock, RefreshCw, ShieldCheck, Wallet } from "lucide-react";
import { api, IS_DEMO } from "@/lib/api";
import { cn, shortAddress } from "@/lib/format";
import { explorerAccount, fundWithFriendbot, NETWORK, signOwnershipMessage } from "@/lib/stellar";
import { useSession, useToast, useWallet } from "@/components/providers";
import { Button, ErrorNote, LogoMark } from "@/components/ui";

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

  const usdcBal = w.balances?.find((b) => b.asset === "USDC")?.balance;
  const xlmBal = w.balances?.find((b) => b.asset === "XLM")?.balance;
  const fmt = (n?: number) => (n === undefined ? "–" : n.toLocaleString("en-US", { maximumFractionDigits: 2 }));

  const steps = [
    {
      t: "Install Freighter",
      d: "The Stellar wallet extension for Chrome, Brave and Firefox.",
      done: w.freighterAvailable === true || w.source === "freighter",
      href: "https://www.freighter.app/",
    },
    { t: "Switch it to Testnet", d: "Settings, then Network, then Testnet. The pilot uses test funds.", done: !!w.address && !w.wrongNetwork },
    { t: "Connect", d: "Approve the connection in Freighter.", done: !!w.address },
    { t: "Link to your account", d: "Sign a free message to prove the address is yours.", done: !!verified },
  ];
  const next = steps.findIndex((x) => !x.done);

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-semiwide text-3xl font-bold sm:text-4xl">Wallet</h1>
          <p className="mt-2 text-ink-2">
            {user?.role === "professional"
              ? "Released payments go straight to this Stellar address."
              : "You pay into escrow from this Stellar wallet. UniFix never sees your secret key."}
          </p>
        </div>
        {w.address && (
          <div className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              onClick={() => {
                navigator.clipboard.writeText(w.address!);
                toast({ title: "Address copied", tone: "info" });
              }}
            >
              <Copy className="size-4" aria-hidden /> Copy address
            </Button>
            {w.source === "freighter" && (
              <Button variant="outline" href={explorerAccount(w.address)}>
                <ExternalLink className="size-4" aria-hidden /> Stellar Expert
              </Button>
            )}
            <Button variant="ghost" onClick={w.disconnect}>
              Disconnect
            </Button>
          </div>
        )}
      </header>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
        {/* The wallet as a card: what is connected and what it holds */}
        <section className="flex flex-col gap-5">
          <div className="relative flex aspect-[1.7] max-h-80 w-full flex-col justify-between overflow-hidden rounded-3xl bg-ink p-6 text-white shadow-ticket sm:p-8">
            <LogoMark size={260} light className="pointer-events-none absolute -bottom-16 -right-10 opacity-10" />
            <div className="relative flex items-start justify-between gap-4">
              <span className="flex items-center gap-2 text-sm font-semibold">
                <Wallet className="size-5" aria-hidden />
                {w.address ? (w.source === "demo" ? "Demo wallet" : "Freighter") : "No wallet connected"}
              </span>
              <span
                className={cn(
                  "rounded-full px-2.5 py-1 text-xs font-semibold",
                  !w.address ? "bg-ink-2 text-mist" : w.wrongNetwork ? "bg-clay-soft text-clay-ink" : "bg-lagoon-soft text-lagoon-ink",
                )}
              >
                {!w.address ? NETWORK.label : w.wrongNetwork ? "Wrong network" : NETWORK.label}
              </span>
            </div>
            <div className="relative">
              <p className="text-sm text-mist">USDC balance</p>
              <p className="font-wide tnum mt-1 text-4xl font-bold sm:text-5xl">{w.address ? fmt(usdcBal) : "0.00"}</p>
              <p className="tnum mt-1 text-sm text-mist">{w.address ? `${fmt(xlmBal)} XLM for network fees` : "Connect to see balances"}</p>
            </div>
            <div className="relative flex items-end justify-between gap-4">
              <p className="tnum font-mono text-sm tracking-wider text-mist">{w.address ? shortAddress(w.address) : "G••••• ••••• •••••"}</p>
              {verified && (
                <span className="flex items-center gap-1.5 text-sm font-semibold text-lagoon-soft">
                  <BadgeCheck className="size-4" aria-hidden /> Verified
                </span>
              )}
            </div>
          </div>

          {!w.address ? (
            <div className="flex flex-wrap gap-2">
              <Button size="lg" onClick={() => w.connect()} loading={w.status === "connecting"} className="flex-1">
                Connect Freighter
              </Button>
              {IS_DEMO && (
                <Button size="lg" variant="outline" onClick={() => w.connectDemo()} className="flex-1">
                  Use demo wallet
                </Button>
              )}
            </div>
          ) : (
            <div className="rounded-2xl border border-line bg-paper p-5 shadow-xs">
              <div className="flex items-center justify-between">
                <h2 className="font-semibold">All balances</h2>
                <Button variant="ghost" size="sm" onClick={w.reloadBalances} aria-label="Refresh balances">
                  <RefreshCw className="size-4" />
                </Button>
              </div>
              {w.balances === null ? (
                <div className="mt-2">
                  <p className="text-ink-2">This account does not exist on testnet yet. Fund it with free test XLM to activate it.</p>
                  <Button variant="chain" size="sm" className="mt-3" onClick={friendbot} loading={busy === "friendbot"}>
                    Fund with Friendbot
                  </Button>
                </div>
              ) : w.balances?.length ? (
                <ul className="mt-3 divide-y divide-line">
                  {w.balances.map((b) => (
                    <li key={`${b.asset}${b.issuer ?? ""}`} className="flex items-center justify-between py-3">
                      <span className="font-semibold">{b.asset}</span>
                      <span className="tnum">{fmt(b.balance)}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="mt-2 text-sm text-ink-3">Could not load balances from Horizon.</p>
              )}
              {w.balances && usdcBal === undefined && (
                <p className="mt-3 text-sm text-ink-3">Add a USDC trustline in Freighter to receive and pay with testnet USDC.</p>
              )}
            </div>
          )}
          {w.error && <p className="text-sm text-clay-ink">{w.error}</p>}
          {w.wrongNetwork && (
            <p className="flex items-start gap-2 rounded-xl bg-clay-soft px-4 py-3 text-sm text-clay-ink">
              <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
              Freighter is on another network. Switch to Testnet in Freighter settings and reconnect.
            </p>
          )}
        </section>

        {/* Setup checklist, then the link step when it is next */}
        <section className="rounded-2xl border border-line bg-paper p-6 shadow-xs sm:p-8">
          <div className="flex items-baseline justify-between">
            <h2 className="text-lg font-semibold">Set up</h2>
            <span className="tnum text-sm text-ink-3">
              {steps.filter((x) => x.done).length} of {steps.length} done
            </span>
          </div>
          <ol className="mt-6 space-y-1">
            {steps.map((x, i) => {
              const current = i === next;
              return (
                <li key={x.t} className={cn("flex gap-4 rounded-xl p-3", current && "bg-stellar-soft")}>
                  <span
                    className={cn(
                      "tnum grid size-8 shrink-0 place-items-center rounded-full text-sm font-bold",
                      x.done ? "bg-lagoon text-white" : current ? "bg-stellar text-white" : "bg-plaster text-ink-3",
                    )}
                  >
                    {x.done ? <Check className="size-4" aria-hidden /> : i + 1}
                  </span>
                  <span className="min-w-0 pt-1">
                    <span className={cn("block font-semibold", !x.done && !current && "text-ink-2")}>
                      {x.href && !x.done ? (
                        <a href={x.href} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 hover:text-stellar">
                          {x.t} <ExternalLink className="size-3.5" aria-hidden />
                        </a>
                      ) : (
                        x.t
                      )}
                    </span>
                    <span className="mt-0.5 block text-sm leading-relaxed text-ink-3">{x.d}</span>
                    {current && i === 3 && (
                      <span className="mt-3 block">
                        <ErrorNote error={error} />
                        <Button className="mt-2" onClick={verify} loading={busy === "verify"} disabled={w.wrongNetwork}>
                          Sign and link wallet
                        </Button>
                      </span>
                    )}
                  </span>
                </li>
              );
            })}
          </ol>
          {verified && <ErrorNote error={error} />}
        </section>
      </div>

      <section className="grid gap-4 md:grid-cols-3">
        {[
          { Icon: Lock, t: "You fund escrow", d: "The agreed amount moves into a Soroban contract, not to UniFix or the professional." },
          { Icon: BadgeCheck, t: "You approve release", d: "The contract pays the professional only after you approve the finished job." },
          { Icon: ShieldCheck, t: "Your keys stay yours", d: "Freighter signs on your device. UniFix never sees your secret key." },
        ].map(({ Icon, t, d }) => (
          <div key={t} className="rounded-2xl border border-line bg-paper p-5 shadow-xs">
            <span className="grid size-10 place-items-center rounded-xl bg-plaster text-ink-2">
              <Icon className="size-5" aria-hidden />
            </span>
            <p className="mt-4 font-semibold">{t}</p>
            <p className="mt-1 text-sm leading-relaxed text-ink-3">{d}</p>
          </div>
        ))}
      </section>
    </div>
  );
}
