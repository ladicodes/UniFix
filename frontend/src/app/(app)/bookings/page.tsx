"use client";

import Link from "next/link";
import { useState } from "react";
import { cn, money, timeAgo, usdc } from "@/lib/format";
import { useBookings } from "@/lib/hooks";
import { nextStep } from "@/lib/booking";
import type { BookingBundle } from "@/lib/types";
import { useSession } from "@/components/providers";
import { BookingBadge } from "@/components/status";
import { Avatar, Button, Empty, Panel, Skeleton } from "@/components/ui";

type Tab = "active" | "done" | "all";


export default function BookingsPage() {
  const { user } = useSession();
  const { data, isLoading } = useBookings(!!user);
  const [tab, setTab] = useState<Tab>("active");
  if (!user) return null;

  const isActive = (b: BookingBundle) => !["COMPLETED", "CANCELLED"].includes(b.booking.status);
  const list = (data ?? []).filter((b) => (tab === "all" ? true : tab === "active" ? isActive(b) : !isActive(b)));
  const held = (data ?? []).filter((b) => b.escrow && ["FUNDED", "DISPUTED"].includes(b.escrow.state)).reduce((s, b) => s + (b.escrow?.amount ?? 0), 0);
  const released = (data ?? []).filter((b) => b.escrow?.state === "RELEASED").reduce((s, b) => s + (b.escrow?.amount ?? 0), 0);
  const isPro = user.role === "professional";
  const actionCount = (data ?? []).filter((b) => nextStep(b, b.booking.customerId === user.id)).length;

  return (
    <div>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-semiwide text-3xl font-bold">Bookings</h1>
          <p className="mt-1 text-ink-3">{actionCount > 0 ? `${actionCount} need${actionCount === 1 ? "s" : ""} your attention` : "Nothing waiting on you"}</p>
        </div>
        {!isPro && (
          <Button href="/discover" variant="outline">
            Find a professional
          </Button>
        )}
      </div>

      {(held > 0 || released > 0) && (
        <p className="mt-6 flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <span className="font-wide tnum text-3xl font-bold">{usdc(held)}</span>
          <span className="text-ink-2">held in escrow right now</span>
          {released > 0 && (
            <span className="text-ink-3">
              and <span className="tnum font-semibold text-lagoon-ink">{usdc(released)}</span> {isPro ? "paid to you" : "released"} so far
            </span>
          )}
        </p>
      )}

      <div className="mt-8 flex gap-2" role="tablist">
        {(
          [
            ["active", "Active"],
            ["done", "Finished"],
            ["all", "All"],
          ] as const
        ).map(([v, l]) => (
          <button
            key={v}
            role="tab"
            aria-selected={tab === v}
            onClick={() => setTab(v)}
            className={cn("rounded-full px-4 py-2 text-sm font-semibold transition-colors", tab === v ? "bg-stellar text-white" : "bg-plaster text-ink-2 hover:bg-plaster-2")}
          >
            {l}
          </button>
        ))}
      </div>

      <div className="mt-4">
        {isLoading ? (
          <Panel className="space-y-4 py-6">
            <Skeleton className="h-14 w-full" />
            <Skeleton className="h-14 w-full" />
          </Panel>
        ) : list.length === 0 ? (
          <Empty
            title={tab === "active" ? "No active bookings" : "Nothing here yet"}
            body={isPro ? "When a customer accepts your quotation, the booking shows up here." : "Accept a quotation in chat and the booking appears here, ready to fund."}
            action={!isPro ? <Button href="/discover">Find a professional</Button> : undefined}
          />
        ) : (
          <Panel className="divide-y divide-line">
            {list.map((b) => {
              const isCustomer = b.booking.customerId === user.id;
              const other = isCustomer ? b.professional.name : b.customer.name;
              const step = nextStep(b, isCustomer);
              return (
                <Link key={b.booking.id} href={`/bookings/${b.booking.id}`} className="group grid grid-cols-[auto_1fr] gap-4 py-5 sm:grid-cols-[auto_1fr_auto]">
                  <Avatar name={other} size={44} />
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <BookingBadge status={b.booking.status} />
                      <span className="text-xs text-ink-3">{timeAgo(b.booking.timeline.at(-1)?.at ?? b.booking.createdAt)}</span>
                    </div>
                    <p className="mt-2 truncate font-semibold transition-colors group-hover:text-stellar">{b.booking.title}</p>
                    <p className="text-sm text-ink-3">{isCustomer ? `with ${other}` : `for ${other}`}</p>
                  </div>
                  <div className="col-span-2 flex items-center justify-between gap-4 sm:col-span-1 sm:flex-col sm:items-end sm:justify-center">
                    <span className="tnum font-semibold">{money(b.quote.total, b.quote.currency)}</span>
                    {step && <span className="rounded-full bg-stellar-soft px-3 py-1 text-xs font-semibold text-stellar-ink">{step}</span>}
                  </div>
                </Link>
              );
            })}
          </Panel>
        )}
      </div>
    </div>
  );
}
