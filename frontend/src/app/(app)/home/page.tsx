"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ArrowRight, CheckCircle2, Lock, MessageCircle, Search, Star } from "lucide-react";
import { nextStep } from "@/lib/booking";
import { categoryLabel, cn, money, timeAgo, usdc } from "@/lib/format";
import { useBookings, useConversations, useProfessional, useProfessionals } from "@/lib/hooks";
import type { BookingBundle, BookingStatus, User } from "@/lib/types";
import { useSession } from "@/components/providers";
import { BookingBadge } from "@/components/status";
import { Avatar, Button, Card, Skeleton } from "@/components/ui";

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

function Track({ status }: { status: BookingStatus }) {
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

function JobRow({ b, user, action }: { b: BookingBundle; user: User; action?: string | null }) {
  const isCustomer = b.booking.customerId === user.id;
  const other = isCustomer ? b.professional.name : b.customer.name;
  return (
    <li>
      <Link href={`/bookings/${b.booking.id}`} className="group grid grid-cols-[auto_minmax(0,1fr)] items-center gap-x-4 gap-y-3 px-5 py-4 transition-colors hover:bg-plaster sm:grid-cols-[auto_minmax(0,1fr)_auto_auto]">
        <Avatar name={other} size={40} />
        <span className="min-w-0">
          <span className="block truncate font-semibold group-hover:text-stellar">{b.booking.title}</span>
          <span className="mt-0.5 block truncate text-sm text-ink-3">
            {isCustomer ? other : `For ${other}`} · <span className="tnum">{money(b.quote.total, b.quote.currency)}</span>
          </span>
        </span>
        <span className="col-span-2 sm:col-span-1 sm:w-48">
          <Track status={b.booking.status} />
        </span>
        <span className="col-span-2 flex justify-end sm:col-span-1">
          {action ? (
            <span className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-lg bg-stellar px-3 py-2 text-sm font-semibold text-white transition-colors group-hover:bg-stellar-ink">
              {action}
              <ArrowRight className="size-4" aria-hidden />
            </span>
          ) : (
            <BookingBadge status={b.booking.status} />
          )}
        </span>
      </Link>
    </li>
  );
}

function CardLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <Link href={href} className="text-sm font-semibold text-stellar hover:underline">
      {children}
    </Link>
  );
}

function cityOf(u: User) {
  const parts = u.city.split(",");
  return parts[parts.length - 1].trim();
}

function Recommended({ user }: { user: User }) {
  const city = cityOf(user);
  const { data } = useProfessionals({ city, sort: "best" });
  return (
    <Card title={`Top rated in ${city}`} action={<CardLink href={`/discover?city=${encodeURIComponent(city)}`}>See all</CardLink>}>
      <ul className="divide-y divide-line">
        {!data
          ? [0, 1, 2].map((i) => (
              <li key={i} className="px-5 py-3">
                <Skeleton className="h-10" />
              </li>
            ))
          : data.slice(0, 4).map((p) => (
              <li key={p.id}>
                <Link href={`/pros/${p.id}`} className="group flex items-center gap-3 px-5 py-3 transition-colors hover:bg-plaster">
                  <Avatar name={p.name} size={36} />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-semibold group-hover:text-stellar">{p.name}</span>
                    <span className="block truncate text-sm text-ink-3">
                      {categoryLabel(p.category)} in {p.area}
                    </span>
                  </span>
                  <span className="tnum inline-flex items-center gap-1 text-sm font-semibold">
                    <Star className="size-4 text-danfo-ink" fill="var(--color-danfo)" strokeWidth={1.5} aria-hidden />
                    {p.rating.toFixed(1)}
                  </span>
                </Link>
              </li>
            ))}
      </ul>
    </Card>
  );
}

function ProStanding({ user }: { user: User }) {
  const { data: p } = useProfessional(user.professionalId ?? "");
  if (!p) return <Skeleton className="h-40 w-full rounded-2xl" />;
  return (
    <Card title="Your standing" action={<CardLink href={`/pros/${p.id}`}>Public profile</CardLink>}>
      <dl className="grid grid-cols-3 divide-x divide-line">
        {[
          { v: p.reviewCount ? p.rating.toFixed(1) : "–", l: `${p.reviewCount} reviews` },
          { v: String(p.completedJobs), l: "jobs done" },
          { v: `${p.responseMinutes}m`, l: "typical reply" },
        ].map((x) => (
          <div key={x.l} className="flex flex-col-reverse px-5 py-4">
            <dt className="text-sm text-ink-3">{x.l}</dt>
            <dd className="font-wide tnum text-2xl font-bold">{x.v}</dd>
          </div>
        ))}
      </dl>
    </Card>
  );
}

function MoneyCard({ held, released, heldList, isPro }: { held: number; released: number; heldList: BookingBundle[]; isPro: boolean }) {
  return (
    <Card title="Money" action={<CardLink href="/wallet">Wallet</CardLink>}>
      <div className="px-5 py-5">
        <p className="text-sm text-ink-3">Held in escrow</p>
        <p className="font-wide tnum mt-1 text-4xl font-bold">{usdc(held)}</p>
        <p className="mt-1 text-sm text-ink-3">
          across {heldList.length} booking{heldList.length === 1 ? "" : "s"} ·{" "}
          <span className="tnum font-semibold text-lagoon-ink">{usdc(released)}</span> {isPro ? "paid to you" : "released"} so far
        </p>
      </div>
      {heldList.length > 0 && (
        <>
          <div className="hazard h-2" aria-hidden />
          <ul className="divide-y divide-danfo-ink/15 bg-danfo-soft">
            {heldList.map((b) => (
              <li key={b.booking.id}>
                <Link href={`/bookings/${b.booking.id}`} className="flex items-center gap-3 px-5 py-3 text-sm hover:underline">
                  <Lock className="size-4 shrink-0 text-danfo-ink" aria-hidden />
                  <span className="min-w-0 flex-1 truncate">{b.booking.title}</span>
                  <span className="tnum font-semibold">{usdc(b.escrow!.amount)}</span>
                </Link>
              </li>
            ))}
          </ul>
        </>
      )}
    </Card>
  );
}

