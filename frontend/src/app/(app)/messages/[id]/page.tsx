"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { ArrowLeft, Check, CheckCheck, FileText, Flag, ImagePlus, Phone, SendHorizontal, X } from "lucide-react";
import { api, IS_DEMO } from "@/lib/api";
import { isTyping } from "@/lib/api/demo";
import { categoryLabel, clockTime, cn, money, shortDate } from "@/lib/format";
import { useConversation } from "@/lib/hooks";
import type { Message, Quote } from "@/lib/types";
import { useSession, useToast } from "@/components/providers";
import { CallOverlay } from "@/components/call-overlay";
import { QuoteCard, quoteStatus } from "@/components/quote-card";
import { QuoteForm } from "@/components/quote-form";
import { Avatar, Badge, Button, Dialog, ErrorNote, Field, Select, Skeleton, Textarea } from "@/components/ui";

const MAX_IMAGE = 5 * 1024 * 1024;
const CUSTOMER_REPLIES = ["Are you free this week?", "Can you send a quotation?", "Can I pay with escrow?", "Do you bring the parts?"];
const PRO_REPLIES = ["I can come tomorrow morning.", "Can you send a photo of the problem?", "Sending a quotation now.", "I'm on my way."];

function useTyping(conversationId: string) {
  return useSyncExternalStore(
    (cb) => api.subscribe(`typing:${conversationId}`, cb),
    () => (IS_DEMO ? isTyping(conversationId) : false),
    () => false,
  );
}

function dayKey(iso: string) {
  return new Date(iso).toDateString();
}

