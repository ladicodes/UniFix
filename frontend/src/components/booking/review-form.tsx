"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { overall, RATING_LABELS } from "@/lib/format";
import type { RatingBreakdown, RatingKey, Review } from "@/lib/types";
import { useToast } from "../providers";
import { Button, ErrorNote, Field, StarInput, Stars, Textarea } from "../ui";

const KEYS = Object.keys(RATING_LABELS) as RatingKey[];

export function ReviewForm({ bookingId, proName }: { bookingId: string; proName: string }) {
  const toast = useToast();
  const [ratings, setRatings] = useState<RatingBreakdown>({ quality: 0, punctuality: 0, communication: 0, professionalism: 0, value: 0 });
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const complete = KEYS.every((k) => ratings[k] > 0);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!complete) return setError(new Error("Rate all five categories."));
    setBusy(true);
    setError(null);
    try {
      await api.submitReview(bookingId, { ratings, comment });
      toast({ title: "Review published", body: `${proName}'s rating is updated.`, tone: "ok" });
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  }

  return (
    <form id="review" onSubmit={submit} className="flex flex-col gap-5">
      <div>
        <h2 className="text-lg font-semibold">Rate {proName}</h2>
        <p className="mt-1 text-ink-2">Your review is marked as verified because it is linked to this paid booking.</p>
      </div>
      <div className="divide-y divide-line border-y border-line">
        {KEYS.map((k) => (
          <div key={k} className="flex flex-wrap items-center justify-between gap-2 py-2">
            <span className="text-base font-semibold">{RATING_LABELS[k]}</span>
            <StarInput label={RATING_LABELS[k]} value={ratings[k]} onChange={(v) => setRatings({ ...ratings, [k]: v })} />
          </div>
        ))}
      </div>
      {complete && (
        <p className="flex items-center gap-2 text-sm">
          Overall <Stars value={overall(ratings)} /> <span className="tnum font-semibold">{overall(ratings).toFixed(1)}</span>
        </p>
      )}
      <Field label="What should other customers know?">
        {(id) => <Textarea id={id} required minLength={10} value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Was the job done right? Were they on time? Was the price fair?" />}
      </Field>
      <ErrorNote error={error} />
      <Button type="submit" loading={busy} className="self-start" disabled={!complete}>
        Publish review
      </Button>
    </form>
  );
}

export function ReviewDone({ r }: { r: Review }) {
  const o = overall(r.ratings);
  return (
    <div>
      <h2 className="text-lg font-semibold">Your review</h2>
      <p className="mt-2 flex items-center gap-2">
        <Stars value={o} /> <span className="tnum font-semibold">{o.toFixed(1)}</span>
      </p>
      <p className="mt-2 max-w-prose text-ink-2">{r.comment}</p>
    </div>
  );
}
