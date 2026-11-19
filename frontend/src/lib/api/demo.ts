"use client";

// In-browser demo backend. Persists to localStorage so the full customer-to-
// professional journey can be clicked through without the FastAPI server.
// Every chain transaction it produces is marked `simulated: true` and the UI
// labels it as such. Live mode (NEXT_PUBLIC_API_URL) never touches this file.

import { createSeed, DB_VERSION, hex, type DB } from "../seed";
import { RATES, toUsdc, overall, money } from "../format";
import type {
  AppNotification,
  Booking,
  BookingBundle,
  Escrow,
  Message,
  Professional,
  Quote,
  RatingBreakdown,
  TimelineEvent,
  User,
} from "../types";
import type { ChangeListener, ConversationSummary, UniFixApi } from "./contract";

const KEY = "unifix-demo-db";
const SESSION_KEY = "unifix-session";
const CONFIRM_MS = 3200;

let db: DB | null = null;
const listeners = new Map<string, Set<ChangeListener>>();

function load(): DB {
  if (db) return db;
  try {
    const raw = typeof window !== "undefined" ? window.localStorage.getItem(KEY) : null;
    const parsed = raw ? (JSON.parse(raw) as DB) : null;
    db = parsed && parsed.version === DB_VERSION ? parsed : createSeed();
  } catch {
    db = createSeed();
  }
  reconcilePending(db);
  return db;
}

function save() {
  try {
    window.localStorage.setItem(KEY, JSON.stringify(db));
  } catch {
    /* storage full or blocked: keep in memory */
  }
}

function emit(...channels: string[]) {
  save();
  for (const ch of [...channels, "*"]) listeners.get(ch)?.forEach((l) => l());
}

export function resetDemo() {
  db = createSeed();
  save();
  emit("*");
}

const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v));
const now = () => new Date().toISOString();
const id = (p: string) => `${p}-${Math.random().toString(36).slice(2, 9)}`;
const wait = (ms = 260 + Math.random() * 240) => new Promise((r) => setTimeout(r, ms));

class ApiError extends Error {
  constructor(
    message: string,
    public status = 400,
  ) {
    super(message);
  }
}

function sessionUserId(): string | null {
  try {
    return window.localStorage.getItem(SESSION_KEY);
  } catch {
    return null;
  }
}

function requireUser(): User {
  const uid = sessionUserId();
  const u = uid ? load().users.find((x) => x.id === uid) : undefined;
  if (!u) throw new ApiError("Sign in to continue.", 401);
  return u;
}

function proOf(pid: string): Professional {
  const p = load().professionals.find((x) => x.id === pid);
  if (!p) throw new ApiError("Professional not found.", 404);
  return p;
}
const userOf = (uid: string) => {
  const u = load().users.find((x) => x.id === uid);
  if (!u) throw new ApiError("User not found.", 404);
  return u;
};
const proUserId = (pid: string) => proOf(pid).userId;
const withOnJob = (p: Professional): Professional => ({
  ...p,
  onJob: load().bookings.some((b) => b.professionalId === p.id && b.status === "IN_PROGRESS"),
});

function notify(userId: string, title: string, body: string, href: string) {
  const n: AppNotification = { id: id("n"), userId, title, body, href, at: now(), read: false };
  load().notifications.unshift(n);
}

function systemMessage(conversationId: string, body: string) {
  const d = load();
  d.messages.push({ id: id("m"), conversationId, senderId: "system", kind: "system", body, createdAt: now() });
  const c = d.conversations.find((x) => x.id === conversationId);
  if (c) {
    c.lastMessageAt = now();
    c.lastMessagePreview = body;
  }
}

function addTimeline(b: Booking, label: string, actor: TimelineEvent["actor"]) {
  b.timeline.push({ at: now(), label, actor });
}

function bundle(b: Booking): BookingBundle {
  const d = load();
  const quote = d.quotes.find((q) => q.id === b.quoteId)!;
  return clone({
    booking: b,
    quote,
    escrow: d.escrows.find((e) => e.id === b.escrowId),
    professional: proOf(b.professionalId),
    customer: userOf(b.customerId),
    dispute: d.disputes.find((x) => x.id === b.disputeId),
    review: d.reviews.find((r) => r.id === b.reviewId),
  });
}

