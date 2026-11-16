"use client";

// Live client for the Handi FastAPI backend. Routes follow PRD section 10.
// The backend owns business rules and reconciliation: this client never
// treats a wallet signature as proof of settlement. It always re-reads
// escrow state from the API, which reads confirmed state from Stellar.

import type { HandiApi } from "./contract";

const BASE = (process.env.NEXT_PUBLIC_API_URL ?? "").replace(/\/$/, "");
const TOKEN_KEY = "handi-token";

export class LiveApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

function token() {
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

function idempotencyKey() {
  return typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : String(Date.now());
}

async function req<T>(path: string, init: RequestInit & { json?: unknown; idempotent?: boolean } = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const t = token();
  if (t) headers.set("Authorization", `Bearer ${t}`);
  if (init.json !== undefined) headers.set("Content-Type", "application/json");
  if (init.idempotent) headers.set("Idempotency-Key", idempotencyKey());
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers,
    body: init.json !== undefined ? JSON.stringify(init.json) : init.body,
  });
  if (!res.ok) {
    let msg = `Request failed (${res.status}).`;
    try {
      const body = await res.json();
      msg = typeof body.detail === "string" ? body.detail : (body.message ?? msg);
    } catch {
      /* non-JSON error */
    }
    throw new LiveApiError(msg, res.status);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

const post = <T,>(path: string, json?: unknown) => req<T>(path, { method: "POST", json: json ?? {}, idempotent: true });

export const liveApi: HandiApi = {
  mode: "live",

  async signIn(email, password) {
    const r = await req<{ access_token: string; user: Awaited<ReturnType<HandiApi["me"]>> }>("/auth/login", {
      method: "POST",
      json: { email, password },
    });
    window.localStorage.setItem(TOKEN_KEY, r.access_token);
    return r.user!;
  },
  async signUp(input) {
    const r = await req<{ access_token: string; user: Awaited<ReturnType<HandiApi["me"]>> }>("/auth/register", {
      method: "POST",
      json: input,
    });
    window.localStorage.setItem(TOKEN_KEY, r.access_token);
    return r.user!;
  },
  async signOut() {
    window.localStorage.removeItem(TOKEN_KEY);
  },
  async me() {
    if (!token()) return null;
    try {
      return await req("/auth/me");
    } catch (e) {
      if (e instanceof LiveApiError && e.status === 401) return null;
      throw e;
    }
  },

  updateMe: (input) => req("/auth/me", { method: "PATCH", json: input, idempotent: true }),
  updateProfessional: (id, input) => req(`/professionals/${id}`, { method: "PATCH", json: input, idempotent: true }),

  listProfessionals(f) {
    const qs = new URLSearchParams();
    Object.entries(f).forEach(([k, v]) => {
      if (v !== undefined && v !== "" && v !== "all" && v !== "any" && v !== false) qs.set(k, String(v));
    });
    return req(`/professionals?${qs}`);
  },
  getProfessional: (id) => req(`/professionals/${id}`),
  listReviews: (id) => req(`/professionals/${id}/reviews`),

  listConversations: () => req("/conversations"),
  getConversation: (id) => req(`/conversations/${id}`),
  openConversation: (professionalId) => post("/conversations", { professional_id: professionalId }),
  sendMessage: (id, input) => post(`/conversations/${id}/messages`, input),

  createQuote: (input) => post("/quotes", input),
  acceptQuote: (id) => post(`/quotes/${id}/accept`),
  rejectQuote: (id) => post(`/quotes/${id}/reject`),

  listBookings: () => req("/bookings"),
  getBooking: (id) => req(`/bookings/${id}`),
  prepareEscrow: (id, customerWallet) => post(`/bookings/${id}/escrow`, { customer_wallet: customerWallet }),
  submitFunding: (id, signedXdr) => post(`/escrows/${id}/funding`, { signed_xdr: signedXdr }),
  getEscrow: (id) => req(`/escrows/${id}`),
  startJob: (id) => post(`/bookings/${id}/start`),
  submitCompletion: (id, evidence) => post(`/bookings/${id}/completion`, evidence),
  releaseEscrow: (id, signedXdr) => post(`/escrows/${id}/release`, signedXdr ? { signed_xdr: signedXdr } : {}),
  openDispute: (id, input) => post(`/escrows/${id}/disputes`, input),
  resolveDispute: (id, input) => post(`/disputes/${id}/resolve`, input),
  listDisputes: () => req("/admin/disputes"),
  submitReview: (id, input) => post(`/bookings/${id}/reviews`, input),

  listNotifications: () => req("/notifications"),
  markNotificationsRead: () => post("/notifications/read"),

  walletChallenge: (address) => post("/wallets/challenge", { address }),
  registerWallet: (address, message, signature) => post("/wallets", { address, message, signature }),

  startCall: (conversationId) => post("/calls/sessions", { conversation_id: conversationId }),

  subscribe(channel, listener) {
    // Conversations stream over the authenticated WebSocket. Other channels
    // rely on TanStack Query polling (see hooks.ts).
    if (!channel.startsWith("conversation:")) return () => {};
    const id = channel.split(":")[1];
    const wsBase = BASE.replace(/^http/, "ws");
    let ws: WebSocket | null = null;
    let closed = false;
    let retry = 0;
    const open = () => {
      ws = new WebSocket(`${wsBase}/ws/conversations/${id}?token=${encodeURIComponent(token() ?? "")}`);
      ws.onmessage = () => listener();
      ws.onopen = () => (retry = 0);
      ws.onclose = () => {
        if (closed) return;
        retry = Math.min(retry + 1, 5);
        setTimeout(open, 500 * 2 ** retry);
      };
    };
    open();
    return () => {
      closed = true;
      ws?.close();
    };
  },
};
