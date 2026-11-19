"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { CheckCircle2, Hourglass, Loader2, Lock, MapPin, MessageCircle, Play, ShieldCheck } from "lucide-react";
import { api } from "@/lib/api";
import { categoryLabel, cn, dateTime, money, toUsdc } from "@/lib/format";
import { signXdr } from "@/lib/stellar";
import { useBooking } from "@/lib/hooks";
import type { BookingBundle, TimelineEvent } from "@/lib/types";
import { useSession, useToast, useWallet } from "@/components/providers";
import { BookingBadge } from "@/components/status";
import { AgreementTicket, type TicketStage } from "@/components/ticket";
import { EscrowCard } from "@/components/booking/escrow-card";
import { FundPanel } from "@/components/booking/fund-panel";
import { CompletionForm, EvidenceView } from "@/components/booking/completion";
import { DisputeDialog, DisputeView } from "@/components/booking/dispute";
import { Receipt } from "@/components/booking/receipt";
import { ReviewDone, ReviewForm } from "@/components/booking/review-form";
import { Avatar, Button, Dialog, ErrorNote, Skeleton } from "@/components/ui";

function stageOf(b: BookingBundle): TicketStage {
  const s = b.booking.status;
  if (b.escrow?.state === "REFUNDED") return "refunded";
  if (s === "COMPLETED") return "released";
  if (s === "DISPUTED") return "disputed";
  if (s === "COMPLETION_SUBMITTED") return "submitted";
  if (s === "FUNDED" || s === "IN_PROGRESS") return "held";
  return "agreed";
}

const ACTOR_DOT: Record<TimelineEvent["actor"], string> = {
  customer: "bg-stellar",
  professional: "bg-ink-3",
  system: "bg-line-2",
  chain: "bg-stellar",
  admin: "bg-clay",
};

function Timeline({ events }: { events: TimelineEvent[] }) {
  return (
    <ol className="relative space-y-4 before:absolute before:bottom-2 before:left-[5px] before:top-2 before:w-px before:bg-line">
      {[...events].reverse().map((e, i) => (
        <li key={i} className="relative flex gap-4 pl-0">
          <span className={cn("relative z-10 mt-2 size-[11px] shrink-0 rounded-full ring-4 ring-paper", ACTOR_DOT[e.actor])} aria-hidden />
          <div>
            <p className="text-base font-semibold">{e.label}</p>
            <p className="text-sm text-ink-3">
              {dateTime(e.at)}
              {e.actor === "chain" && " on Stellar"}
            </p>
          </div>
        </li>
      ))}
    </ol>
  );
}

function Waiting({ icon: Icon = Hourglass, title, body }: { icon?: typeof Hourglass; title: string; body: string }) {
  return (
    <div className="flex items-start gap-4">
      <span className="grid size-10 shrink-0 place-items-center rounded-full bg-plaster-2">
        <Icon className="size-5 text-ink-2" aria-hidden />
      </span>
      <div>
        <p className="text-lg font-semibold">{title}</p>
        <p className="mt-1 max-w-prose text-ink-2">{body}</p>
      </div>
    </div>
  );
}

function ApprovePanel({ b, onDispute }: { b: BookingBundle; onDispute: () => void }) {
  const toast = useToast();
  const w = useWallet();
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const first = b.professional.name.split(" ")[0];

  async function release() {
    if (!b.escrow) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api.releaseEscrow(b.escrow.id);
      if (r.unsignedXdr) {
        if (!w.address || w.source !== "freighter") throw new Error("Connect Freighter to sign the release.");
        await api.releaseEscrow(b.escrow.id, await signXdr(r.unsignedXdr, w.address));
      }
      setConfirm(false);
      toast({ title: "Release submitted", body: "Stellar is confirming the payment to the professional.", tone: "info" });
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <p className="text-lg font-semibold">{first} says the job is done</p>
      <p className="mt-1 max-w-prose text-ink-2">
        Check the evidence below, and the work itself if you can. Approving tells the escrow contract to pay {first}. This cannot be
        undone.
      </p>
      <div className="mt-5 flex flex-col gap-2 sm:flex-row">
        <Button variant="accent" size="lg" onClick={() => setConfirm(true)}>
          <CheckCircle2 className="size-5" aria-hidden />
          Approve and release payment
        </Button>
        <Button variant="danger" size="lg" onClick={onDispute}>
          Something is wrong
        </Button>
      </div>
      <Dialog open={confirm} onClose={() => setConfirm(false)} title={`Release ${b.escrow?.amount.toFixed(2)} USDC to ${first}?`}>
        <p className="text-ink-2">
          The contract sends the full escrowed amount to {b.professional.name}&apos;s wallet. After release, the funds cannot be refunded through UniFix.
        </p>
        <ErrorNote error={error} />
        <div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button variant="ghost" onClick={() => setConfirm(false)}>
            Go back
          </Button>
          <Button variant="accent" onClick={release} loading={busy}>
            Release payment
          </Button>
        </div>
      </Dialog>
    </div>
  );
}

