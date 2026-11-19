"use client";

import Link from "next/link";
import { useState } from "react";
import { BadgeCheck, Check, CircleDashed, Mail, MapPin, UserRound } from "lucide-react";
import { api } from "@/lib/api";
import { categoryLabel, money, shortAddress } from "@/lib/format";
import { useBookings, useProfessional } from "@/lib/hooks";
import type { Professional, User } from "@/lib/types";
import { useSession, useToast, useWallet } from "@/components/providers";
import { BookingBadge } from "@/components/status";
import { Avatar, Button, ChipInput, ErrorNote, Field, Input, Segmented, Skeleton, Textarea } from "@/components/ui";

function SaveButton({ dirty, busy, label }: { dirty: boolean; busy: boolean; label: string }) {
  return dirty ? (
    <Button type="submit" loading={busy}>
      {label}
    </Button>
  ) : (
    <span className="inline-flex h-11 items-center gap-2 text-sm text-ink-3">
      <Check className="size-4 text-lagoon" aria-hidden />
      All changes saved
    </span>
  );
}

function AccountForm({ user }: { user: User }) {
  const { refresh } = useSession();
  const toast = useToast();
  const [v, setV] = useState({ name: user.name, city: user.city });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const dirty = v.name !== user.name || v.city !== user.city;

  return (
    <form
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        setError(null);
        try {
          await api.updateMe(v);
          await refresh();
          toast({ title: "Account details saved", tone: "ok" });
        } catch (err) {
          setError(err);
        } finally {
          setBusy(false);
        }
      }}
      className="grid grid-cols-1 gap-5 sm:grid-cols-2"
    >
      <Field label="Full name">{(id) => <Input id={id} icon={UserRound} required autoComplete="name" value={v.name} onChange={(e) => setV({ ...v, name: e.target.value })} />}</Field>
      <Field label="Area and city" hint="Shown to professionals you message.">
        {(id, d) => <Input id={id} icon={MapPin} aria-describedby={d} required value={v.city} onChange={(e) => setV({ ...v, city: e.target.value })} />}
      </Field>
      <Field label="Sign-in email" className="sm:col-span-2" hint="To change it, contact UniFix support.">
        {(id, d) => <Input id={id} icon={Mail} aria-describedby={d} value={user.email} disabled readOnly />}
      </Field>
      <div className="sm:col-span-2">
        <ErrorNote error={error} />
        <SaveButton dirty={dirty} busy={busy} label="Save account details" />
      </div>
    </form>
  );
}

function ProfessionalForm({ p }: { p: Professional }) {
  const toast = useToast();
  const initial = {
    headline: p.headline,
    bio: p.bio,
    area: p.area,
    availability: p.availability,
    startingPrice: p.startingPrice,
    skills: p.skills,
    coverage: p.coverage,
  };
  const [v, setV] = useState(initial);
  const [saved, setSaved] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const dirty = JSON.stringify(v) !== JSON.stringify(saved);

  return (
    <form
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        setError(null);
        try {
          await api.updateProfessional(p.id, v);
          setSaved(v);
          toast({ title: "Public profile saved", body: "Customers see the changes right away.", tone: "ok" });
        } catch (err) {
          setError(err);
        } finally {
          setBusy(false);
        }
      }}
      className="grid grid-cols-1 gap-5 sm:grid-cols-2"
    >
      <Field label="Headline" className="sm:col-span-2" hint="One line about what you do best.">
        {(id) => <Input id={id} required maxLength={90} value={v.headline} onChange={(e) => setV({ ...v, headline: e.target.value })} />}
      </Field>
      <Field label="About your work" className="sm:col-span-2">
        {(id) => <Textarea id={id} required maxLength={600} value={v.bio} onChange={(e) => setV({ ...v, bio: e.target.value })} />}
      </Field>
      <Field label="Base area">{(id) => <Input id={id} required value={v.area} onChange={(e) => setV({ ...v, area: e.target.value })} />}</Field>
      <Field label="Starting price">
        {(id) => (
          <Input
            id={id}
            type="number"
            min={0}
            value={v.startingPrice}
            onChange={(e) => setV({ ...v, startingPrice: Number(e.target.value) })}
            trailing={<span className="px-2 text-sm font-semibold text-ink-3">{p.currency}</span>}
          />
        )}
      </Field>
      <div className="flex flex-col gap-2 sm:col-span-2">
        <span className="text-sm font-semibold">Availability</span>
        <Segmented
          label="Availability"
          value={v.availability}
          onChange={(availability) => setV({ ...v, availability })}
          options={[
            { value: "now", label: "Now" },
            { value: "today", label: "Today" },
            { value: "this-week", label: "This week" },
            { value: "unavailable", label: "Paused" },
          ]}
        />
      </div>
      <Field label="Areas you cover" className="sm:col-span-2" hint="Press Enter after each one.">
        {(id, d) => <ChipInput id={id} describedBy={d} value={v.coverage} onChange={(coverage) => setV({ ...v, coverage })} />}
      </Field>
      <Field label="Skills" className="sm:col-span-2" hint="Press Enter after each one.">
        {(id, d) => <ChipInput id={id} describedBy={d} value={v.skills} onChange={(skills) => setV({ ...v, skills })} />}
      </Field>
      <div className="sm:col-span-2">
        <ErrorNote error={error} />
        <SaveButton dirty={dirty} busy={busy} label="Save public profile" />
      </div>
    </form>
  );
}

