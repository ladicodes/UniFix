"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Lock, Star } from "lucide-react";
import { nextStep } from "@/lib/booking";
import { categoryLabel, cn, money, timeAgo, usdc } from "@/lib/format";
import { useBookings, useConversations, useProfessional, useProfessionals } from "@/lib/hooks";
import type { BookingBundle, User } from "@/lib/types";
import { useSession } from "@/components/providers";
import { BookingBadge } from "@/components/status";
import { Avatar, Button, Panel, Skeleton, Surface } from "@/components/ui";

function SectionHead({ title, href, link }: { title: string; href?: string; link?: string }) {
  return (
    <div className="mb-3 flex items-baseline justify-between gap-4">
      <h2 className="text-lg font-semibold">{title}</h2>
      {href && (
        <Link href={href} className="text-sm font-semibold text-stellar hover:underline">
          {link}
        </Link>
      )}
    </div>
  );
}

function BookingLine({ b, user, action }: { b: BookingBundle; user: User; action?: string | null }) {
  const isCustomer = b.booking.customerId === user.id;
  const other = isCustomer ? b.professional.name : b.customer.name;
  return (
    <Link href={`/bookings/${b.booking.id}`} className="group flex items-center gap-4 py-4">
      <Avatar name={other} size={40} />
      <div className="min-w-0 flex-1">
        <p className="truncate font-semibold transition-colors group-hover:text-stellar">{b.booking.title}</p>
        <p className="truncate text-sm text-ink-3">
          {isCustomer ? other : `For ${other}`}, {money(b.quote.total, b.quote.currency)}
        </p>
        {action && <p className="mt-1 text-sm font-semibold text-stellar sm:hidden">{action}</p>}
      </div>
      {action ? (
        <span className="shrink-0 rounded-lg bg-stellar px-3 py-2 text-sm font-semibold text-white max-sm:hidden">{action}</span>
      ) : (
        <BookingBadge status={b.booking.status} />
      )}
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
      <SectionHead title={`Top rated in ${city}`} href={`/discover?city=${encodeURIComponent(city)}`} link="See all" />
      <Panel className="divide-y divide-line">
        {!data
          ? [0, 1, 2].map((i) => <Skeleton key={i} className="my-4 h-10" />)
          : data.slice(0, 4).map((p) => (
              <Link key={p.id} href={`/pros/${p.id}`} className="group flex items-center gap-3 py-3">
                <Avatar name={p.name} size={36} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-semibold transition-colors group-hover:text-stellar">{p.name}</span>
                  <span className="block truncate text-sm text-ink-3">
                    {categoryLabel(p.category)} in {p.area}
                  </span>
                </span>
                <span className="tnum inline-flex items-center gap-1 text-sm font-semibold">
                  <Star className="size-4 text-danfo-ink" fill="var(--color-danfo)" strokeWidth={1.5} aria-hidden />
                  {p.rating.toFixed(1)}
                </span>
              </Link>
            ))}
      </Panel>
    </section>
  );
}

function ProStanding({ user }: { user: User }) {
  const { data: p } = useProfessional(user.professionalId ?? "");
  if (!p) return <Skeleton className="h-40 w-full" />;
  return (
    <section>
      <SectionHead title="Your standing" href={`/pros/${p.id}`} link="Public profile" />
      <dl className="grid grid-cols-3 gap-4 border-t border-line pt-4">
        {[
          { v: p.reviewCount ? p.rating.toFixed(1) : "–", l: `from ${p.reviewCount} reviews` },
          { v: String(p.completedJobs), l: "jobs done" },
          { v: `${p.responseMinutes} min`, l: "typical reply" },
        ].map((x) => (
          <div key={x.l}>
            <dd className="tnum text-2xl font-semibold">{x.v}</dd>
            <dt className="text-sm text-ink-3">{x.l}</dt>
          </div>
        ))}
      </dl>
    </section>
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

  return (
    <div>
      <p className="text-sm text-ink-3">{today}</p>
      <h1 className="font-semiwide mt-1 text-3xl font-bold">{isPro ? "Your work" : "Your jobs"}</h1>

      <div className="mt-8 grid grid-cols-1 gap-10 xl:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <div className="min-w-0 space-y-10">
          <section>
            <SectionHead title={needs.length ? `Needs you (${needs.length})` : "Needs you"} />
            {isLoading ? (
              <Skeleton className="h-32 w-full" />
            ) : needs.length ? (
              <Panel className="divide-y divide-line">
                {needs.map((b) => (
                  <BookingLine key={b.booking.id} b={b} user={user} action={nextStep(b, mine(b))} />
                ))}
              </Panel>
            ) : (
              <p className="border-t border-line py-4 text-ink-3">Nothing needs you right now.</p>
            )}
          </section>

          <section>
            <SectionHead title="In progress" href="/bookings" link="All bookings" />
            {active.length ? (
              <Panel className="divide-y divide-line">
                {active.map((b) => (
                  <BookingLine key={b.booking.id} b={b} user={user} />
                ))}
              </Panel>
            ) : (
              <p className="border-t border-line py-4 text-ink-3">
                {isPro ? "No jobs running. New bookings appear when customers accept your quotations." : "No jobs running."}
                {!isPro && (
                  <Link href="/discover" className="ml-1 font-semibold text-stellar hover:underline">
                    Find a professional
                  </Link>
                )}
              </p>
            )}
          </section>

          <section>
            <SectionHead title="Recent messages" href="/messages" link="All messages" />
            <Panel className="divide-y divide-line">
              {(convos ?? []).slice(0, 4).map(({ conversation: c, professional, customer, unread }) => {
                const other = c.customerId === user.id ? professional.name : customer.name;
                return (
                  <Link key={c.id} href={`/messages/${c.id}`} className="group flex items-center gap-4 py-3">
                    <Avatar name={other} size={36} />
                    <span className="min-w-0 flex-1">
                      <span className={cn("block truncate transition-colors group-hover:text-stellar", unread ? "font-semibold" : "font-normal")}>{other}</span>
                      <span className="block truncate text-sm text-ink-3">{c.lastMessagePreview}</span>
                    </span>
                    <span className="shrink-0 text-xs text-ink-3">{timeAgo(c.lastMessageAt)}</span>
                    {unread && <span className="size-2 shrink-0 rounded-full bg-stellar" aria-label="Unread" />}
                  </Link>
                );
              })}
              {convos?.length === 0 && <p className="py-4 text-ink-3">No conversations yet.</p>}
            </Panel>
          </section>
        </div>

        <aside className="min-w-0 space-y-10">
          <section>
            <SectionHead title="Money" />
            <Surface className="overflow-hidden">
              <div className="p-5">
                <p className="font-wide tnum text-3xl font-bold">{usdc(held)}</p>
                <p className="text-ink-2">held in escrow across {heldList.length} booking{heldList.length === 1 ? "" : "s"}</p>
                <p className="mt-3 text-sm text-ink-3">
                  <span className="tnum font-semibold text-lagoon-ink">{usdc(released)}</span> {isPro ? "paid to you" : "released"} on UniFix so far
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
            </Surface>
          </section>

          {isPro ? <ProStanding user={user} /> : <Recommended user={user} />}

          {!isPro && (
            <Button href="/discover" variant="outline" className="w-full">
              Find a professional
            </Button>
          )}
        </aside>
      </div>
    </div>
  );
}
