"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { BadgeCheck, CircleDashed, Clock, Hammer, MapPin, MessageCircle, ShieldCheck } from "lucide-react";
import { api } from "@/lib/api";
import { categoryLabel, cn, money, overall, RATING_LABELS, shortDate } from "@/lib/format";
import { useLive, useProfessional, useReviews } from "@/lib/hooks";
import type { Professional, RatingKey, Review } from "@/lib/types";
import { useSession } from "@/components/providers";
import { AVAILABILITY } from "@/components/pro-row";
import { Avatar, Badge, Button, ErrorNote, Skeleton, Stars, Surface } from "@/components/ui";

function Verification({ p }: { p: Professional }) {
  const rows = [
    { ok: p.verification.identity, label: "Government ID checked" },
    { ok: p.verification.trade, label: "Trade certificate checked" },
    { ok: p.verification.phone, label: "Phone number confirmed" },
  ];
  return (
    <ul className="space-y-3">
      {rows.map((r) => (
        <li key={r.label} className={cn("flex items-center gap-3 text-sm", r.ok ? "text-ink" : "text-ink-3")}>
          {r.ok ? <BadgeCheck className="size-[18px] text-lagoon" aria-hidden /> : <CircleDashed className="size-[18px]" aria-hidden />}
          <span>
            {r.label}
            {!r.ok && <span className="sr-only"> (not verified)</span>}
          </span>
          {!r.ok && <span className="ml-auto text-xs">Not yet</span>}
        </li>
      ))}
    </ul>
  );
}

