"use client";

import Link from "next/link";
import { useState } from "react";
import { cn, money, timeAgo, usdc } from "@/lib/format";
import { useBookings } from "@/lib/hooks";
import { nextStep } from "@/lib/booking";
import type { BookingBundle } from "@/lib/types";
import { useSession } from "@/components/providers";
import { BookingBadge } from "@/components/status";
import { Avatar, Button, Empty, Skeleton } from "@/components/ui";
import { Track } from "@/components/job-track";
import { ArrowRight, Lock, Search } from "lucide-react";

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

  const counts = {
    active: (data ?? []).filter(isActive).length,
    done: (data ?? []).filter((b) => !isActive(b)).length,
    all: data?.length ?? 0,
  };

  return (
    <div>
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-semiwide text-3xl font-bold sm:text-4xl">Bookings</h1>
          <p className="mt-2 text-ink-2">{actionCount > 0 ? `${actionCount} need${actionCount === 1 ? "s" : ""} your attention.` : "Nothing is waiting on you."}</p>
        </div>
        {!isPro && (
          <Button href="/discover">
            <Search className="size-4" aria-hidden />
            Find a professional
          </Button>
        )}
      </header>

      <section className="mt-8 grid overflow-hidden rounded-2xl border border-line bg-paper shadow-xs sm:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)_minmax(0,1fr)]">
        <div className="relative p-6">
          <p className="flex items-center gap-2 text-sm text-ink-3">
            <Lock className="size-4 text-danfo-ink" aria-hidden />
            Held in escrow now
          </p>
          <p className="font-wide tnum mt-2 text-4xl font-bold">{usdc(held)}</p>
          <div className="hazard absolute inset-x-0 bottom-0 h-1.5" aria-hidden />
        </div>
        <div className="border-t border-line p-6 sm:border-l sm:border-t-0">
          <p className="text-sm text-ink-3">{isPro ? "Paid to you" : "Released"}</p>
          <p className="font-wide tnum mt-2 text-2xl font-bold text-lagoon-ink">{usdc(released)}</p>
        </div>
        <div className="border-t border-line p-6 sm:border-l sm:border-t-0">
          <p className="text-sm text-ink-3">Needs you</p>
          <p className="font-wide tnum mt-2 text-2xl font-bold">{actionCount}</p>
        </div>
      </section>

      <section className="mt-6 overflow-hidden rounded-2xl border border-line bg-paper shadow-xs">
        <div className="flex gap-6 border-b border-line px-5" role="tablist">
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
              className={cn(
                "relative flex items-center gap-2 py-4 text-sm font-semibold transition-colors",
                tab === v ? "text-ink after:absolute after:inset-x-0 after:-bottom-px after:h-0.5 after:rounded-full after:bg-ink" : "text-ink-3 hover:text-ink",
              )}
            >
              {l}
              <span className="tnum rounded-full bg-plaster px-2 py-0.5 text-xs text-ink-3">{counts[v]}</span>
            </button>
          ))}
        </div>

        {isLoading ? (
          <div className="space-y-4 p-5">
            <Skeleton className="h-14 w-full" />
            <Skeleton className="h-14 w-full" />
          </div>
        ) : list.length === 0 ? (
          <div className="p-5">
            <Empty
              title={tab === "active" ? "No active bookings" : "Nothing here yet"}
              body={isPro ? "When a customer accepts your quotation, the booking shows up here." : "Accept a quotation in chat and the booking appears here, ready to fund."}
              action={!isPro ? <Button href="/discover">Find a professional</Button> : undefined}
            />
          </div>
        ) : (
          <ul className="divide-y divide-line">
            {list.map((b) => {
              const isCustomer = b.booking.customerId === user.id;
              const other = isCustomer ? b.professional.name : b.customer.name;
              const step = nextStep(b, isCustomer);
              return (
                <li key={b.booking.id}>
                  <Link
                    href={`/bookings/${b.booking.id}`}
                    className="group grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-x-4 gap-y-3 px-5 py-4 transition-colors hover:bg-plaster lg:grid-cols-[auto_minmax(0,1fr)_12rem_8rem_11rem]"
                  >
                    <Avatar name={other} size={44} />
                    <span className="min-w-0">
                      <span className="block truncate font-semibold group-hover:text-stellar">{b.booking.title}</span>
                      <span className="mt-0.5 block truncate text-sm text-ink-3">
                        {isCustomer ? `with ${other}` : `for ${other}`} · updated {timeAgo(b.booking.timeline.at(-1)?.at ?? b.booking.createdAt)}
                      </span>
                    </span>
                    <span className="tnum text-right font-semibold lg:order-4">{money(b.quote.total, b.quote.currency)}</span>
                    <span className="col-span-3 lg:order-3 lg:col-span-1">
                      <Track status={b.booking.status} />
                    </span>
                    <span className="col-span-3 flex justify-start lg:order-5 lg:col-span-1 lg:justify-end">
                      {step ? (
                        <span className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-lg bg-stellar px-3 py-2 text-sm font-semibold text-white group-hover:bg-stellar-ink">
                          {step}
                          <ArrowRight className="size-4" aria-hidden />
                        </span>
                      ) : (
                        <BookingBadge status={b.booking.status} />
                      )}
                    </span>
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </div>
  );
}
