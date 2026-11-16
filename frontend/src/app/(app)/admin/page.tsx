"use client";

import Link from "next/link";
import { useState } from "react";
import { api } from "@/lib/api";
import { cn, dateTime, money, timeAgo, usdc } from "@/lib/format";
import { useDisputes } from "@/lib/hooks";
import type { DisputeBundle } from "@/lib/api";
import type { DisputeOutcome } from "@/lib/types";
import { useSession, useToast } from "@/components/providers";
import { EvidenceView } from "@/components/booking/completion";
import { EscrowCard } from "@/components/booking/escrow-card";
import { Badge, Button, Dialog, Empty, ErrorNote, Field, Panel, Skeleton, Textarea } from "@/components/ui";

const STATUS_TONE = { OPEN: "clay", UNDER_REVIEW: "danfo", RESOLVED: "lagoon", CLOSED: "neutral" } as const;
const STATUS_LABEL = { OPEN: "Open", UNDER_REVIEW: "Under review", RESOLVED: "Resolved", CLOSED: "Closed" };

function Resolve({ d, onClose }: { d: DisputeBundle; onClose: () => void }) {
  const toast = useToast();
  const [outcome, setOutcome] = useState<DisputeOutcome>("SPLIT");
  const [split, setSplit] = useState(80);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const amount = d.bundle.escrow?.amount ?? 0;
  const toPro = outcome === "RELEASE" ? amount : outcome === "REFUND" ? 0 : (amount * split) / 100;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.resolveDispute(d.dispute.id, { outcome, splitPercentToProfessional: outcome === "SPLIT" ? split : undefined, note });
      toast({ title: "Dispute resolved", body: "Settlement was submitted to the escrow contract.", tone: "ok" });
      onClose();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-5">
      <fieldset>
        <legend className="text-sm font-semibold">Outcome</legend>
        <div className="mt-2 grid gap-2 sm:grid-cols-3">
          {(
            [
              ["RELEASE", "Release to professional"],
              ["SPLIT", "Split"],
              ["REFUND", "Refund customer"],
            ] as const
          ).map(([v, l]) => (
            <label key={v} className={cn("cursor-pointer rounded-lg border-2 px-4 py-3 text-sm font-semibold transition-colors", outcome === v ? "border-stellar bg-stellar-soft" : "border-line hover:border-line-2")}>
              <input type="radio" name="outcome" className="sr-only" checked={outcome === v} onChange={() => setOutcome(v)} />
              {l}
            </label>
          ))}
        </div>
      </fieldset>
      {outcome === "SPLIT" && (
        <div>
          <label htmlFor="split" className="text-sm font-semibold">
            Share to professional: <span className="tnum">{split}%</span>
          </label>
          <input id="split" type="range" min={5} max={95} step={5} value={split} onChange={(e) => setSplit(Number(e.target.value))} className="mt-3 w-full accent-stellar" />
        </div>
      )}
      <dl className="grid grid-cols-2 gap-4 border-y border-line py-4 text-sm">
        <div>
          <dt className="text-ink-3">To {d.bundle.professional.name}</dt>
          <dd className="font-wide tnum mt-1 text-lg font-bold">{usdc(toPro)}</dd>
        </div>
        <div>
          <dt className="text-ink-3">Back to {d.bundle.customer.name}</dt>
          <dd className="font-wide tnum mt-1 text-lg font-bold">{usdc(amount - toPro)}</dd>
        </div>
      </dl>
      <Field label="Resolution note" hint="Both parties see this. It is stored in the audit log.">
        {(id) => <Textarea id={id} required minLength={10} value={note} onChange={(e) => setNote(e.target.value)} />}
      </Field>
      <ErrorNote error={error} />
      <div className="flex justify-end gap-2">
        <Button type="button" variant="ghost" onClick={onClose}>
          Cancel
        </Button>
        <Button type="submit" loading={busy}>
          Authorise settlement
        </Button>
      </div>
    </form>
  );
}