export default function HomePage() {
  const router = useRouter();
  const { user } = useSession();
  const { data: bookings, isLoading } = useBookings(!!user && user.role !== "admin");
  const { data: convos } = useConversations(!!user && user.role !== "admin");
  const [today, setToday] = useState("");

  useEffect(() => {
    if (user?.role === "admin") router.replace("/admin");
  }, [user, router]);
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- date depends on the viewer's clock, set after mount
    setToday(new Date().toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" }));
  }, []);

  if (!user || user.role === "admin") return null;
  const isPro = user.role === "professional";
  const all = bookings ?? [];
  const mine = (b: BookingBundle) => b.booking.customerId === user.id;
  const needs = all.filter((b) => nextStep(b, mine(b)));
  const active = all.filter((b) => !nextStep(b, mine(b)) && !["COMPLETED", "CANCELLED"].includes(b.booking.status));
  const heldList = all.filter((b) => b.escrow && ["FUNDED", "DISPUTED"].includes(b.escrow.state));
  const held = heldList.reduce((s, b) => s + (b.escrow?.amount ?? 0), 0);
  const released = all.filter((b) => b.escrow?.state === "RELEASED").reduce((s, b) => s + (b.escrow?.amount ?? 0), 0);
  const unread = (convos ?? []).filter((c) => c.unread).length;

  return (
    <div>
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-sm text-ink-3">{today || " "}</p>
          <h1 className="font-semiwide mt-1 text-3xl font-bold sm:text-4xl">{isPro ? "Your work" : "Your jobs"}</h1>
          <p className="mt-2 text-ink-2">
            {needs.length
              ? `${needs.length} ${needs.length === 1 ? "booking needs" : "bookings need"} you, ${active.length} in progress.`
              : active.length
                ? `Nothing needs you. ${active.length} in progress.`
                : "Nothing needs you right now."}
          </p>
        </div>
        {!isPro && (
          <Button href="/discover">
            <Search className="size-4" aria-hidden />
            Find a professional
          </Button>
        )}
      </header>

      <div className="mt-8 grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_24rem]">
        <div className="min-w-0 space-y-6">
          <Card
            title={
              <span className="flex items-center gap-2">
                Needs you
                {!!needs.length && <span className="tnum grid h-6 min-w-6 place-items-center rounded-full bg-stellar px-2 text-xs text-white">{needs.length}</span>}
              </span>
            }
          >
            {isLoading ? (
              <div className="p-5">
                <Skeleton className="h-16 w-full" />
              </div>
            ) : needs.length ? (
              <ul className="divide-y divide-line">
                {needs.map((b) => (
                  <JobRow key={b.booking.id} b={b} user={user} action={nextStep(b, mine(b))} />
                ))}
              </ul>
            ) : (
              <p className="flex items-center gap-3 px-5 py-6 text-ink-2">
                <CheckCircle2 className="size-5 text-lagoon" aria-hidden />
                You&apos;re all caught up.
              </p>
            )}
          </Card>

          <Card title="In progress" action={<CardLink href="/bookings">All bookings</CardLink>}>
            {active.length ? (
              <ul className="divide-y divide-line">
                {active.map((b) => (
                  <JobRow key={b.booking.id} b={b} user={user} />
                ))}
              </ul>
            ) : (
              <p className="px-5 py-6 text-ink-3">
                {isPro ? "No jobs running. New bookings appear when customers accept your quotations." : "No jobs running."}
              </p>
            )}
          </Card>

          <Card
            title={
              <span className="flex items-center gap-2">
                Messages
                {!!unread && <span className="tnum rounded-full bg-stellar-soft px-2 py-0.5 text-xs font-semibold text-stellar-ink">{unread} unread</span>}
              </span>
            }
            action={<CardLink href="/messages">All messages</CardLink>}
          >
            <ul className="divide-y divide-line">
              {(convos ?? []).slice(0, 4).map(({ conversation: c, professional, customer, unread }) => {
                const other = c.customerId === user.id ? professional.name : customer.name;
                return (
                  <li key={c.id}>
                    <Link href={`/messages/${c.id}`} className="group flex items-center gap-4 px-5 py-3.5 transition-colors hover:bg-plaster">
                      <Avatar name={other} size={36} />
                      <span className="min-w-0 flex-1">
                        <span className={cn("block truncate group-hover:text-stellar", unread ? "font-semibold" : "font-normal")}>{other}</span>
                        <span className={cn("block truncate text-sm", unread ? "text-ink-2" : "text-ink-3")}>{c.lastMessagePreview}</span>
                      </span>
                      <span className="shrink-0 text-xs text-ink-3">{timeAgo(c.lastMessageAt)}</span>
                      {unread && <span className="size-2 shrink-0 rounded-full bg-stellar" aria-label="Unread" />}
                    </Link>
                  </li>
                );
              })}
              {convos?.length === 0 && (
                <li className="flex items-center gap-3 px-5 py-6 text-ink-3">
                  <MessageCircle className="size-5" aria-hidden />
                  No conversations yet.
                </li>
              )}
            </ul>
          </Card>
        </div>

        <aside className="min-w-0 space-y-6">
          <MoneyCard held={held} released={released} heldList={heldList} isPro={isPro} />
          {isPro ? <ProStanding user={user} /> : <Recommended user={user} />}
        </aside>
      </div>
    </div>
  );
}