function Section({ title, body, children }: { title: string; body?: string; children: React.ReactNode }) {
  return (
    <section className="grid gap-6 rounded-2xl border border-line bg-paper p-6 shadow-xs lg:grid-cols-[16rem_minmax(0,1fr)] lg:gap-10 lg:p-8">
      <div>
        <h2 className="text-lg font-semibold">{title}</h2>
        {body && <p className="mt-1 text-sm leading-relaxed text-ink-3">{body}</p>}
      </div>
      <div className="min-w-0">{children}</div>
    </section>
  );
}

export default function ProfilePage() {
  const { user } = useSession();
  const w = useWallet();
  const pro = useProfessional(user?.professionalId ?? "");
  const { data: bookings } = useBookings(!!user && user.role !== "admin");
  if (!user) return <Skeleton className="h-64 w-full" />;
  const p = user.professionalId ? pro.data : undefined;

  const all = bookings ?? [];
  const active = all.filter((b) => !["COMPLETED", "CANCELLED"].includes(b.booking.status)).length;
  const done = all.filter((b) => b.booking.status === "COMPLETED").length;
  const held = all.filter((b) => b.escrow && ["FUNDED", "DISPUTED"].includes(b.escrow.state)).reduce((s, b) => s + (b.escrow?.amount ?? 0), 0);
  const linked = !!w.address && user.walletAddress === w.address && user.walletVerified;

  return (
    <div>
      <header className="overflow-hidden rounded-2xl border border-line bg-paper shadow-xs">
        <div className="h-28 bg-ink" aria-hidden />
        <div className="flex flex-col gap-6 px-6 pb-6 lg:flex-row lg:items-end lg:justify-between lg:px-8">
          <div className="-mt-10 flex items-end gap-5">
            <Avatar name={user.name} size={96} className="ring-4 ring-paper" />
            <div className="pb-1">
              <div className="flex flex-wrap items-center gap-2">
                <h1 className="font-semiwide text-3xl font-bold">{user.name}</h1>
                <span className="rounded-full bg-stellar-soft px-2.5 py-0.5 text-xs font-semibold capitalize text-stellar-ink">{user.role}</span>
              </div>
              <p className="mt-1 flex items-center gap-1.5 text-ink-2">
                <MapPin className="size-4 text-ink-3" aria-hidden />
                {p ? `${categoryLabel(p.category)} in ` : ""}
                {user.city}
              </p>
            </div>
          </div>
          {user.role !== "admin" && (
            <dl className="grid grid-cols-3 divide-x divide-line rounded-xl border border-line">
              {[
                { v: String(active), l: "Active jobs" },
                { v: String(done), l: "Completed" },
                p ? { v: p.reviewCount ? p.rating.toFixed(1) : "–", l: `Rating (${p.reviewCount})` } : { v: held.toFixed(2), l: "USDC held" },
              ].map((x) => (
                <div key={x.l} className="flex flex-col-reverse px-5 py-3">
                  <dt className="text-xs text-ink-3">{x.l}</dt>
                  <dd className="font-wide tnum text-2xl font-bold">{x.v}</dd>
                </div>
              ))}
            </dl>
          )}
        </div>
      </header>

      <div className="mt-6 grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_24rem]">
        <div className="min-w-0 space-y-6">
          <Section title="Account" body="Your name and area. Professionals see these when you message them.">
            <AccountForm key={`${user.name}${user.city}`} user={user} />
          </Section>

          {user.professionalId && (
            <Section title="Public profile" body="What customers see when they compare professionals.">
              {p ? <ProfessionalForm key={p.id} p={p} /> : <Skeleton className="h-64 w-full" />}
            </Section>
          )}

          {p && (
            <Section title="Verification" body="UniFix operations checks these documents. They are never shown publicly; customers only see the result.">
              <ul className="divide-y divide-line">
                {[
                  { ok: p.verification.identity, label: "Government ID" },
                  { ok: p.verification.trade, label: "Trade certificate" },
                  { ok: p.verification.phone, label: "Phone number" },
                ].map((r) => (
                  <li key={r.label} className="flex items-center gap-3 py-3">
                    {r.ok ? <BadgeCheck className="size-5 text-lagoon" aria-hidden /> : <CircleDashed className="size-5 text-ink-4" aria-hidden />}
                    <span className="flex-1">{r.label}</span>
                    <span className={r.ok ? "text-sm font-semibold text-lagoon-ink" : "text-sm text-ink-3"}>{r.ok ? "Checked" : "Not checked yet"}</span>
                  </li>
                ))}
              </ul>
            </Section>
          )}
        </div>

        {user.role !== "admin" && (
          <aside className="space-y-6 xl:sticky xl:top-24 xl:self-start">
            <section className="rounded-2xl border border-line bg-paper p-5 shadow-xs">
              <h2 className="font-semibold">Stellar wallet</h2>
              <p className="mt-1 text-sm text-ink-3">
                {user.role === "professional" ? "Released payments are sent here." : "You fund escrow from this wallet."}
              </p>
              <p className="tnum mt-4 font-semibold">{w.address ? shortAddress(w.address) : "No wallet connected"}</p>
              <p className="flex items-center gap-2 text-sm text-ink-2">
                <span className={linked ? "size-2 rounded-full bg-lagoon" : "size-2 rounded-full bg-ink-4"} aria-hidden />
                {linked ? "Linked and ownership verified" : w.address ? "Connected, not linked to your account yet" : "Connect Freighter to pay or get paid"}
              </p>
              <Button href="/wallet" variant={w.address ? "outline" : "primary"} className="mt-4 w-full">
                {w.address ? "Manage wallet" : "Connect wallet"}
              </Button>
            </section>

            <section className="rounded-2xl border border-line bg-paper px-5 pt-5 shadow-xs">
              <div className="flex items-baseline justify-between">
                <h2 className="font-semibold">Recent bookings</h2>
                <Link href="/bookings" className="text-sm font-semibold text-stellar hover:underline">
                  All bookings
                </Link>
              </div>
              <ul className="mt-3 divide-y divide-line border-t border-line">
                {all.slice(0, 4).map((b) => (
                  <li key={b.booking.id}>
                    <Link href={`/bookings/${b.booking.id}`} className="block py-3 hover:text-stellar">
                      <span className="block truncate font-semibold">{b.booking.title}</span>
                      <span className="mt-1 flex items-center justify-between gap-3 text-sm text-ink-3">
                        <span className="tnum">{money(b.quote.total, b.quote.currency)}</span>
                        <BookingBadge status={b.booking.status} />
                      </span>
                    </Link>
                  </li>
                ))}
                {all.length === 0 && <li className="py-3 text-sm text-ink-3">No bookings yet.</li>}
              </ul>
            </section>
          </aside>
        )}
      </div>
    </div>
  );
}