function canSeeBooking(u: User, b: Booking) {
  return u.role === "admin" || b.customerId === u.id || proOf(b.professionalId).userId === u.id;
}

function getBookingFor(u: User, bookingId: string) {
  const b = load().bookings.find((x) => x.id === bookingId);
  if (!b || !canSeeBooking(u, b)) throw new ApiError("Booking not found.", 404);
  return b;
}

/** Mimics the backend background job that confirms pending chain transactions. */
function scheduleConfirmation(escrowId: string) {
  setTimeout(() => {
    const d = load();
    const e = d.escrows.find((x) => x.id === escrowId);
    if (!e) return;
    confirmEscrow(d, e);
    emit(`booking:${e.bookingId}`);
  }, CONFIRM_MS);
}

function confirmEscrow(d: DB, e: Escrow) {
  const tx = e.transactions.find((t) => t.status === "PENDING");
  if (!tx) return;
  tx.status = "CONFIRMED";
  tx.ledger = 1_190_000 + Math.floor(Math.random() * 9000);
  e.reconciliation = "CONFIRMED";
  const b = d.bookings.find((x) => x.id === e.bookingId);
  if (!b) return;
  const pro = d.professionals.find((p) => p.id === b.professionalId)!;
  if (tx.kind === "FUND") {
    e.state = "FUNDED";
    b.status = "FUNDED";
    addTimeline(b, "Escrow funded and confirmed on-chain", "chain");
    systemMessage(b.conversationId, `${e.amount.toFixed(2)} ${e.asset} is held in escrow. Work can begin.`);
    notify(pro.userId, "Payment secured", `${b.title}: funds are held in escrow. You can start the job.`, `/bookings/${b.id}`);
    notify(b.customerId, "Payment confirmed on Stellar", `${e.amount.toFixed(2)} ${e.asset} is held for ${pro.name}.`, `/bookings/${b.id}`);
  } else if (tx.kind === "RELEASE") {
    e.state = "RELEASED";
    b.status = "COMPLETED";
    pro.completedJobs += 1;
    addTimeline(b, "Payment released to professional", "chain");
    systemMessage(b.conversationId, `Payment released. ${e.amount.toFixed(2)} ${e.asset} sent to ${pro.name}.`);
    notify(pro.userId, "Payment released", `${e.amount.toFixed(2)} ${e.asset} for ${b.title} is in your wallet.`, `/bookings/${b.id}`);
    notify(b.customerId, "You can now leave a review", `Tell others how ${pro.name} did.`, `/bookings/${b.id}#review`);
  } else if (tx.kind === "REFUND") {
    e.state = "REFUNDED";
    addTimeline(b, "Refund settled to customer", "chain");
  }
}

function reconcilePending(d: DB) {
  for (const e of d.escrows) {
    const tx = e.transactions.find((t) => t.status === "PENDING");
    if (!tx) continue;
    if (Date.now() - new Date(tx.at).getTime() > CONFIRM_MS) confirmEscrow(d, e);
    else scheduleConfirmation(e.id);
  }
}

function recomputeRating(pid: string) {
  const d = load();
  const pro = d.professionals.find((p) => p.id === pid)!;
  const rs = d.reviews.filter((r) => r.professionalId === pid);
  if (!rs.length) return;
  // Seeded professionals carry historic counts; blend seeded aggregate with new verified reviews.
  const keys: (keyof RatingBreakdown)[] = ["quality", "punctuality", "communication", "professionalism", "value"];
  const prevCount = pro.reviewCount;
  const latest = rs[0];
  for (const k of keys) {
    pro.ratingBreakdown[k] = Math.round(((pro.ratingBreakdown[k] * prevCount + latest.ratings[k]) / (prevCount + 1)) * 100) / 100;
  }
  pro.reviewCount = prevCount + 1;
  pro.rating = overall(pro.ratingBreakdown);
}

const CANNED_REPLIES = [
  "Noted. I can come by tomorrow morning to take a proper look.",
  "Thanks for the details. Can you send a photo of the unit's label?",
  "That's clear. I'll send a quotation with the full breakdown shortly.",
  "Okay. I'll bring the parts with me so we don't need a second visit.",
];