function StartPanel({ b }: { b: BookingBundle }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  return (
    <div>
      <div className="flex items-start gap-4">
        <span className="grid size-10 shrink-0 place-items-center rounded-full bg-danfo">
          <Lock className="size-5 text-ink" aria-hidden />
        </span>
        <div>
          <p className="text-lg font-semibold">Payment is secured. You can start.</p>
          <p className="mt-1 max-w-prose text-ink-2">
            {b.escrow?.amount.toFixed(2)} USDC is held in the escrow contract for this job. Tap start when you arrive so {b.customer.name.split(" ")[0]} knows work has begun.
          </p>
        </div>
      </div>
      <ErrorNote error={error} />
      <Button
        size="lg"
        className="mt-5"
        loading={busy}
        onClick={async () => {
          setBusy(true);
          setError(null);
          try {
            await api.startJob(b.booking.id);
            toast({ title: "Job started", tone: "ok" });
          } catch (e) {
            setError(e);
          } finally {
            setBusy(false);
          }
        }}
      >
        <Play className="size-5" aria-hidden />
        Start job
      </Button>
    </div>
  );
}

export default function BookingPage() {
  const { id } = useParams<{ id: string }>();
  const { user } = useSession();
  const { data: b, isLoading, error } = useBooking(id);
  const [disputeOpen, setDisputeOpen] = useState(false);

  if (isLoading || !user)
    return (
      <div className="grid gap-8 lg:grid-cols-[1fr_380px]">
        <div className="space-y-4">
          <Skeleton className="h-10 w-2/3" />
          <Skeleton className="h-64 w-full" />
        </div>
        <Skeleton className="h-96 w-full" />
      </div>
    );
  if (error || !b) return <ErrorNote error={error ?? "Booking not found."} />;

  const isCustomer = user.id === b.booking.customerId;
  const isPro = user.professionalId === b.booking.professionalId;
  const status = b.booking.status;
  const escrowPending = b.escrow?.reconciliation === "PENDING_CONFIRMATION";
  const other = isCustomer ? b.professional.name : b.customer.name;
  const canDispute = b.escrow?.state === "FUNDED" && ["FUNDED", "IN_PROGRESS", "COMPLETION_SUBMITTED"].includes(status) && !escrowPending;

  let action: React.ReactNode = null;
  if (isCustomer) {
    if (status === "PENDING_PAYMENT") action = <FundPanel b={b} />;
    else if (escrowPending && status === "COMPLETION_SUBMITTED")
      action = <Waiting icon={Loader2} title="Releasing payment on Stellar" body="The contract is paying the professional. This page updates when the ledger confirms it." />;
    else if (status === "FUNDED") action = <Waiting icon={Lock} title="Payment held. Waiting for the job to start." body={`${b.professional.name} has been notified that the money is secured.`} />;
    else if (status === "IN_PROGRESS") action = <Waiting icon={Lock} title="Work in progress" body={`Your payment stays in escrow while ${b.professional.name.split(" ")[0]} works. You will be asked to approve when they finish.`} />;
    else if (status === "COMPLETION_SUBMITTED") action = <ApprovePanel b={b} onDispute={() => setDisputeOpen(true)} />;
  } else if (isPro) {
    if (status === "PENDING_PAYMENT")
      action = (
        <Waiting
          title={escrowPending ? "Customer payment is confirming" : "Waiting for the customer to fund escrow"}
          body="Do not buy materials or travel yet. You will be notified the moment the payment is held on Stellar."
        />
      );
    else if (status === "FUNDED") action = <StartPanel b={b} />;
    else if (status === "IN_PROGRESS") action = <CompletionForm bookingId={b.booking.id} scope={b.quote.description} />;
    else if (status === "COMPLETION_SUBMITTED")
      action = escrowPending ? (
        <Waiting icon={Loader2} title="Payment is being released" body="The customer approved. Stellar is confirming the transfer to your wallet." />
      ) : (
        <Waiting title="Waiting for customer approval" body={`${b.customer.name.split(" ")[0]} is reviewing your evidence. Payment releases when they approve.`} />
      );
  }

  return (
    <div className="grid gap-8 lg:grid-cols-[1fr_380px] lg:gap-10">
      <div className="min-w-0 space-y-8">
        <div>
          <Link href="/bookings" className="text-sm font-semibold text-ink-3 hover:text-ink">
            All bookings
          </Link>
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <BookingBadge status={status} />
          </div>
          <h1 className="font-semiwide mt-2 text-2xl font-bold leading-tight sm:text-3xl">{b.booking.title}</h1>
          <div className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-3">
            <span className="flex items-center gap-3">
              <Avatar name={other} size={32} />
              <span className="text-sm">
                <span className="font-semibold">{other}</span>
                <span className="block text-ink-3">{isCustomer ? categoryLabel(b.professional.category) : "Customer"}</span>
              </span>
            </span>
            <span className="flex items-center gap-2 text-sm text-ink-2">
              <MapPin className="size-4 text-ink-3" aria-hidden />
              {b.booking.address}
            </span>
            <Button href={`/messages/${b.booking.conversationId}`} variant="outline" size="sm">
              <MessageCircle className="size-4" aria-hidden /> Chat
            </Button>
          </div>
        </div>

        {action && (
          <div className="rounded-2xl bg-plaster p-5 sm:p-8">{action}</div>
        )}

        {b.dispute && (
          <div className="rounded-2xl bg-clay-soft/60 p-5 sm:p-8">
            <DisputeView d={b.dispute} />
          </div>
        )}

        {b.booking.completion && (
          <section className="border-t border-line pt-8">
            <EvidenceView e={b.booking.completion} proName={b.professional.name} />
          </section>
        )}

        {status === "COMPLETED" && (
          <>
            <section className="border-t border-line pt-8">
              <Receipt b={b} />
            </section>
            {isCustomer && (
              <section className={b.review ? "border-t border-line pt-8" : "rounded-2xl bg-plaster p-5 sm:p-8"}>
                {b.review ? <ReviewDone r={b.review} /> : <ReviewForm bookingId={b.booking.id} proName={b.professional.name} />}
              </section>
            )}
            {isPro && b.review && (
              <section className="border-t border-line pt-8">
                <ReviewDone r={b.review} />
              </section>
            )}
          </>
        )}

        <section className="border-t border-line pt-8">
          <h2 className="mb-5 text-lg font-semibold">Activity</h2>
          <Timeline events={b.booking.timeline} />
        </section>

        {canDispute && status !== "COMPLETION_SUBMITTED" && (
          <p className="text-sm text-ink-3">
            Problem with this job?{" "}
            <button onClick={() => setDisputeOpen(true)} className="font-semibold text-clay hover:underline">
              Raise a dispute
            </button>{" "}
            to keep the funds locked.
          </p>
        )}
      </div>

      <aside className="space-y-5 lg:sticky lg:top-24 lg:self-start">
        <AgreementTicket
          title={b.quote.title}
          professional={b.professional.name}
          customer={b.customer.name}
          labour={b.quote.labour}
          materials={b.quote.materials}
          currency={b.quote.currency}
          usdcAmount={b.escrow?.amount ?? toUsdc(b.quote.total, b.quote.currency)}
          stage={stageOf(b)}
          version={b.quote.version}
          txHash={b.escrow?.transactions.find((t) => t.kind === "FUND")?.hash}
        />
        <p className="flex items-start gap-2 px-1 text-sm text-ink-3">
          <ShieldCheck className="mt-0.5 size-4 shrink-0 text-lagoon" aria-hidden />
          <span>
            Agreed {money(b.quote.total, b.quote.currency)} on {dateTime(b.quote.acceptedAt ?? b.booking.createdAt)}. Changes need a new quotation.
          </span>
        </p>
        {b.escrow && <EscrowCard escrow={b.escrow} />}
      </aside>

      {b.escrow && <DisputeDialog open={disputeOpen} onClose={() => setDisputeOpen(false)} escrowId={b.escrow.id} />}
    </div>
  );
}
