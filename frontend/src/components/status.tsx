import type { BookingStatus, EscrowState, Reconciliation } from "@/lib/types";
import { Badge } from "./ui";

export const BOOKING_STATUS: Record<BookingStatus, { label: string; tone: "neutral" | "danfo" | "lagoon" | "clay" | "stellar" }> = {
  PENDING_PAYMENT: { label: "Waiting for payment", tone: "neutral" },
  FUNDED: { label: "Payment held", tone: "danfo" },
  IN_PROGRESS: { label: "In progress", tone: "danfo" },
  COMPLETION_SUBMITTED: { label: "Awaiting approval", tone: "stellar" },
  COMPLETED: { label: "Completed", tone: "lagoon" },
  DISPUTED: { label: "In dispute", tone: "clay" },
  CANCELLED: { label: "Cancelled", tone: "neutral" },
};

export const ESCROW_STATE: Record<EscrowState, { label: string; tone: "neutral" | "danfo" | "lagoon" | "clay" | "stellar" }> = {
  CREATED: { label: "Created, not funded", tone: "neutral" },
  FUNDED: { label: "Held in escrow", tone: "danfo" },
  RELEASED: { label: "Released", tone: "lagoon" },
  REFUNDED: { label: "Refunded", tone: "neutral" },
  DISPUTED: { label: "Locked by dispute", tone: "clay" },
};

export const RECONCILIATION: Record<Reconciliation, string> = {
  AWAITING_SIGNATURE: "Waiting for your signature",
  PENDING_CONFIRMATION: "Confirming on Stellar",
  CONFIRMED: "Confirmed on-chain",
  FAILED: "Transaction failed",
};

export function BookingBadge({ status }: { status: BookingStatus }) {
  const s = BOOKING_STATUS[status];
  return <Badge tone={s.tone}>{s.label}</Badge>;
}

export function EscrowBadge({ state }: { state: EscrowState }) {
  const s = ESCROW_STATE[state];
  return <Badge tone={s.tone}>{s.label}</Badge>;
}
