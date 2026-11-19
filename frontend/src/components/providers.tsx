"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { QueryClient, QueryClientProvider, useQueryClient } from "@tanstack/react-query";
import { api, IS_DEMO } from "@/lib/api";
import type { User } from "@/lib/types";
import { connectFreighter, fetchBalances, hasFreighter, NETWORK, onRightNetwork, type Balance } from "@/lib/stellar";
import { useGlobalLive } from "@/lib/hooks";

/* ---------------- session ---------------- */

interface SessionCtx {
  user: User | null;
  ready: boolean;
  refresh: () => Promise<void>;
  signOut: () => Promise<void>;
}

const Session = createContext<SessionCtx>({ user: null, ready: false, refresh: async () => {}, signOut: async () => {} });
export const useSession = () => useContext(Session);

function SessionProvider({ children }: { children: React.ReactNode }) {
  const qc = useQueryClient();
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);
  useGlobalLive();

  const refresh = useCallback(async () => {
    try {
      setUser(await api.me());
    } finally {
      setReady(true);
    }
  }, []);

  useEffect(() => {
    refresh();
    return api.subscribe("*", refresh);
  }, [refresh]);

  const signOut = useCallback(async () => {
    await api.signOut();
    setUser(null);
    qc.clear();
  }, [qc]);

  return <Session.Provider value={{ user, ready, refresh, signOut }}>{children}</Session.Provider>;
}

/* ---------------- wallet ---------------- */

type WalletStatus = "idle" | "connecting" | "connected" | "error";

interface WalletCtx {
  status: WalletStatus;
  address: string | null;
  passphrase: string | null;
  source: "freighter" | "demo" | null;
  error: string | null;
  freighterAvailable: boolean | null;
  wrongNetwork: boolean;
  balances: Balance[] | null | undefined;
  connect: () => Promise<string | null>;
  connectDemo: () => string;
  disconnect: () => void;
  reloadBalances: () => Promise<void>;
}

const Wallet = createContext<WalletCtx | null>(null);
export function useWallet() {
  const ctx = useContext(Wallet);
  if (!ctx) throw new Error("useWallet outside provider");
  return ctx;
}

const WALLET_KEY = "unifix-wallet";
const DEMO_ADDRESS = "GBUNIFXDEMOCUSTOMERWALLETQ7XKJ5ZP6V3WRB2N8LYTFA4HGSUQM";

function WalletProvider({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<WalletStatus>("idle");
  const [address, setAddress] = useState<string | null>(null);
  const [passphrase, setPassphrase] = useState<string | null>(null);
  const [source, setSource] = useState<WalletCtx["source"]>(null);
  const [error, setError] = useState<string | null>(null);
  const [freighterAvailable, setFreighterAvailable] = useState<boolean | null>(null);
  const [balances, setBalances] = useState<Balance[] | null | undefined>(undefined);

  // Restore the wallet saved in localStorage after mount (not during SSR).
  useEffect(() => {
    hasFreighter().then(setFreighterAvailable);
    try {
      const saved = JSON.parse(window.localStorage.getItem(WALLET_KEY) ?? "null") as {
        address: string;
        source: "freighter" | "demo";
        passphrase: string;
      } | null;
      if (saved) {
        // eslint-disable-next-line react-hooks/set-state-in-effect -- one-time sync from localStorage
        setAddress(saved.address);
        setSource(saved.source);
        setPassphrase(saved.passphrase);
        setStatus("connected");
      }
    } catch {
      /* ignore */
    }
  }, []);

  const reloadBalances = useCallback(async () => {
    if (!address || source !== "freighter") {
      setBalances(source === "demo" ? [{ asset: "XLM", balance: 9998.5 }, { asset: "USDC", balance: 250 }] : undefined);
      return;
    }
    try {
      setBalances(await fetchBalances(address));
    } catch {
      setBalances(undefined);
    }
  }, [address, source]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetches from Horizon when the wallet changes
    reloadBalances();
  }, [reloadBalances]);

  const persist = (a: string, s: "freighter" | "demo", p: string) =>
    window.localStorage.setItem(WALLET_KEY, JSON.stringify({ address: a, source: s, passphrase: p }));

  const connect = useCallback(async () => {
    setStatus("connecting");
    setError(null);
    try {
      const w = await connectFreighter();
      setAddress(w.address);
      setPassphrase(w.passphrase);
      setSource("freighter");
      setStatus("connected");
      persist(w.address, "freighter", w.passphrase);
      return w.address;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Wallet connection failed.");
      setStatus("error");
      return null;
    }
  }, []);

  const connectDemo = useCallback(() => {
    setAddress(DEMO_ADDRESS);
    setPassphrase(NETWORK.passphrase);
    setSource("demo");
    setStatus("connected");
    setError(null);
    persist(DEMO_ADDRESS, "demo", NETWORK.passphrase);
    return DEMO_ADDRESS;
  }, []);

  const disconnect = useCallback(() => {
    setAddress(null);
    setSource(null);
    setPassphrase(null);
    setStatus("idle");
    setBalances(undefined);
    window.localStorage.removeItem(WALLET_KEY);
  }, []);

  const value = useMemo<WalletCtx>(
    () => ({
      status,
      address,
      passphrase,
      source,
      error,
      freighterAvailable,
      wrongNetwork: !!address && !onRightNetwork(passphrase ?? undefined),
      balances,
      connect,
      connectDemo,
      disconnect,
      reloadBalances,
    }),
    [status, address, passphrase, source, error, freighterAvailable, balances, connect, connectDemo, disconnect, reloadBalances],
  );

  return <Wallet.Provider value={value}>{children}</Wallet.Provider>;
}

/* ---------------- toasts ---------------- */

interface Toast {
  id: number;
  title: string;
  body?: string;
  tone: "ok" | "err" | "info";
}
const ToastCtx = createContext<(t: Omit<Toast, "id">) => void>(() => {});
export const useToast = () => useContext(ToastCtx);

function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((t: Omit<Toast, "id">) => {
    const id = Date.now() + Math.random();
    setToasts((xs) => [...xs, { ...t, id }]);
    setTimeout(() => setToasts((xs) => xs.filter((x) => x.id !== id)), 4800);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div aria-live="polite" className="pointer-events-none fixed inset-x-0 bottom-20 z-[60] flex flex-col items-center gap-2 px-4 md:bottom-6 md:items-end md:pr-6">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={`toast-in pointer-events-auto w-full max-w-sm rounded-lg border px-4 py-3 shadow-lift ${
              t.tone === "err"
                ? "border-clay/30 bg-clay-soft text-clay-ink"
                : t.tone === "ok"
                  ? "border-lagoon/30 bg-lagoon-soft text-lagoon-ink"
                  : "border-line bg-paper text-ink"
            }`}
          >
            <p className="text-sm font-semibold">{t.title}</p>
            {t.body && <p className="mt-0.5 text-sm opacity-80">{t.body}</p>}
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

/* ---------------- root ---------------- */

export function Providers({ children }: { children: React.ReactNode }) {
  const [qc] = useState(
    () =>
      new QueryClient({
        defaultOptions: { queries: { staleTime: IS_DEMO ? 0 : 10_000, retry: 1, refetchOnWindowFocus: !IS_DEMO } },
      }),
  );
  return (
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <SessionProvider>
          <WalletProvider>{children}</WalletProvider>
        </SessionProvider>
      </ToastProvider>
    </QueryClientProvider>
  );
}