function autoReply(conversationId: string) {
  const d = load();
  const c = d.conversations.find((x) => x.id === conversationId);
  if (!c) return;
  const pro = proOf(c.professionalId);
  if (sessionUserId() === pro.userId) return;
  const typingKey = `typing:${conversationId}`;
  setTimeout(() => {
    typingUntil.set(conversationId, Date.now() + 1600);
    emit(typingKey);
  }, 900);
  setTimeout(() => {
    const msg: Message = {
      id: id("m"),
      conversationId,
      senderId: pro.userId,
      kind: "text",
      body: CANNED_REPLIES[Math.floor(Math.random() * CANNED_REPLIES.length)],
      createdAt: now(),
    };
    d.messages.push(msg);
    c.lastMessageAt = msg.createdAt;
    c.lastMessagePreview = msg.body;
    c.unreadFor = [c.customerId];
    emit(`conversation:${conversationId}`, typingKey);
  }, 2600);
}

const typingUntil = new Map<string, number>();

/** True while the demo professional is "typing" a reply. */
export function isTyping(conversationId: string) {
  return (typingUntil.get(conversationId) ?? 0) > Date.now();
}

export const demoApi: UniFixApi = {
  mode: "demo",

  async signIn(email) {
    await wait();
    const u = load().users.find((x) => x.email.toLowerCase() === email.trim().toLowerCase());
    if (!u) throw new ApiError("No account uses that email. Pick a demo account below, or create one.", 401);
    window.localStorage.setItem(SESSION_KEY, u.id);
    return clone(u);
  },

  async signUp(input) {
    await wait();
    const d = load();
    if (d.users.some((u) => u.email.toLowerCase() === input.email.toLowerCase())) {
      throw new ApiError("An account with this email already exists. Sign in instead.", 409);
    }
    const uid = id("u");
    const user: User = { id: uid, name: input.name, email: input.email, role: input.role, city: input.city, country: input.country };
    if (input.role === "professional" && input.professional) {
      const p = input.professional;
      const pid = id("p");
      user.professionalId = pid;
      d.professionals.push({
        id: pid,
        userId: uid,
        name: input.name,
        category: p.category,
        headline: p.headline,
        bio: p.bio,
        city: input.city,
        area: p.area,
        country: input.country,
        distanceKm: 5,
        coverage: p.coverage,
        rating: 0,
        reviewCount: 0,
        completedJobs: 0,
        yearsExperience: p.yearsExperience,
        verification: { identity: false, trade: false, phone: false },
        availability: p.availability,
        responseMinutes: 30,
        startingPrice: p.startingPrice,
        currency: input.country === "NG" ? "NGN" : "GHS",
        skills: p.skills,
        languages: ["English"],
        portfolio: [],
        ratingBreakdown: { quality: 0, punctuality: 0, communication: 0, professionalism: 0, value: 0 },
        joinedAt: now(),
      });
    }
    d.users.push(user);
    window.localStorage.setItem(SESSION_KEY, uid);
    emit("*");
    return clone(user);
  },

  async signOut() {
    window.localStorage.removeItem(SESSION_KEY);
  },

  async me() {
    const uid = sessionUserId();
    if (!uid) return null;
    const u = load().users.find((x) => x.id === uid);
    return u ? clone(u) : null;
  },

  async updateMe(input) {
    await wait();
    const me = requireUser();
    const u = load().users.find((x) => x.id === me.id)!;
    if (!input.name.trim()) throw new ApiError("Enter your name.");
    u.name = input.name.trim();
    u.city = input.city.trim();
    if (u.professionalId) {
      const p = load().professionals.find((x) => x.id === u.professionalId);
      if (p) p.name = u.name;
    }
    emit("*");
    return clone(u);
  },

  async updateProfessional(pid, input) {
    await wait();
    const me = requireUser();
    const p = load().professionals.find((x) => x.id === pid);
    if (!p || p.userId !== me.id) throw new ApiError("You can only edit your own profile.", 403);
    if (input.startingPrice < 0) throw new ApiError("Starting price can't be negative.");
    Object.assign(p, input);
    emit("*", `pro:${pid}`);
    return clone(p);
  },

  async listProfessionals(f) {
    await wait();
    const q = f.q?.trim().toLowerCase();
    let list = load().professionals.filter((p) => {
      if (f.category && f.category !== "all" && p.category !== f.category) return false;
      if (f.city && f.city !== "all" && p.city !== f.city) return false;
      if (f.availability === "now" && p.availability !== "now") return false;
      if (f.availability === "today" && !["now", "today"].includes(p.availability)) return false;
      if (f.minRating && p.rating < f.minRating) return false;
      if (f.verifiedOnly && !(p.verification.identity && p.verification.trade)) return false;
      if (q) {
        const hay = [p.name, p.headline, p.area, p.city, p.category, ...p.skills].join(" ").toLowerCase();
        if (!q.split(/\s+/).every((w) => hay.includes(w))) return false;
      }
      return true;
    });
    const sorters: Record<string, (a: Professional, b: Professional) => number> = {
      best: (a, b) => b.rating * Math.log(b.reviewCount + 2) - a.rating * Math.log(a.reviewCount + 2),
      nearest: (a, b) => a.distanceKm - b.distanceKm,
      "most-jobs": (a, b) => b.completedJobs - a.completedJobs,
      experience: (a, b) => b.yearsExperience - a.yearsExperience,
    };
    list = [...list].sort(sorters[f.sort ?? "best"]);
    return clone(list.map(withOnJob));
  },

  async getProfessional(pid) {
    await wait(180);
    return clone(withOnJob(proOf(pid)));
  },

  async listReviews(pid) {
    await wait(200);
    return clone(
      load()
        .reviews.filter((r) => r.professionalId === pid)
        .sort((a, b) => b.createdAt.localeCompare(a.createdAt)),
    );
  },

  async listConversations() {
    await wait(160);
    const u = requireUser();
    const d = load();
    const mine = d.conversations.filter((c) => c.customerId === u.id || proUserId(c.professionalId) === u.id);
    return clone(
      mine
        .sort((a, b) => b.lastMessageAt.localeCompare(a.lastMessageAt))
        .map<ConversationSummary>((c) => ({
          conversation: c,
          professional: proOf(c.professionalId),
          customer: userOf(c.customerId),
          unread: c.unreadFor.includes(u.id),
        })),
    );
  },

  async getConversation(cid) {
    await wait(120);
    const u = requireUser();
    const d = load();
    const c = d.conversations.find((x) => x.id === cid);
    if (!c || (c.customerId !== u.id && proUserId(c.professionalId) !== u.id && u.role !== "admin")) {
      throw new ApiError("Conversation not found.", 404);
    }
    if (c.unreadFor.includes(u.id)) {
      c.unreadFor = c.unreadFor.filter((x) => x !== u.id);
      d.messages.filter((m) => m.conversationId === cid && m.senderId !== u.id && !m.readAt).forEach((m) => (m.readAt = now()));
      save();
    }
    return clone({
      conversation: c,
      professional: proOf(c.professionalId),
      customer: userOf(c.customerId),
      unread: false,
      messages: d.messages.filter((m) => m.conversationId === cid).sort((a, b) => a.createdAt.localeCompare(b.createdAt)),
      quotes: d.quotes.filter((q) => q.conversationId === cid),
    });
  },

  async openConversation(pid) {
    await wait();
    const u = requireUser();
    if (u.role !== "customer") throw new ApiError("Only customers can start a conversation with a professional.", 403);
    const d = load();
    let c = d.conversations.find((x) => x.customerId === u.id && x.professionalId === pid && !x.bookingId);
    if (!c) {
      c = { id: id("c"), customerId: u.id, professionalId: pid, lastMessageAt: now(), lastMessagePreview: "Conversation started", unreadFor: [] };
      d.conversations.push(c);
      emit("*");
    }
    return clone(c);
  },

  async sendMessage(cid, input) {
    await wait(120);
    const u = requireUser();
    const d = load();
    const c = d.conversations.find((x) => x.id === cid);
    if (!c) throw new ApiError("Conversation not found.", 404);
    const msg: Message = {
      id: id("m"),
      conversationId: cid,
      senderId: u.id,
      kind: input.attachment ? "image" : "text",
      body: input.body,
      attachment: input.attachment,
      createdAt: now(),
    };
    d.messages.push(msg);
    c.lastMessageAt = msg.createdAt;
    c.lastMessagePreview = input.attachment ? "Photo" : input.body;
    const other = u.id === c.customerId ? proUserId(c.professionalId) : c.customerId;
    c.unreadFor = [other];
    emit(`conversation:${cid}`);
    if (u.id === c.customerId) autoReply(cid);
    return clone(msg);
  },

  async createQuote(input) {
    await wait();
    const u = requireUser();
    const d = load();
    const c = d.conversations.find((x) => x.id === input.conversationId);
    if (!c || proUserId(c.professionalId) !== u.id) throw new ApiError("Only the professional in this conversation can send a quotation.", 403);
    if (input.labour < 0 || input.materials < 0 || input.labour + input.materials <= 0) throw new ApiError("Enter a labour or materials cost above zero.");
    if (input.milestones.length && input.milestones.reduce((s, m) => s + m.percent, 0) !== 100) {
      throw new ApiError("Milestone allocations must add up to 100%.");
    }
    const prev = d.quotes.filter((q) => q.conversationId === c.id);
    prev.filter((q) => q.status === "PENDING").forEach((q) => (q.status = "SUPERSEDED"));
    const quote: Quote = {
      id: id("q"),
      conversationId: c.id,
      professionalId: c.professionalId,
      customerId: c.customerId,
      version: prev.length + 1,
      status: "PENDING",
      title: input.title,
      description: input.description,
      labour: input.labour,
      materials: input.materials,
      total: input.labour + input.materials,
      currency: input.currency,
      completionDate: input.completionDate,
      paymentTerms: input.paymentTerms,
      milestones: input.milestones,
      createdAt: now(),
    };
    d.quotes.push(quote);
    d.messages.push({ id: id("m"), conversationId: c.id, senderId: u.id, kind: "quote", body: "Quotation", quoteId: quote.id, createdAt: now() });
    c.lastMessageAt = now();
    c.lastMessagePreview = `Quotation v${quote.version} sent`;
    c.unreadFor = [c.customerId];
    notify(c.customerId, `New quotation from ${u.name}`, `${money(quote.total, quote.currency)} for ${quote.title}.`, `/messages/${c.id}`);
    emit(`conversation:${c.id}`);
    return clone(quote);
  },

  async acceptQuote(qid) {
    await wait();
    const u = requireUser();
    const d = load();
    const q = d.quotes.find((x) => x.id === qid);
    if (!q || q.customerId !== u.id) throw new ApiError("Quotation not found.", 404);
    if (q.status !== "PENDING") throw new ApiError("This quotation can no longer be accepted.", 409);
    const existing = d.bookings.find((b) => b.quoteId === qid);
    if (existing) return clone(existing);
    q.status = "ACCEPTED";
    q.acceptedAt = now();
    q.agreementHash = hex();
    const b: Booking = {
      id: id("b"),
      quoteId: q.id,
      conversationId: q.conversationId,
      customerId: q.customerId,
      professionalId: q.professionalId,
      title: q.title,
      address: u.city,
      status: "PENDING_PAYMENT",
      createdAt: now(),
      timeline: [{ at: now(), label: `Quotation v${q.version} accepted and locked`, actor: "customer" }],
    };
    d.bookings.push(b);
    const c = d.conversations.find((x) => x.id === q.conversationId)!;
    c.bookingId = b.id;
    systemMessage(c.id, "Quotation accepted. Agreement locked and booking created.");
    notify(proUserId(q.professionalId), "Quotation accepted", `${u.name} accepted ${q.title}. Waiting for payment.`, `/bookings/${b.id}`);
    emit(`conversation:${c.id}`, `booking:${b.id}`);
    return clone(b);
  },

  async rejectQuote(qid) {
    await wait();
    const u = requireUser();
    const d = load();
    const q = d.quotes.find((x) => x.id === qid);
    if (!q || q.customerId !== u.id) throw new ApiError("Quotation not found.", 404);
    if (q.status !== "PENDING") throw new ApiError("This quotation was already answered.", 409);
    q.status = "REJECTED";
    systemMessage(q.conversationId, `Quotation v${q.version} declined.`);
    emit(`conversation:${q.conversationId}`);
    return clone(q);
  },

  async listBookings() {
    await wait(180);
    const u = requireUser();
    return load()
      .bookings.filter((b) => canSeeBooking(u, b))
      .sort((a, b) => b.createdAt.localeCompare(a.createdAt))
      .map(bundle);
  },

  async getBooking(bid) {
    await wait(140);
    return bundle(getBookingFor(requireUser(), bid));
  },

  async prepareEscrow(bid, customerWallet) {
    await wait(500);
    const u = requireUser();
    const d = load();
    const b = getBookingFor(u, bid);
    if (b.customerId !== u.id) throw new ApiError("Only the customer can fund this booking.", 403);
    if (b.status !== "PENDING_PAYMENT") throw new ApiError("This booking is not waiting for payment.", 409);
    const q = d.quotes.find((x) => x.id === b.quoteId)!;
    let e = d.escrows.find((x) => x.id === b.escrowId);
    if (!e) {
      e = {
        id: id("e"),
        bookingId: b.id,
        contractId: "CDUNIFIXESCRWTESTNETDEMO7QX4M2KJ5ZP6V3WRB2N8LYTFA4HGSU",
        state: "CREATED",
        asset: "USDC",
        amount: toUsdc(q.total, q.currency),
        localAmount: q.total,
        currency: q.currency,
        rate: RATES[q.currency],
        networkFee: 0.00421,
        customerWallet,
        professionalWallet: `GC${proOf(b.professionalId).id.toUpperCase().replace(/[^A-Z]/g, "").padEnd(10, "X")}DEMOWALLETTESTNET7QKX7M2JZP5VRB2N8LY`.slice(0, 56),
        reconciliation: "AWAITING_SIGNATURE",
        transactions: [],
        createdAt: now(),
      };
      d.escrows.push(e);
      b.escrowId = e.id;
      addTimeline(b, "Escrow created for agreed amount", "system");
    }
    e.customerWallet = customerWallet;
    emit(`booking:${b.id}`);
    return { escrow: clone(e) };
  },

  async submitFunding(eid) {
    await wait(700);
    const u = requireUser();
    const d = load();
    const e = d.escrows.find((x) => x.id === eid);
    if (!e) throw new ApiError("Escrow not found.", 404);
    const b = getBookingFor(u, e.bookingId);
    if (b.customerId !== u.id) throw new ApiError("Only the customer can fund this escrow.", 403);
    if (e.transactions.some((t) => t.kind === "FUND")) return clone(e); // idempotent: no duplicate funding
    e.transactions.push({ kind: "FUND", hash: hex(), at: now(), status: "PENDING", simulated: true });
    e.reconciliation = "PENDING_CONFIRMATION";
    addTimeline(b, "Funding transaction submitted", "customer");
    emit(`booking:${b.id}`);
    scheduleConfirmation(e.id);
    return clone(e);
  },

  async getEscrow(eid) {
    const e = load().escrows.find((x) => x.id === eid);
    if (!e) throw new ApiError("Escrow not found.", 404);
    return clone(e);
  },

  async startJob(bid) {
    await wait();
    const u = requireUser();
    const b = getBookingFor(u, bid);
    if (proUserId(b.professionalId) !== u.id) throw new ApiError("Only the assigned professional can start this job.", 403);
    if (b.status !== "FUNDED") throw new ApiError("The job can start once payment is confirmed.", 409);
    b.status = "IN_PROGRESS";
    addTimeline(b, "Job started", "professional");
    notify(b.customerId, `${u.name} started your job`, b.title, `/bookings/${b.id}`);
    systemMessage(b.conversationId, "Job started.");
    emit(`booking:${b.id}`);
    return clone(b);
  },

  async submitCompletion(bid, evidence) {
    await wait(600);
    const u = requireUser();
    const b = getBookingFor(u, bid);
    if (proUserId(b.professionalId) !== u.id) throw new ApiError("Only the assigned professional can submit completion evidence.", 403);
    if (b.status !== "IN_PROGRESS") throw new ApiError("Completion can only be submitted for a job in progress.", 409);
    b.completion = { ...evidence, submittedAt: now(), hash: hex() };
    b.status = "COMPLETION_SUBMITTED";
    addTimeline(b, "Completion evidence submitted", "professional");
    notify(b.customerId, "Job marked complete", `Review ${u.name}'s evidence and approve or raise a dispute.`, `/bookings/${b.id}`);
    systemMessage(b.conversationId, "Completion evidence submitted. Waiting for customer approval.");
    emit(`booking:${b.id}`);
    return clone(b);
  },

  async releaseEscrow(eid) {
    await wait(700);
    const u = requireUser();
    const d = load();
    const e = d.escrows.find((x) => x.id === eid);
    if (!e) throw new ApiError("Escrow not found.", 404);
    const b = getBookingFor(u, e.bookingId);
    if (b.customerId !== u.id) throw new ApiError("Only the customer can approve release.", 403);
    if (e.state === "DISPUTED") throw new ApiError("Funds are locked by an open dispute and cannot be released by approval.", 409);
    if (e.state === "RELEASED" || e.transactions.some((t) => t.kind === "RELEASE")) return { escrow: clone(e) };
    if (e.state === "REFUNDED") throw new ApiError("This escrow was refunded and cannot be released.", 409);
    if (e.state !== "FUNDED" || b.status !== "COMPLETION_SUBMITTED") throw new ApiError("Release is available after the professional submits completion.", 409);
    e.transactions.push({ kind: "RELEASE", hash: hex(), at: now(), status: "PENDING", simulated: true });
    e.reconciliation = "PENDING_CONFIRMATION";
    addTimeline(b, "Customer approved the work", "customer");
    emit(`booking:${b.id}`);
    scheduleConfirmation(e.id);
    return { escrow: clone(e) };
  },

  async openDispute(eid, input) {
    await wait();
    const u = requireUser();
    const d = load();
    const e = d.escrows.find((x) => x.id === eid);
    if (!e) throw new ApiError("Escrow not found.", 404);
    const b = getBookingFor(u, e.bookingId);
    if (e.state !== "FUNDED") throw new ApiError("Only funded escrows can be disputed.", 409);
    const dispute = { id: id("d"), bookingId: b.id, escrowId: e.id, openedBy: u.id, reason: input.reason, details: input.details, status: "OPEN" as const, openedAt: now() };
    d.disputes.push(dispute);
    e.state = "DISPUTED";
    b.status = "DISPUTED";
    b.disputeId = dispute.id;
    addTimeline(b, "Dispute opened, funds locked", u.id === b.customerId ? "customer" : "professional");
    systemMessage(b.conversationId, "Dispute opened. Funds stay locked until UniFix resolves it.");
    const other = u.id === b.customerId ? proUserId(b.professionalId) : b.customerId;
    notify(other, "A dispute was opened", b.title, `/bookings/${b.id}`);
    d.users.filter((x) => x.role === "admin").forEach((a) => notify(a.id, "Dispute needs review", b.title, "/admin"));
    emit(`booking:${b.id}`);
    return clone(dispute);
  },

  async resolveDispute(did, input) {
    await wait(700);
    const u = requireUser();
    if (u.role !== "admin") throw new ApiError("Only an authorised resolver can settle disputes.", 403);
    const d = load();
    const dispute = d.disputes.find((x) => x.id === did);
    if (!dispute) throw new ApiError("Dispute not found.", 404);
    if (dispute.status === "RESOLVED" || dispute.status === "CLOSED") throw new ApiError("Dispute is already resolved.", 409);
    const e = d.escrows.find((x) => x.id === dispute.escrowId)!;
    const b = d.bookings.find((x) => x.id === dispute.bookingId)!;
    dispute.status = "RESOLVED";
    dispute.outcome = input.outcome;
    dispute.splitPercentToProfessional = input.splitPercentToProfessional;
    dispute.resolutionNote = input.note;
    dispute.resolvedAt = now();
    const kind = input.outcome === "REFUND" ? "REFUND" : "RELEASE";
    e.transactions.push({ kind, hash: hex(), ledger: 1_190_000 + Math.floor(Math.random() * 9000), at: now(), status: "CONFIRMED", simulated: true });
    e.state = input.outcome === "REFUND" ? "REFUNDED" : "RELEASED";
    e.reconciliation = "CONFIRMED";
    b.status = input.outcome === "REFUND" ? "CANCELLED" : "COMPLETED";
    const label =
      input.outcome === "SPLIT"
        ? `Dispute resolved: ${input.splitPercentToProfessional}% to professional, rest refunded`
        : input.outcome === "REFUND"
          ? "Dispute resolved: full refund to customer"
          : "Dispute resolved: full release to professional";
    addTimeline(b, label, "admin");
    systemMessage(b.conversationId, label);
    notify(b.customerId, "Dispute resolved", label, `/bookings/${b.id}`);
    notify(proUserId(b.professionalId), "Dispute resolved", label, `/bookings/${b.id}`);
    emit(`booking:${b.id}`);
    return clone(dispute);
  },

  async listDisputes() {
    await wait(200);
    const u = requireUser();
    if (u.role !== "admin") throw new ApiError("Admin access required.", 403);
    const d = load();
    return d.disputes
      .sort((a, b) => b.openedAt.localeCompare(a.openedAt))
      .map((dispute) => ({ dispute: clone(dispute), bundle: bundle(d.bookings.find((b) => b.id === dispute.bookingId)!) }));
  },

  async submitReview(bid, input) {
    await wait(500);
    const u = requireUser();
    const d = load();
    const b = getBookingFor(u, bid);
    if (b.customerId !== u.id) throw new ApiError("Only the customer on this booking can leave a review.", 403);
    if (b.status !== "COMPLETED") throw new ApiError("Reviews open once the job is completed and paid.", 409);
    if (b.reviewId || d.reviews.some((r) => r.bookingId === bid && r.customerId === u.id)) {
      throw new ApiError("You already reviewed this booking.", 409);
    }
    const vals = Object.values(input.ratings);
    if (vals.some((v) => v < 1 || v > 5)) throw new ApiError("Rate every category from 1 to 5.");
    const [first, last] = u.name.split(" ");
    const review = {
      id: id("r"),
      bookingId: bid,
      professionalId: b.professionalId,
      customerId: u.id,
      customerName: `${first} ${last ? last[0] + "." : ""}`.trim(),
      jobTitle: b.title,
      ratings: input.ratings,
      comment: input.comment,
      createdAt: now(),
    };
    d.reviews.unshift(review);
    b.reviewId = review.id;
    recomputeRating(b.professionalId);
    addTimeline(b, "Verified review submitted", "customer");
    notify(proUserId(b.professionalId), "New verified review", `${review.customerName} rated you ${overall(input.ratings)}.`, `/pros/${b.professionalId}`);
    emit(`booking:${b.id}`, `pro:${b.professionalId}`);
    return clone(review);
  },

  async listNotifications() {
    const uid = sessionUserId();
    if (!uid) return [];
    return clone(load().notifications.filter((n) => n.userId === uid).slice(0, 30));
  },

  async markNotificationsRead() {
    const uid = sessionUserId();
    load().notifications.forEach((n) => {
      if (n.userId === uid) n.read = true;
    });
    emit("notifications");
  },

  async walletChallenge(address) {
    await wait(150);
    return { message: `UniFix wallet ownership check\nAddress: ${address}\nNonce: ${hex(16)}\nIssued: ${now()}` };
  },

  async registerWallet(address, _message, signature) {
    await wait(300);
    const u = load().users.find((x) => x.id === requireUser().id)!;
    u.walletAddress = address;
    u.walletVerified = signature !== "demo";
    emit("*");
    return clone(u);
  },

  async startCall() {
    await wait(300);
    return { sessionId: id("call") };
  },

  subscribe(channel, listener) {
    if (!listeners.has(channel)) listeners.set(channel, new Set());
    listeners.get(channel)!.add(listener);
    return () => listeners.get(channel)?.delete(listener);
  },
};

export const DEMO_ACCOUNTS = [
  { email: "adaeze@demo.unifix", name: "Adaeze Okafor", role: "Customer in Lekki, Lagos" },
  { email: "tunde@demo.unifix", name: "Tunde Bakare", role: "AC technician in Yaba" },
  { email: "kofi@demo.unifix", name: "Kofi Asante", role: "Customer in East Legon, Accra" },
  { email: "ops@demo.unifix", name: "UniFix Operations", role: "Admin and dispute resolver" },
];

export { ApiError };
