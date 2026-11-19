import { cn } from "@/lib/format";
import type { BookingStatus } from "@/lib/types";

/* Where a booking sits on the four-step path every job follows. */
const STAGE: Record<BookingStatus, number> = {
  PENDING_PAYMENT: 0,
  FUNDED: 1,
  IN_PROGRESS: 1,
  COMPLETION_SUBMITTED: 2,
  DISPUTED: 2,
  COMPLETED: 3,
  CANCELLED: 0,
};
const STAGES = ["Agreed", "Held", "Done", "Paid"];

export function Track({ status }: { status: BookingStatus }) {
  const at = STAGE[status];
  const disputed = status === "DISPUTED";
  return (
    <div className="w-full max-w-48" aria-label={`Step ${at + 1} of 4: ${STAGES[at]}`}>
      <div className="flex gap-1">
        {STAGES.map((s, i) => (
          <span
            key={s}
            className={cn(
              "h-1.5 flex-1 rounded-full",
              i < at ? "bg-ink-2" : i === at ? (disputed ? "bg-clay" : i === 1 ? "bg-danfo" : i === 3 ? "bg-lagoon" : "bg-stellar") : "bg-line",
            )}
          />
        ))}
      </div>
      <div className="mt-1.5 flex justify-between text-xs text-ink-3">
        {STAGES.map((s, i) => (
          <span key={s} className={cn(i === at && "font-semibold text-ink")}>
            {s}
          </span>
        ))}
      </div>
    </div>
  );
}