export default function ChatPage() {
  const { id } = useParams<{ id: string }>();
  const { user } = useSession();
  const toast = useToast();
  const { data, isLoading, error } = useConversation(id);
  const typing = useTyping(id);
  const [text, setText] = useState("");
  const [attachment, setAttachment] = useState<Message["attachment"]>();
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<unknown>(null);
  const [quoteOpen, setQuoteOpen] = useState(false);
  const [callOpen, setCallOpen] = useState(false);
  const [reportOpen, setReportOpen] = useState(false);
  const [quoteView, setQuoteView] = useState<Quote | null>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const count = data?.messages.length ?? 0;
  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: count > 0 ? "smooth" : "auto" });
  }, [count, typing]);

  if (isLoading)
    return (
      <div className="space-y-4 p-6">
        <Skeleton className="h-12 w-64" />
        <Skeleton className="ml-auto h-16 w-72" />
        <Skeleton className="h-16 w-80" />
      </div>
    );
  if (error || !data || !user) return <div className="p-6"><ErrorNote error={error ?? "Conversation not found."} /></div>;

  const isCustomer = user.id === data.conversation.customerId;
  const peer = isCustomer ? data.professional.name : data.customer.name;
  const peerSub = isCustomer ? `${categoryLabel(data.professional.category)} in ${data.professional.area}` : data.customer.city;
  const quotes = new Map(data.quotes.map((q) => [q.id, q]));
  const online = isCustomer && data.professional.availability === "now";
  const latestQuote = [...data.quotes].sort((a, b) => b.version - a.version).find((q) => q.status !== "REJECTED");
  const bookingId = data.conversation.bookingId;

  async function send(e?: React.FormEvent) {
    e?.preventDefault();
    const body = text.trim();
    if (!body && !attachment) return;
    setSending(true);
    setSendError(null);
    try {
      await api.sendMessage(id, { body, attachment });
      setText("");
      setAttachment(undefined);
    } catch (err) {
      setSendError(err);
    } finally {
      setSending(false);
    }
  }

  function pickFile(f?: File) {
    if (!f) return;
    if (!/^image\/(png|jpe?g|webp|gif)$/.test(f.type)) return toast({ title: "Only images can be attached", body: "Use PNG, JPG, WEBP or GIF.", tone: "err" });
    if (f.size > MAX_IMAGE) return toast({ title: "Image is larger than 5 MB", body: "Pick a smaller photo.", tone: "err" });
    const r = new FileReader();
    r.onload = () => setAttachment({ name: f.name, dataUrl: String(r.result) });
    r.readAsDataURL(f);
  }

  return (
    <div className="flex h-full">
    <div className="flex min-w-0 flex-1 flex-col bg-paper">
      <header className="flex items-center gap-3 border-b border-line px-3 py-3 sm:px-5">
        <Link href="/messages" aria-label="Back to messages" className="grid size-9 place-items-center rounded-lg hover:bg-plaster md:hidden">
          <ArrowLeft className="size-5" />
        </Link>
        <span className="relative">
          <Avatar name={peer} size={42} />
          {online && <span className="absolute bottom-0 right-0 size-3 rounded-full border-2 border-paper bg-lagoon" aria-hidden />}
        </span>
        <div className="min-w-0 flex-1">
          {isCustomer ? (
            <Link href={`/pros/${data.professional.id}`} className="block truncate font-semibold hover:underline">
              {peer}
            </Link>
          ) : (
            <p className="truncate font-semibold">{peer}</p>
          )}
          <p className="truncate text-xs text-ink-3">
            {online ? <span className="font-semibold text-lagoon">Online</span> : peerSub}
          </p>
        </div>
        {data.conversation.bookingId && (
          <Button href={`/bookings/${data.conversation.bookingId}`} variant="outline" size="sm" className="hidden sm:inline-flex">
            View booking
          </Button>
        )}
        <Button variant="ghost" size="sm" aria-label={`Call ${peer}`} onClick={() => setCallOpen(true)}>
          <Phone className="size-4" />
          <span className="hidden sm:inline">Call</span>
        </Button>
        <Button variant="ghost" size="sm" aria-label="Report this conversation" onClick={() => setReportOpen(true)}>
          <Flag className="size-4" />
        </Button>
      </header>

      {latestQuote && (
        <button
          type="button"
          onClick={() => setQuoteView(latestQuote)}
          className="flex items-center gap-3 border-b border-line px-3 py-3 text-left transition-colors hover:bg-plaster sm:px-5 2xl:hidden"
        >
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm font-semibold">{latestQuote.title}</span>
            <span className="tnum block text-sm text-ink-3">
              {money(latestQuote.total, latestQuote.currency)}, {quoteStatus(latestQuote, isCustomer).label.toLowerCase()}
            </span>
          </span>
          <span className="shrink-0 text-sm font-semibold text-stellar">View quotation</span>
        </button>
      )}

      <div ref={scroller} className="min-h-0 flex-1 overflow-y-auto bg-plaster/60 px-3 py-5 sm:px-6" aria-live="polite">
        <ol className="flex flex-col gap-3">
          {data.messages.map((m, i) => {
            const prev = data.messages[i - 1];
            const newDay = !prev || dayKey(prev.createdAt) !== dayKey(m.createdAt);
            const mine = m.senderId === user.id;
            return (
              <li key={m.id} className="contents">
                {newDay && (
                  <p className="mx-auto my-3 rounded-full border border-line bg-paper px-3 py-1 text-center text-xs font-semibold text-ink-3">
                    {dayKey(m.createdAt) === dayKey(new Date().toISOString()) ? "Today" : shortDate(m.createdAt)}
                  </p>
                )}
                {m.kind === "system" ? (
                  <p className="mx-auto my-1 max-w-sm rounded-full bg-plaster-2 px-4 py-2 text-center text-xs font-semibold text-ink-2">{m.body}</p>
                ) : m.kind === "quote" && m.quoteId && quotes.get(m.quoteId) ? (
                  <div className={cn("flex", mine ? "justify-end" : "justify-start")}>
                    <QuoteMessage quote={quotes.get(m.quoteId)!} viewerIsCustomer={isCustomer} onOpen={setQuoteView} />
                  </div>
                ) : (
                  <div className={cn("flex flex-col", mine ? "items-end" : "items-start")}>
                    <div
                      className={cn(
                        "max-w-[min(80%,30rem)] rounded-2xl px-4 py-3 text-base leading-relaxed",
                        mine ? "rounded-br-md bg-stellar text-white" : "rounded-bl-md border border-line bg-paper",
                      )}
                    >
                      {m.attachment && (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img src={m.attachment.dataUrl} alt={m.attachment.name} className="mb-2 max-h-64 rounded-lg object-cover" />
                      )}
                      {m.body && <p className="whitespace-pre-wrap break-words">{m.body}</p>}
                      <span className={cn("mt-1 flex items-center justify-end gap-1 text-xs", mine ? "text-white" : "text-ink-3")}>
                        {clockTime(m.createdAt)}
                        {mine && (m.readAt ? <CheckCheck className="size-3.5" aria-label="Read" /> : <Check className="size-3.5" aria-label="Sent" />)}
                      </span>
                    </div>
                  </div>
                )}
              </li>
            );
          })}
          {typing && (
            <li className="flex items-center gap-1 self-start rounded-2xl rounded-bl-md border border-line bg-paper px-4 py-3" aria-label={`${peer} is typing`}>
              {[0, 1, 2].map((i) => (
                <span key={i} className="typing-dot size-1.5 rounded-full bg-ink-3" style={{ animationDelay: `${i * 0.15}s` }} />
              ))}
            </li>
          )}
        </ol>
      </div>

      {!text && !attachment && (
      <div className="flex gap-2 overflow-x-auto border-t border-line bg-paper px-3 pt-3 sm:px-5" role="group" aria-label="Quick replies">
        {(isCustomer ? CUSTOMER_REPLIES : PRO_REPLIES).map((r) => (
          <button
            key={r}
            type="button"
            onClick={() => setText(r)}
            className="shrink-0 rounded-full bg-plaster px-3 py-1 text-sm text-ink-2 transition-colors hover:bg-stellar-soft hover:text-stellar-ink"
          >
            {r}
          </button>
        ))}
      </div>
      )}

      <form onSubmit={send} className="bg-paper p-3 sm:px-5">
        {attachment && (
          <div className="mb-2 flex items-center gap-2 rounded-lg bg-plaster px-3 py-2 text-sm">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={attachment.dataUrl} alt="" className="size-10 rounded-lg object-cover" />
            <span className="flex-1 truncate">{attachment.name}</span>
            <button type="button" aria-label="Remove attachment" onClick={() => setAttachment(undefined)} className="grid size-8 place-items-center rounded-lg hover:bg-plaster-2">
              <X className="size-4" />
            </button>
          </div>
        )}
        <ErrorNote error={sendError} />
        <div className="flex items-end gap-2">
          <input ref={fileRef} type="file" accept="image/png,image/jpeg,image/webp,image/gif" className="hidden" onChange={(e) => pickFile(e.target.files?.[0])} />
          <Button type="button" variant="ghost" size="md" className="px-3" aria-label="Attach a photo" onClick={() => fileRef.current?.click()}>
            <ImagePlus className="size-5" />
          </Button>
          {!isCustomer && (
            <Button type="button" variant="outline" size="md" className="px-3 sm:px-4" onClick={() => setQuoteOpen(true)} aria-label="Send quotation">
              <FileText className="size-5" aria-hidden />
              <span className="hidden sm:inline">Quotation</span>
            </Button>
          )}
          <label htmlFor="composer" className="sr-only">
            Message
          </label>
          <textarea
            id="composer"
            rows={1}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
            placeholder={`Message ${peer.split(" ")[0]}`}
            className="max-h-32 min-h-11 flex-1 resize-none rounded-lg border border-line-2 bg-paper px-4 py-3 text-base focus:border-stellar"
          />
          <Button type="submit" size="md" className="px-4" loading={sending} disabled={!text.trim() && !attachment} aria-label="Send">
            {!sending && <SendHorizontal className="size-5" />}
          </Button>
        </div>
      </form>

      {!isCustomer && (
        <QuoteForm
          open={quoteOpen}
          onClose={() => setQuoteOpen(false)}
          conversationId={id}
          currency={data.professional.currency}
          nextVersion={data.quotes.length + 1}
        />
      )}
      <CallOverlay open={callOpen} onClose={() => setCallOpen(false)} conversationId={id} peerName={peer} />
      <ReportDialog open={reportOpen} onClose={() => setReportOpen(false)} peer={peer} />
      <Dialog open={!!quoteView} onClose={() => setQuoteView(null)} title={`Quotation from ${data.professional.name.split(" ")[0]}`}>
        {quoteView && <QuoteCard bare quote={quotes.get(quoteView.id) ?? quoteView} viewerIsCustomer={isCustomer} bookingId={bookingId} />}
      </Dialog>
    </div>

    <aside aria-label="Job details" className="hidden w-90 shrink-0 flex-col border-l border-line bg-paper 2xl:flex">
      <div className="border-b border-line px-5 py-4">
        <h2 className="font-semibold">The job</h2>
        <p className="text-sm text-ink-3">
          {bookingId ? "Agreement locked. Payment is handled in the booking." : latestQuote ? "Latest quotation" : "No quotation yet"}
        </p>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-5">
        {latestQuote ? (
          <QuoteCard bare quote={latestQuote} viewerIsCustomer={isCustomer} bookingId={bookingId} />
        ) : isCustomer ? (
          <p className="leading-relaxed text-ink-2">
            Describe the job and ask {peer.split(" ")[0]} for a quotation. It shows up here with the price breakdown, ready to accept.
          </p>
        ) : (
          <>
            <p className="leading-relaxed text-ink-2">When you know the scope, send a quotation. The customer accepts it and pays into escrow.</p>
            <Button className="mt-4" onClick={() => setQuoteOpen(true)}>
              Send quotation
            </Button>
          </>
        )}
      </div>
    </aside>
    </div>
  );
}

