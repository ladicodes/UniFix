"use client";

import { useState } from "react";
import { AlertTriangle, BadgeCheck, Copy, ExternalLink, RefreshCw, Wallet } from "lucide-react";
import { api, IS_DEMO } from "@/lib/api";
import { shortAddress } from "@/lib/format";
import { explorerAccount, fundWithFriendbot, NETWORK, signOwnershipMessage } from "@/lib/stellar";
import { useSession, useToast, useWallet } from "@/components/providers";
import { Badge, Button, ErrorNote, Surface } from "@/components/ui";

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

  return (
    <div className="w-full">
      <h1 className="font-semiwide text-3xl font-bold">Wallet</h1>
      <p className="mt-2 text-ink-2">
        {user?.role === "professional"
          ? "Released payments go straight to this Stellar address."
          : "You pay into escrow from this Stellar wallet. UniFix never sees your secret key."}
      </p>

      {!w.address ? (
        <Surface className="mt-8 p-6 sm:p-8">
          <span className="grid size-12 place-items-center rounded-2xl bg-stellar-soft">
            <Wallet className="size-6 text-stellar" aria-hidden />
          </span>
          <h2 className="mt-5 text-xl font-semibold">Connect a Stellar wallet</h2>
          <p className="mt-2 max-w-prose text-ink-2">
            UniFix works with Freighter on {NETWORK.label}. You approve every transaction in the wallet and see the asset and amount
            before signing.
          </p>
          <div className="mt-6 flex flex-wrap gap-2">
            <Button variant="chain" size="lg" onClick={() => w.connect()} loading={w.status === "connecting"}>
              Connect Freighter
            </Button>
            {IS_DEMO && (
              <Button variant="outline" size="lg" onClick={() => w.connectDemo()}>
                Use demo wallet
              </Button>
            )}
          </div>
          {w.freighterAvailable === false && (
            <p className="mt-4 text-sm text-ink-3">
              Freighter is not installed.{" "}
              <a className="font-semibold text-stellar hover:underline" href="https://www.freighter.app/" target="_blank" rel="noreferrer">
                Get Freighter
              </a>
              , create an account, and switch the network to Testnet.
            </p>
          )}
          {w.error && <p className="mt-4 text-sm text-clay">{w.error}</p>}
        </Surface>
      ) : (
        <>
          <section className="mt-8">
            <div className="pb-8">
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone={w.source === "demo" ? "neutral" : "stellar"}>{w.source === "demo" ? "Demo wallet" : "Freighter"}</Badge>
                {w.wrongNetwork ? <Badge tone="clay">Wrong network</Badge> : <Badge tone="lagoon">{NETWORK.label}</Badge>}
                {verified && (
                  <Badge tone="lagoon">
                    <BadgeCheck className="size-3.5" aria-hidden /> Ownership verified
                  </Badge>
                )}
              </div>
              <p className="tnum mt-4 break-all text-lg font-semibold leading-snug">{w.address}</p>
              <div className="mt-3 flex flex-wrap gap-2">
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
            </div>

            <div className="border-t border-line pt-6">
              <div className="flex items-center justify-between">
                <h2 className="font-semibold">Balances</h2>
                <Button variant="ghost" size="sm" onClick={w.reloadBalances} aria-label="Refresh balances">
                  <RefreshCw className="size-4" />
                </Button>
              </div>
              {w.balances === null ? (
                <div className="mt-3">
                  <p className="text-sm text-ink-2">This account does not exist on testnet yet. Fund it with free test XLM to activate it.</p>
                  <Button variant="chain" size="sm" className="mt-3" onClick={friendbot} loading={busy === "friendbot"}>
                    Fund with Friendbot
                  </Button>
                </div>
              ) : w.balances?.length ? (
                <ul className="mt-3 grid gap-2 sm:grid-cols-2">
                  {w.balances.map((b) => (
                    <li key={`${b.asset}${b.issuer ?? ""}`}>
                      <p className="text-sm text-ink-3">{b.asset}</p>
                      <p className="font-wide tnum text-xl font-bold">{b.balance.toLocaleString("en-US", { maximumFractionDigits: 2 })}</p>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="mt-3 text-sm text-ink-3">Could not load balances from Horizon.</p>
              )}
              {w.balances && !w.balances.some((b) => b.asset === "USDC") && (
                <p className="mt-3 text-sm text-ink-3">Add a USDC trustline in Freighter to receive and pay with testnet USDC.</p>
              )}
            </div>
          </section>

          {!verified && (
            <Surface className="mt-10 p-6 sm:p-8">
              <h2 className="text-lg font-semibold">Link this wallet to your UniFix account</h2>
              <p className="mt-2 text-ink-2">
                You sign a short message to prove you own the address. It costs nothing and does not move any funds.
              </p>
              <ErrorNote error={error} />
              <Button className="mt-4" onClick={verify} loading={busy === "verify"} disabled={w.wrongNetwork}>
                Sign and link wallet
              </Button>
            </Surface>
          )}
          {verified && <ErrorNote error={error} />}
        </>
      )}
    </div>
  );
}
