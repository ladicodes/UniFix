import Link from "next/link";
import { Lock, MessageCircle } from "lucide-react";

/* Shown beside the list until a conversation is open. */
export default function MessagesIndex() {
  return (
    <div className="grid h-full place-items-center p-10 text-center">
      <div className="max-w-sm">
        <div className="relative mx-auto h-36 w-64" aria-hidden>
          <span className="absolute left-0 top-2 w-44 rounded-2xl rounded-bl-md border border-line bg-paper px-4 py-3 text-left text-sm text-ink-2 shadow-lift">
            Can you come Thursday?
          </span>
          <span className="absolute right-0 top-14 w-48 rounded-2xl rounded-br-md bg-stellar px-4 py-3 text-left text-sm text-white shadow-lift">
            Yes. Quotation on the way.
          </span>
          <span className="absolute bottom-0 left-8 flex items-center gap-2 rounded-full bg-danfo-soft px-3 py-1.5 text-xs font-semibold text-danfo-ink">
            <Lock className="size-3.5" />
            Paid through escrow
          </span>
        </div>
        <p className="font-semiwide mt-8 text-xl font-bold">Pick a conversation</p>
        <p className="mt-2 text-ink-3">Chats, quotations, payment updates and job photos for each booking live in one thread.</p>
        <Link
          href="/discover"
          className="mt-6 inline-flex h-11 items-center gap-2 rounded-lg border border-line bg-paper px-4 text-sm font-semibold text-ink shadow-xs hover:border-line-2"
        >
          <MessageCircle className="size-4" aria-hidden />
          Message a professional
        </Link>
      </div>
    </div>
  );
}
