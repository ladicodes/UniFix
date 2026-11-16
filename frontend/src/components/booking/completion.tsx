"use client";

import { useRef, useState } from "react";
import { Camera, CheckSquare, Fingerprint, ImageIcon, Plus, Square, X } from "lucide-react";
import { api } from "@/lib/api";
import { cn, dateTime, shortHash } from "@/lib/format";
import type { CompletionEvidence } from "@/lib/types";
import { useToast } from "../providers";
import { Button, ErrorNote, Field, Input, Textarea } from "../ui";

const MAX = 5 * 1024 * 1024;

export function CompletionForm({ bookingId, scope }: { bookingId: string; scope: string }) {
  const toast = useToast();
  const [notes, setNotes] = useState("");
  const [items, setItems] = useState(() =>
    scope
      .split(/[,.]/)
      .map((s) => s.trim())
      .filter((s) => s.length > 3)
      .slice(0, 6)
      .map((label) => ({ label: label[0].toUpperCase() + label.slice(1), done: false })),
  );
  const [newItem, setNewItem] = useState("");
  const [photos, setPhotos] = useState<CompletionEvidence["photos"]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  function addFiles(files: FileList | null) {
    if (!files) return;
    [...files].slice(0, 8 - photos.length).forEach((f) => {
      if (!f.type.startsWith("image/")) return toast({ title: `${f.name} is not an image`, tone: "err" });
      if (f.size > MAX) return toast({ title: `${f.name} is larger than 5 MB`, tone: "err" });
      const r = new FileReader();
      r.onload = () => setPhotos((p) => [...p, { id: `${Date.now()}-${f.name}`, name: f.name, dataUrl: String(r.result) }]);
      r.readAsDataURL(f);
    });
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!photos.length) return setError(new Error("Add at least one photo of the finished work."));
    if (items.some((i) => !i.done)) return setError(new Error("Tick every checklist item, or remove items that were not part of the job."));
    setBusy(true);
    setError(null);
    try {
      await api.submitCompletion(bookingId, { notes, checklist: items, photos });
      toast({ title: "Completion submitted", body: "The customer can now approve and release payment.", tone: "ok" });
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-5">
      <div>
        <p className="text-lg font-semibold">Submit completion evidence</p>
        <p className="mt-1 text-ink-2">Submitting does not release payment. The customer reviews this and approves.</p>
      </div>

      <fieldset>
        <legend className="text-sm font-semibold">Checklist</legend>
        <ul className="mt-2 divide-y divide-line border-y border-line">
          {items.map((it, i) => (
            <li key={i} className="flex items-center gap-3 py-3">
              <button
                type="button"
                role="checkbox"
                aria-checked={it.done}
                onClick={() => setItems(items.map((x, j) => (j === i ? { ...x, done: !x.done } : x)))}
                className="flex flex-1 items-center gap-3 text-left text-base"
              >
                {it.done ? <CheckSquare className="size-5 shrink-0 text-lagoon" aria-hidden /> : <Square className="size-5 shrink-0 text-ink-3" aria-hidden />}
                <span className={cn(it.done && "text-ink-2")}>{it.label}</span>
              </button>
              <button type="button" aria-label={`Remove ${it.label}`} onClick={() => setItems(items.filter((_, j) => j !== i))} className="grid size-8 place-items-center rounded-lg text-ink-3 hover:bg-plaster">
                <X className="size-4" />
              </button>
            </li>
          ))}
          <li className="flex gap-2 py-2">
            <Input aria-label="New checklist item" placeholder="Add an item" value={newItem} onChange={(e) => setNewItem(e.target.value)} className="h-10" />
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-10"
              onClick={() => {
                if (newItem.trim()) setItems([...items, { label: newItem.trim(), done: true }]);
                setNewItem("");
              }}
            >
              <Plus className="size-4" aria-hidden /> Add
            </Button>
          </li>
        </ul>
      </fieldset>

      <div>
        <p className="text-sm font-semibold">Photos of the finished work</p>
        <div className="mt-2 grid grid-cols-3 gap-2 sm:grid-cols-4">
          {photos.map((p) => (
            <div key={p.id} className="group relative aspect-square overflow-hidden rounded-lg bg-plaster-2">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={p.dataUrl} alt={p.name} className="size-full object-cover" />
              <button type="button" aria-label={`Remove ${p.name}`} onClick={() => setPhotos(photos.filter((x) => x.id !== p.id))} className="absolute right-1.5 top-1.5 grid size-7 place-items-center rounded-full bg-ink/70 text-white">
                <X className="size-4" />
              </button>
            </div>
          ))}
          {photos.length < 8 && (
            <button type="button" onClick={() => fileRef.current?.click()} className="flex aspect-square flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed border-line-2 text-sm font-semibold text-ink-3 hover:border-ink-3 hover:text-ink">
              <Camera className="size-6" aria-hidden />
              Add photo
            </button>
          )}
        </div>
        <input ref={fileRef} type="file" accept="image/*" multiple className="hidden" onChange={(e) => addFiles(e.target.files)} />
        <p className="mt-2 text-sm text-ink-3">Up to 8 images, 5 MB each.</p>
      </div>

      <Field label="Notes for the customer">
        {(id) => <Textarea id={id} required placeholder="What you did, readings taken, anything to watch out for" value={notes} onChange={(e) => setNotes(e.target.value)} />}
      </Field>
      <ErrorNote error={error} />
      <Button type="submit" size="lg" loading={busy} className="self-start">
        Submit for approval
      </Button>
    </form>
  );
}

export function EvidenceView({ e, proName }: { e: CompletionEvidence; proName: string }) {
  return (
    <div>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-lg font-semibold">Completion evidence</h2>
        <p className="text-sm text-ink-3">
          From {proName}, {dateTime(e.submittedAt)}
        </p>
      </div>
      <p className="mt-3 max-w-prose leading-relaxed text-ink-2">{e.notes}</p>
      <ul className="mt-4 grid gap-2 sm:grid-cols-2">
        {e.checklist.map((c) => (
          <li key={c.label} className="flex items-center gap-2 text-sm">
            <CheckSquare className={cn("size-4 shrink-0", c.done ? "text-lagoon" : "text-ink-3")} aria-hidden />
            {c.label}
          </li>
        ))}
      </ul>
      <ul className="mt-5 grid grid-cols-3 gap-2 sm:grid-cols-4">
        {e.photos.map((p) => (
          <li key={p.id} className="aspect-square overflow-hidden rounded-lg bg-plaster-2">
            {p.dataUrl ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={p.dataUrl} alt={p.name} className="size-full object-cover" />
            ) : (
              <div className="flex size-full flex-col items-center justify-center gap-1 p-2 text-center text-xs text-ink-3">
                <ImageIcon className="size-5" aria-hidden />
                <span className="line-clamp-2 break-all">{p.name}</span>
              </div>
            )}
          </li>
        ))}
      </ul>
      <p className="mt-4 flex items-center gap-2 text-xs text-ink-3">
        <Fingerprint className="size-3.5" aria-hidden />
        Evidence fingerprint <span className="tnum font-semibold text-ink-2">{shortHash(e.hash)}</span>, stored off-chain
      </p>
    </div>
  );
}
