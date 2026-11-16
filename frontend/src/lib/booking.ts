import type { BookingBundle } from "./types";

/** The next thing this viewer has to do on a booking, or null when it's waiting on someone else. */
export function nextStep(b: BookingBundle, viewerIsCustomer: boolean): string | null {
  const s = b.booking.status;
  if (b.escrow?.reconciliation === "PENDING_CONFIRMATION") return null;
  if (viewerIsCustomer) {
    if (s === "PENDING_PAYMENT") return "Fund the escrow";
    if (s === "COMPLETION_SUBMITTED") return "Review and approve";
    if (s === "COMPLETED" && !b.booking.reviewId) return "Leave a review";
  } else {
    if (s === "FUNDED") return "Start the job";
    if (s === "IN_PROGRESS") return "Submit completion";
  }
  return null;
}