function RatingSummary({ p }: { p: Professional }) {
  const keys = Object.keys(RATING_LABELS) as RatingKey[];
  return (
    <div className="grid gap-8 sm:grid-cols-[auto_1fr] sm:gap-12">
      <div>
        <p className="font-wide tnum text-6xl font-bold leading-none tracking-tight">{p.reviewCount ? p.rating.toFixed(1) : "–"}</p>
        <Stars value={p.rating} size={18} className="mt-3" />
        <p className="mt-2 text-sm text-ink-3">
          {p.reviewCount} verified review{p.reviewCount === 1 ? "" : "s"}
          <br />
          {p.completedJobs} completed jobs
        </p>
      </div>
      <dl className="grid content-center gap-3">
        {keys.map((k) => (
          <div key={k} className="grid grid-cols-[140px_1fr_36px] items-center gap-3 text-sm">
            <dt className="text-ink-2">{RATING_LABELS[k]}</dt>
            <dd className="h-2 overflow-hidden rounded-full bg-plaster-2">
              <span className="block h-full rounded-full bg-ink-3" style={{ width: `${(p.ratingBreakdown[k] / 5) * 100}%` }} />
            </dd>
            <dd className="tnum text-right font-semibold">{p.ratingBreakdown[k] ? p.ratingBreakdown[k].toFixed(1) : "–"}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function ReviewItem({ r, proName }: { r: Review; proName: string }) {
  const o = overall(r.ratings);
  return (
    <article className="py-6">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <Stars value={o} />
        <span className="tnum text-sm font-semibold">{o.toFixed(1)}</span>
        <span className="text-sm text-ink-3">{r.customerName}</span>
        <span className="text-sm text-ink-3">{shortDate(r.createdAt)}</span>
      </div>
      <p className="mt-1 text-sm font-semibold text-ink-2">{r.jobTitle}</p>
      <p className="mt-3 max-w-prose leading-relaxed">{r.comment}</p>
      <p className="mt-3 inline-flex items-center gap-2 text-xs font-semibold text-lagoon">
        <ShieldCheck className="size-3.5" aria-hidden />
        Linked to a paid UniFix booking
      </p>
      {r.response && (
        <div className="mt-4 border-l-2 border-line-2 pl-4">
          <p className="text-sm font-semibold">Reply from {proName.split(" ")[0]}</p>
          <p className="mt-1 text-sm text-ink-2">{r.response.body}</p>
        </div>
      )}
    </article>
  );
}

export default function ProfilePage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { user } = useSession();
  const { data: p, isLoading, error } = useProfessional(id);
  const { data: reviews } = useReviews(id);
  useLive(`pro:${id}`, [["professional", id], ["reviews", id]]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);

  async function message() {
    if (!user) return router.push(`/sign-in?next=/pros/${id}`);
    setBusy(true);
    setErr(null);
    try {
      const c = await api.openConversation(id);
      router.push(`/messages/${c.id}`);
    } catch (e) {
      setErr(e);
      setBusy(false);
    }
  }

  if (isLoading)
    return (
      <div className="space-y-6">
        <Skeleton className="h-28 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  if (error || !p) return <ErrorNote error={error ?? "Professional not found."} />;

  const a = AVAILABILITY[p.availability];
  const isMe = user?.professionalId === p.id;
  const canMessage = !user || user.role === "customer";

  return (
    <div className="grid gap-10 lg:grid-cols-[1fr_340px]">
      <div className="min-w-0">
        <Link href="/discover" className="text-sm font-semibold text-ink-3 hover:text-ink">
          Back to results
        </Link>

        <header className="mt-5 flex flex-col gap-5 sm:flex-row sm:items-center">
          <Avatar name={p.name} size={88} />
          <div>
            <h1 className="font-semiwide text-3xl font-bold leading-tight">{p.name}</h1>
            <p className="mt-1 text-lg text-ink-2">
              {categoryLabel(p.category)} in {p.area}, {p.city}
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              {p.verification.identity && p.verification.trade && (
                <Badge tone="lagoon">
                  <BadgeCheck className="size-3.5" aria-hidden /> Verified professional
                </Badge>
              )}
              {!p.verification.identity && <Badge>Unverified</Badge>}
              <Badge>
                <Hammer className="size-3.5" aria-hidden /> {p.yearsExperience} years
              </Badge>
              <Badge>
                <Clock className="size-3.5" aria-hidden /> Replies in about {p.responseMinutes} min
              </Badge>
            </div>
          </div>
        </header>

        <p className="mt-8 max-w-prose text-lg leading-relaxed text-ink-2">{p.bio}</p>

        {p.portfolio.length > 0 && (
          <section className="mt-10">
            <h2 className="text-lg font-semibold">Recent work</h2>
            <ul className="mt-3 divide-y divide-line border-y border-line">
              {p.portfolio.map((w) => (
                <li key={w.id} className="py-3 text-ink-2">
                  {w.caption}
                </li>
              ))}
            </ul>
            
          </section>
        )}

        <section className="mt-12" aria-labelledby="ratings">
          <h2 id="ratings" className="text-lg font-semibold">
            Ratings
          </h2>
          <p className="mt-1 text-sm text-ink-3">Only customers with a completed, paid booking can rate. One review per booking.</p>
          <div className="mt-6">
            <RatingSummary p={p} />
          </div>
        </section>

        <section className="mt-10" aria-labelledby="reviews">
          <h2 id="reviews" className="text-lg font-semibold">
            Reviews
          </h2>
          {reviews?.length ? (
            <div className="divide-y divide-line">
              {reviews.map((r) => (
                <ReviewItem key={r.id} r={r} proName={p.name} />
              ))}
            </div>
          ) : (
            <p className="mt-3 text-ink-3">No written reviews yet.</p>
          )}
        </section>
      </div>

      <aside className="lg:sticky lg:top-24 lg:self-start">
        <Surface className="p-6">
          <p className="text-sm text-ink-3">Starting from</p>
          <p className="font-wide tnum text-3xl font-bold tracking-tight">{money(p.startingPrice, p.currency)}</p>
          <p className={cn("mt-2 text-sm font-semibold", a.cls)}>{a.label}</p>
          {canMessage && !isMe && (
            <Button size="lg" className="mt-5 w-full" onClick={message} loading={busy}>
              <MessageCircle className="size-5" aria-hidden />
              Message {p.name.split(" ")[0]}
            </Button>
          )}
          {isMe && (
            <p className="mt-5 text-sm text-ink-2">This is how customers see your profile.</p>
          )}
          <ErrorNote error={err} />
          <p className="mt-3 text-sm leading-relaxed text-ink-3">
            Describe the job, get a quotation, and pay into escrow only when you accept it.
          </p>

          <hr className="my-6 border-line-2/30" />
          <h2 className="text-sm font-semibold">Verification</h2>
          <div className="mt-3">
            <Verification p={p} />
          </div>

          <hr className="my-6 border-line-2/30" />
          <h2 className="text-sm font-semibold">Covers</h2>
          <p className="mt-2 flex items-start gap-2 text-sm text-ink-2">
            <MapPin className="mt-0.5 size-4 shrink-0 text-ink-3" aria-hidden />
            {p.coverage.join(", ")}
          </p>
          <h2 className="mt-5 text-sm font-semibold">Skills</h2>
          <div className="mt-2 flex flex-wrap gap-2">
            {p.skills.map((s) => (
              <Badge key={s}>{s}</Badge>
            ))}
          </div>
          <h2 className="mt-5 text-sm font-semibold">Speaks</h2>
          <p className="mt-1 text-sm text-ink-2">{p.languages.join(", ")}</p>
        </Surface>
      </aside>
    </div>
  );
}
