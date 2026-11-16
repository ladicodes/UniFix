"use client";

import { useState } from "react";
import { Scale } from "lucide-react";
import { api } from "@/lib/api";
import { dateTime } from "@/lib/format";
import type { Dispute } from "@/lib/types";
import { useToast } from "../providers";
import { Badge, Button, Dialog, ErrorNote, Field, Select, Textarea } from "../ui";

const REASONS = ["Work incomplete", "Poor quality", "Different from the agreed scope", "Professional did not show up", "Damage to property", "Other"];

export function DisputeDialog({ open, onClose, escrowId }: { open: boolean; onClose: () => void; escrowId: string }) {
  const toast = useToast();
  const [reason, setReason] = useState(REASONS[0]);
  const [details, setDetails] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.openDispute(escrowId, { reason, details });
      toast({ title: "Dispute opened", body: "The funds are locked until Handi resolves it.", tone: "info" });
      onClose();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onClose={onClose} title="Raise a dispute">
      <form onSubmit={submit} className="flex flex-col gap-4">
        <p className="text-ink-2">
          The escrow contract locks the payment. Nobody can release or refund it until a Handi resolver reviews the agreement, chat and
          evidence. Most disputes are settled within 48 hours.
        </p>
        <Field label="Reason">
          {(id) => (
            <Select id={id} value={reason} onChange={(e) => setReason(e.target.value)}>
              {REASONS.map((r) => (
                <option key={r}>{r}</option>
              ))}
            </Select>
          )}
        </Field>
        <Field label="What went wrong?" hint="Be specific. Point to the part of the agreed scope that was not met.">
          {(id) => <Textarea id={id} required minLength={20} value={details} onChange={(e) => setDetails(e.target.value)} />}
        </Field>
        <ErrorNote error={error} />
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" variant="danger" loading={busy}>
            Open dispute and lock funds
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

const STATUS_TONE = { OPEN: "clay", UNDER_REVIEW: "danfo", RESOLVED: "lagoon", CLOSED: "neutral" } as const;
const STATUS_LABEL = { OPEN: "Open", UNDER_REVIEW: "Under review", RESOLVED: "Resolved", CLOSED: "Closed" };
const OUTCOME = { RELEASE: "Full payment released to the professional", REFUND: "Full refund to the customer", SPLIT: "Split settlement" };

export function DisputeView({ d }: { d: Dispute }) {
  return (
    <div>
      <div className="flex flex-wrap items-center gap-3">
        <Scale className="size-5 text-clay" aria-hidden />
        <h2 className="text-lg font-semibold">Dispute</h2>
        <Badge tone={STATUS_TONE[d.status]}>{STATUS_LABEL[d.status]}</Badge>
        <span className="text-sm text-ink-3">Opened {dateTime(d.openedAt)}</span>
      </div>
      <p className="mt-3 font-semibold">{d.reason}</p>
      <p className="mt-1 max-w-prose text-ink-2">{d.details}</p>
      {d.outcome ? (
        <div className="mt-4 rounded-lg bg-lagoon-soft px-4 py-3 text-lagoon-ink">
          <p className="font-semibold">
            {OUTCOME[d.outcome]}
            {d.outcome === "SPLIT" && `: ${d.splitPercentToProfessional}% to the professional`}
          </p>
          {d.resolutionNote && <p className="mt-1 text-sm">{d.resolutionNote}</p>}
        </div>
      ) : (
        <p className="mt-4 rounded-lg bg-plaster-2 px-4 py-3 text-sm text-ink-2">
          Funds stay locked in escrow. You will be notified when a resolver authorises the outcome.
        </p>
      )}
    </div>
  );
}
