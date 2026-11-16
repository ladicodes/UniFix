import Link from "next/link";
import { BadgeCheck, Star } from "lucide-react";
import { categoryLabel, cn, money } from "@/lib/format";
import type { Professional } from "@/lib/types";
import { Avatar } from "./ui";

export const AVAILABILITY: Record<Professional["availability"], { label: string; cls: string }> = {
  now: { label: "Available now", cls: "text-lagoon" },
  today: { label: "Available today", cls: "text-ink-2" },
  "this-week": { label: "This week", cls: "text-ink-3" },
  unavailable: { label: "Not taking jobs", cls: "text-ink-3" },
};

export function VerifiedMark({ p, className }: { p: Professional; className?: string }) {
  const full = p.verification.identity && p.verification.trade;
  if (!p.verification.identity) return null;
  return (
    <BadgeCheck
      className={cn("size-[18px] shrink-0", full ? "text-lagoon" : "text-ink-3", className)}
      aria-label={full ? "ID and trade verified" : "ID verified"}
    />
  );
}

export function ProRow({ p }: { p: Professional }) {
  const a = AVAILABILITY[p.availability];
  return (
    <Link
      href={`/pros/${p.id}`}
      className="group grid grid-cols-[auto_1fr] gap-x-4 gap-y-3 py-5 sm:grid-cols-[auto_1fr_auto]"
    >
      <Avatar name={p.name} size={48} />
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <h3 className="truncate text-lg font-semibold transition-colors group-hover:text-stellar">{p.name}</h3>
          <VerifiedMark p={p} />
        </div>
        <p className="text-sm text-ink-3">
          {categoryLabel(p.category)} in {p.area}, {p.city}
        </p>
        <p className="mt-2 line-clamp-1 text-base text-ink-2">{p.headline}</p>
        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
          {p.reviewCount > 0 ? (
            <span className="inline-flex items-center gap-1">
              <Star className="size-4 text-danfo-ink" fill="var(--color-danfo)" strokeWidth={1.5} aria-hidden />
              <span className="tnum font-semibold">{p.rating.toFixed(1)}</span>
              <span className="text-ink-3">from {p.reviewCount} reviews</span>
            </span>
          ) : (
            <span className="text-ink-3">No reviews yet</span>
          )}
          <span className="tnum text-ink-3">{p.completedJobs} jobs done</span>
        </div>
      </div>
      <div className="col-span-2 flex items-center justify-between gap-4 pt-1 sm:col-span-1 sm:flex-col sm:items-end sm:justify-start sm:border-0 sm:pt-0">
        <p className="text-sm text-ink-3">
          From <span className="tnum font-semibold text-ink">{money(p.startingPrice, p.currency)}</span>
        </p>
        <p className={cn("inline-flex items-center gap-1 text-sm font-semibold", a.cls)}>
          {a.label}
        </p>
      </div>
    </Link>
  );
}