export default function AdminPage() {
  const { user } = useSession();
  const { data, isLoading, error } = useDisputes();
  const [selected, setSelected] = useState<string | null>(null);
  const [resolving, setResolving] = useState(false);

  if (user && user.role !== "admin") return <Empty title="Admins only" body="This area is for Handi operations and dispute resolvers." />;

  const current = data?.find((d) => d.dispute.id === selected) ?? data?.[0];
  const open = data?.filter((d) => d.dispute.status === "OPEN" || d.dispute.status === "UNDER_REVIEW").length ?? 0;

  return (
    <div>
      <h1 className="font-semiwide text-3xl font-bold">Disputes</h1>
      <p className="mt-1 text-ink-3">{open} waiting for a decision. Every action is recorded in the audit log.</p>
      <ErrorNote error={error} />

      {isLoading ? (
        <Skeleton className="mt-8 h-64 w-full" />
      ) : !data?.length ? (
        <div className="mt-8">
          <Empty title="No disputes" body="When a customer or professional raises a dispute, it appears here with the agreement and evidence." />
        </div>
      ) : (
        <div className="mt-8 grid gap-6 lg:grid-cols-[320px_1fr]">
          <Panel className="divide-y divide-line self-start">
            {data.map((d) => (
              <button
                key={d.dispute.id}
                onClick={() => setSelected(d.dispute.id)}
                aria-current={current?.dispute.id === d.dispute.id}
                className={cn("block w-full rounded-lg px-3 py-4 text-left transition-colors", current?.dispute.id === d.dispute.id ? "bg-stellar-soft" : "hover:bg-plaster")}
              >
                <div className="flex items-center justify-between gap-2">
                  <Badge tone={STATUS_TONE[d.dispute.status]}>{STATUS_LABEL[d.dispute.status]}</Badge>
                  <span className="text-xs text-ink-3">{timeAgo(d.dispute.openedAt)}</span>
                </div>
                <p className="mt-2 font-semibold">{d.bundle.booking.title}</p>
                <p className="text-sm text-ink-3">{d.dispute.reason}</p>
              </button>
            ))}
          </Panel>

          {current && (
            <div className="min-w-0 space-y-5">
              <section>
                <div className="flex flex-wrap items-start justify-between gap-4">
                  <div>
                    <Badge tone={STATUS_TONE[current.dispute.status]}>{STATUS_LABEL[current.dispute.status]}</Badge>
                    <h2 className="mt-2 text-xl font-semibold">{current.bundle.booking.title}</h2>
                    <p className="mt-1 text-sm text-ink-3">
                      {current.bundle.customer.name} and {current.bundle.professional.name}. Opened {dateTime(current.dispute.openedAt)}.
                    </p>
                  </div>
                  {(current.dispute.status === "OPEN" || current.dispute.status === "UNDER_REVIEW") && (
                    <Button onClick={() => setResolving(true)}>Resolve dispute</Button>
                  )}
                </div>
                <div className="mt-5 rounded-lg bg-clay-soft px-4 py-3 text-clay-ink">
                  <p className="font-semibold">{current.dispute.reason}</p>
                  <p className="mt-1 text-sm">{current.dispute.details}</p>
                </div>
                {current.dispute.resolutionNote && (
                  <div className="mt-3 rounded-lg bg-lagoon-soft px-4 py-3 text-lagoon-ink">
                    <p className="font-semibold">Resolution</p>
                    <p className="mt-1 text-sm">{current.dispute.resolutionNote}</p>
                  </div>
                )}
                <div className="mt-5 flex flex-wrap gap-2">
                  <Button href={`/bookings/${current.bundle.booking.id}`} variant="outline" size="sm">
                    Open booking
                  </Button>
                  <Link href={`/pros/${current.bundle.professional.id}`} className="inline-flex h-9 items-center px-2 text-sm font-semibold text-stellar hover:underline">
                    Professional profile
                  </Link>
                </div>
              </section>

              <section className="border-t border-line pt-6">
                <h3 className="text-lg font-semibold">Locked agreement</h3>
                <p className="mt-2 text-ink-2">{current.bundle.quote.description}</p>
                <p className="tnum mt-3 font-semibold">
                  {money(current.bundle.quote.total, current.bundle.quote.currency)}, version {current.bundle.quote.version}
                </p>
              </section>

              {current.bundle.booking.completion && (
                <section className="border-t border-line pt-6">
                  <EvidenceView e={current.bundle.booking.completion} proName={current.bundle.professional.name} />
                </section>
              )}
              {current.bundle.escrow && <EscrowCard escrow={current.bundle.escrow} />}

              <Dialog open={resolving} onClose={() => setResolving(false)} title="Resolve dispute" wide>
                <Resolve d={current} onClose={() => setResolving(false)} />
              </Dialog>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
