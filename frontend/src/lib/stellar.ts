"use client";

import {
  getAddress,
  getNetworkDetails,
  isConnected,
  requestAccess,
  signMessage,
  signTransaction,
} from "@stellar/freighter-api";

export const NETWORK = {
  name: "TESTNET",
  label: "Stellar testnet",
  passphrase: "Test SDF Network ; September 2015",
  horizon: process.env.NEXT_PUBLIC_HORIZON_URL ?? "https://horizon-testnet.stellar.org",
  explorer: "https://stellar.expert/explorer/testnet",
};

const STRKEY = /^G[A-Z2-7]{55}$/;

/** Format check for a Stellar account public key. The backend does the full checksum check. */
export function isValidPublicKey(address: string) {
  return STRKEY.test(address.trim());
}

export async function hasFreighter() {
  try {
    const res = await isConnected();
    return !!res.isConnected && !res.error;
  } catch {
    return false;
  }
}

export class WalletError extends Error {}

export async function connectFreighter() {
  if (!(await hasFreighter())) {
    throw new WalletError("Freighter is not installed in this browser.");
  }
  const access = await requestAccess();
  if (access.error) throw new WalletError(access.error.message ?? "Wallet access was declined.");
  const addr = access.address || (await getAddress()).address;
  if (!isValidPublicKey(addr)) throw new WalletError("The wallet returned an invalid address.");
  const net = await getNetworkDetails();
  if (net.error) throw new WalletError(net.error.message ?? "Could not read wallet network.");
  return { address: addr, network: net.network, passphrase: net.networkPassphrase };
}

export async function currentFreighterNetwork() {
  const net = await getNetworkDetails();
  return net.networkPassphrase;
}

export function onRightNetwork(passphrase?: string) {
  return passphrase === NETWORK.passphrase;
}

export interface Balance {
  asset: string;
  issuer?: string;
  balance: number;
}

/** Reads balances from Horizon. Returns null when the account does not exist on testnet yet. */
export async function fetchBalances(address: string): Promise<Balance[] | null> {
  const res = await fetch(`${NETWORK.horizon}/accounts/${address}`);
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`Horizon returned ${res.status}`);
  const data = (await res.json()) as {
    balances: { asset_type: string; asset_code?: string; asset_issuer?: string; balance: string }[];
  };
  return data.balances.map((b) => ({
    asset: b.asset_type === "native" ? "XLM" : (b.asset_code ?? "?"),
    issuer: b.asset_issuer,
    balance: Number(b.balance),
  }));
}

export async function fundWithFriendbot(address: string) {
  const res = await fetch(`https://friendbot.stellar.org/?addr=${encodeURIComponent(address)}`);
  if (!res.ok) throw new Error("Friendbot could not fund this account.");
}

export async function signXdr(xdr: string, address: string) {
  const res = await signTransaction(xdr, { networkPassphrase: NETWORK.passphrase, address });
  if (res.error) throw new WalletError(res.error.message ?? "Signature was declined.");
  return res.signedTxXdr;
}

export async function signOwnershipMessage(message: string, address: string) {
  const res = await signMessage(message, { networkPassphrase: NETWORK.passphrase, address });
  if (res.error) throw new WalletError(res.error.message ?? "Signature was declined.");
  const sig = res.signedMessage;
  if (!sig) throw new WalletError("Wallet returned no signature.");
  return typeof sig === "string" ? sig : Buffer.from(sig).toString("base64");
}

export const explorerTx = (hash: string) => `${NETWORK.explorer}/tx/${hash}`;
export const explorerContract = (id: string) => `${NETWORK.explorer}/contract/${id}`;
export const explorerAccount = (id: string) => `${NETWORK.explorer}/account/${id}`;