function QuoteMessage({ quote, viewerIsCustomer, onOpen }: { quote: Quote; viewerIsCustomer: boolean; onOpen: (q: Quote) => void }) {
  const status = quoteStatus(quote, viewerIsCustomer);
  const inactive = quote.status === "SUPERSEDED" || quote.status === "REJECTED";
  return (
    <button
      type="button"
      onClick={() => onOpen(quote)}
      className={cn(
        "w-full max-w-sm rounded-2xl border border-line bg-paper p-4 text-left transition-colors hover:border-ink-4",
        inactive && "opacity-60",
      )}
    >
      <span className="flex items-center justify-between gap-3">
        <span className="text-sm text-ink-3">Quotation, version {quote.version}</span>
        <Badge tone={status.tone}>{status.label}</Badge>
      </span>
      <span className="mt-2 block font-semibold leading-snug">{quote.title}</span>
      <span className="font-wide tnum mt-2 block text-xl font-bold">{money(quote.total, quote.currency)}</span>
      <span className="mt-2 block text-sm font-semibold text-stellar">View details</span>
    </button>
  );
}

function ReportDialog({ open, onClose, peer }: { open: boolean; onClose: () => void; peer: string }) {
  const toast = useToast();
  const [reason, setReason] = useState("Asked to pay outside UniFix");
  return (
    <Dialog open={open} onClose={onClose} title={`Report ${peer}`}>
      <form
        className="flex flex-col gap-4"
        onSubmit={(e) => {
          e.preventDefault();
          onClose();
          toast({ title: "Report sent", body: "UniFix operations will review this conversation.", tone: "ok" });
        }}
      >
        <Field label="What happened?">
          {(fid) => (
            <Select id={fid} value={reason} onChange={(e) => setReason(e.target.value)}>
              <option>Asked to pay outside UniFix</option>
              <option>Abusive or threatening language</option>
              <option>Spam or scam</option>
              <option>Something else</option>
            </Select>
          )}
        </Field>
        <Field label="Details (optional)">{(fid) => <Textarea id={fid} />}</Field>
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" variant="danger">
            Send report
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
