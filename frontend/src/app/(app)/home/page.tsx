"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ArrowRight, CheckCircle2, Lock, MessageCircle, Search, Star } from "lucide-react";
import { nextStep } from "@/lib/booking";
import { categoryLabel, cn, money, timeAgo, usdc } from "@/lib/format";
import { useBookings, useConversations, useProfessional, useProfessionals } from "@/lib/hooks";
import type { BookingBundle, User } from "@/lib/types";
import { useSession } from "@/components/providers";
import { BookingBadge } from "@/components/status";
import { Track } from "@/components/job-track";
import { Avatar, Button, Card, Skeleton } from "@/components/ui";

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
    <section>
      <div className="mb-4 flex items-baseline justify-between gap-4">
        <h2 className="text-lg font-semibold">Top rated in {city}</h2>
        <CardLink href={`/discover?city=${encodeURIComponent(city)}`}>See all</CardLink>
      </div>
      <ul className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {!data
          ? [0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-32 rounded-2xl" />)
          : data.slice(0, 4).map((p) => (
              <li key={p.id}>
                <Link href={`/pros/${p.id}`} className="group flex h-full flex-col rounded-2xl border border-line bg-paper p-5 shadow-xs transition hover:-translate-y-0.5 hover:shadow-lift">
                  <span className="flex items-center gap-3">
                    <Avatar name={p.name} size={44} />
                    <span className="min-w-0">
                      <span className="block truncate font-semibold group-hover:text-stellar">{p.name}</span>
                      <span className="block truncate text-sm text-ink-3">
                        {categoryLabel(p.category)} · {p.area}
                      </span>
                    </span>
                  </span>
                  <span className="mt-4 flex items-center justify-between text-sm">
                    <span className="tnum inline-flex items-center gap-1 font-semibold">
                      <Star className="size-4 text-danfo-ink" fill="var(--color-danfo)" strokeWidth={1.5} aria-hidden />
                      {p.rating.toFixed(1)} <span className="font-normal text-ink-3">({p.reviewCount})</span>
                    </span>
                    <span className="tnum text-ink-3">
                      From <span className="font-semibold text-ink">{money(p.startingPrice, p.currency)}</span>
                    </span>
                  </span>
                </Link>
              </li>
            ))}
      </ul>
    </section>
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
    <div className="space-y-6">
      <section className="relative overflow-hidden rounded-2xl bg-ink text-white">
        <div className="grid gap-8 p-6 sm:p-8 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-end lg:p-10">
          <div>
            <p className="text-sm text-mist">{today || " "}</p>
            <h1 className="font-semiwide mt-1 text-3xl font-bold sm:text-4xl">{isPro ? "Your work" : "Your jobs"}</h1>
            <p className="mt-2 text-mist">
              {needs.length
                ? `${needs.length} ${needs.length === 1 ? "booking needs" : "bookings need"} you, ${active.length} in progress.`
                : active.length
                  ? `Nothing needs you. ${active.length} in progress.`
                  : "Nothing needs you right now."}
            </p>
            <div className="mt-6 flex flex-wrap gap-2">
              {isPro ? (
                <Button href="/messages" variant="accent">
                  <MessageCircle className="size-4" aria-hidden />
                  Open messages
                </Button>
              ) : (
                <Button href="/discover" variant="accent">
                  <Search className="size-4" aria-hidden />
                  Find a professional
                </Button>
              )}
              <Button href="/bookings" variant="outline" className="border-mist-2 bg-transparent text-white hover:bg-ink-2">
                All bookings
              </Button>
            </div>
          </div>
          <dl className="grid grid-cols-2 gap-x-10 gap-y-4 lg:text-right">
            <div className="col-span-2">
              <dt className="flex items-center gap-2 text-sm text-mist lg:justify-end">
                <Lock className="size-4 text-danfo" aria-hidden />
                Held in escrow
              </dt>
              <dd className="font-wide tnum mt-1 text-4xl font-bold sm:text-5xl">{usdc(held)}</dd>
            </div>
            <div>
              <dt className="text-sm text-mist">{isPro ? "Paid to you" : "Released"}</dt>
              <dd className="tnum mt-0.5 text-lg font-semibold">{usdc(released)}</dd>
            </div>
            <div>
              <dt className="text-sm text-mist">Bookings held</dt>
              <dd className="tnum mt-0.5 text-lg font-semibold">{heldList.length}</dd>
            </div>
          </dl>
        </div>
        {heldList.length > 0 && <div className="hazard h-2 animate-stripe" aria-hidden />}
      </section>

      <section>
        <div className="mb-4 flex items-center gap-2">
          <h2 className="text-lg font-semibold">Needs you</h2>
          {!!needs.length && <span className="tnum grid h-6 min-w-6 place-items-center rounded-full bg-stellar px-2 text-xs font-semibold text-white">{needs.length}</span>}
        </div>
        {isLoading ? (
          <Skeleton className="h-40 w-full rounded-2xl" />
        ) : needs.length ? (
          <ul className="grid gap-4 md:grid-cols-2 2xl:grid-cols-3">
            {needs.map((b) => {
              const isCustomer = mine(b);
              const other = isCustomer ? b.professional.name : b.customer.name;
              return (
                <li key={b.booking.id}>
                  <Link
                    href={`/bookings/${b.booking.id}`}
                    className="group flex h-full flex-col rounded-2xl border border-line bg-paper p-5 shadow-xs transition hover:-translate-y-0.5 hover:border-stellar hover:shadow-lift"
                  >
                    <span className="flex items-center gap-3">
                      <Avatar name={other} size={40} />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-semibold">{other}</span>
                        <span className="block text-sm text-ink-3">{isCustomer ? categoryLabel(b.professional.category) : "Customer"}</span>
                      </span>
                      <span className="font-wide tnum text-lg font-bold">{money(b.quote.total, b.quote.currency)}</span>
                    </span>
                    <span className="mt-4 line-clamp-2 font-semibold leading-snug group-hover:text-stellar">{b.booking.title}</span>
                    <span className="mt-4 block">
                      <Track status={b.booking.status} />
                    </span>
                    <span className="mt-5 inline-flex items-center justify-center gap-1.5 rounded-xl bg-stellar px-4 py-3 text-sm font-semibold text-white transition-colors group-hover:bg-stellar-ink">
                      {nextStep(b, isCustomer)}
                      <ArrowRight className="size-4" aria-hidden />
                    </span>
                  </Link>
                </li>
              );
            })}
          </ul>
        ) : (
          <p className="flex items-center gap-3 rounded-2xl border border-line bg-paper px-5 py-6 text-ink-2 shadow-xs">
            <CheckCircle2 className="size-5 text-lagoon" aria-hidden />
            You&apos;re all caught up.
          </p>
        )}
      </section>

      <div className="grid gap-6 xl:grid-cols-2">
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

      {isPro ? <ProStanding user={user} /> : <Recommended user={user} />}
    </div>
  );
}
