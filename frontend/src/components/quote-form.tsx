"use client";

import { useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import { money, toUsdc, usdc } from "@/lib/format";
import type { Currency, Milestone } from "@/lib/types";
import { useToast } from "./providers";
import { Button, Dialog, ErrorNote, Field, Input, Textarea } from "./ui";

export function QuoteForm({
  open,
  onClose,
  conversationId,
  currency,
  nextVersion,
}: {
  open: boolean;
  onClose: () => void;
  conversationId: string;
  currency: Currency;
  nextVersion: number;
}) {
  const toast = useToast();
  const [today] = useState(() => new Date().toISOString().slice(0, 10));
  const [v, setV] = useState(() => ({
    title: "",
    description: "",
    labour: 0,
    materials: 0,
    completionDate: new Date(Date.now() + 2 * 86400000).toISOString().slice(0, 10),
    paymentTerms: "Full amount held in Handi escrow. Released when the customer approves the finished job.",
  }));
  const [useMilestones, setUseMilestones] = useState(false);
  const [milestones, setMilestones] = useState<Milestone[]>([
    { title: "Initial work", percent: 30 },
    { title: "Main work", percent: 40 },
    { title: "Final completion", percent: 30 },
  ]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const total = (v.labour || 0) + (v.materials || 0);
  const msTotal = milestones.reduce((s, m) => s + (m.percent || 0), 0);
  const symbol = currency === "NGN" ? "₦" : "GH₵";

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (useMilestones && msTotal !== 100) {
      setError(new Error(`Milestones add up to ${msTotal}%. They must add up to 100%.`));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.createQuote({
        conversationId,
        ...v,
        completionDate: new Date(v.completionDate).toISOString(),
        currency,
        milestones: useMilestones ? milestones : [],
      });
      toast({ title: `Quotation v${nextVersion} sent`, tone: "ok" });
      onClose();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onClose={onClose} title={nextVersion > 1 ? `Send revised quotation (v${nextVersion})` : "Send a quotation"} wide>
      <form onSubmit={submit} className="flex flex-col gap-5">
        {nextVersion > 1 && (
          <p className="rounded-lg bg-danfo-soft px-4 py-3 text-sm text-danfo-ink">
            Sending a new version replaces any quotation still waiting for an answer. Funded agreements never change.
          </p>
        )}
        <Field label="Job title">
          {(id) => <Input id={id} required maxLength={100} placeholder="Replace faulty 32A breaker in kitchen" value={v.title} onChange={(e) => setV({ ...v, title: e.target.value })} />}
        </Field>
        <Field label="What you will do" hint="This becomes the agreed scope of work.">
          {(id) => <Textarea id={id} required value={v.description} onChange={(e) => setV({ ...v, description: e.target.value })} />}
        </Field>
        <div className="grid gap-4 sm:grid-cols-3">
          <Field label={`Labour (${symbol})`}>
            {(id) => <Input id={id} type="number" min={0} inputMode="numeric" required value={v.labour || ""} onChange={(e) => setV({ ...v, labour: Number(e.target.value) })} />}
          </Field>
          <Field label={`Materials (${symbol})`}>
            {(id) => <Input id={id} type="number" min={0} inputMode="numeric" value={v.materials || ""} onChange={(e) => setV({ ...v, materials: Number(e.target.value) })} />}
          </Field>
          <Field label="Done by">
            {(id) => <Input id={id} type="date" required min={today} value={v.completionDate} onChange={(e) => setV({ ...v, completionDate: e.target.value })} />}
          </Field>
        </div>
        <div className="flex items-baseline justify-between rounded-lg bg-plaster px-4 py-3">
          <span className="text-sm text-ink-3">Customer pays into escrow</span>
          <span className="text-right">
            <span className="font-wide tnum block text-xl font-bold">{money(total, currency)}</span>
            <span className="tnum block text-sm font-semibold text-stellar">{usdc(toUsdc(total, currency))}</span>
          </span>
        </div>
        <Field label="Payment terms">
          {(id) => <Textarea id={id} className="min-h-16" value={v.paymentTerms} onChange={(e) => setV({ ...v, paymentTerms: e.target.value })} />}
        </Field>

        <label className="flex cursor-pointer items-start gap-3">
          <input type="checkbox" className="mt-0.5 size-5 accent-ink" checked={useMilestones} onChange={(e) => setUseMilestones(e.target.checked)} />
          <span>
            <span className="block text-sm font-semibold">Split into milestones</span>
            <span className="block text-sm text-ink-3">For larger jobs. Each part is approved and released separately.</span>
          </span>
        </label>
        {useMilestones && (
          <div className="space-y-2">
            {milestones.map((m, i) => (
              <div key={i} className="flex gap-2">
                <Input aria-label={`Milestone ${i + 1} title`} value={m.title} onChange={(e) => setMilestones(milestones.map((x, j) => (j === i ? { ...x, title: e.target.value } : x)))} />
                <div className="relative w-28 shrink-0">
                  <Input
                    aria-label={`Milestone ${i + 1} percent`}
                    type="number"
                    min={1}
                    max={100}
                    value={m.percent}
                    onChange={(e) => setMilestones(milestones.map((x, j) => (j === i ? { ...x, percent: Number(e.target.value) } : x)))}
                    className="pr-8"
                  />
                  <span className="absolute right-3 top-1/2 -translate-y-1/2 text-sm text-ink-3">%</span>
                </div>
                <Button type="button" variant="ghost" aria-label="Remove milestone" onClick={() => setMilestones(milestones.filter((_, j) => j !== i))} disabled={milestones.length <= 2}>
                  <Trash2 className="size-4" />
                </Button>
              </div>
            ))}
            <div className="flex items-center justify-between">
              <Button type="button" variant="ghost" size="sm" onClick={() => setMilestones([...milestones, { title: "", percent: 0 }])}>
                <Plus className="size-4" aria-hidden /> Add milestone
              </Button>
              <span className={msTotal === 100 ? "text-sm font-semibold text-lagoon" : "text-sm font-semibold text-clay"}>{msTotal}% of 100%</span>
            </div>
          </div>
        )}
        <ErrorNote error={error} />
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" loading={busy} disabled={total <= 0}>
            Send quotation
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
