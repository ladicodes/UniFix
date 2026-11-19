"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { Search } from "lucide-react";
import { categoryLabel, cn, timeAgo } from "@/lib/format";
import { useConversations } from "@/lib/hooks";
import { useSession } from "@/components/providers";
import { Avatar, Skeleton } from "@/components/ui";

export default function MessagesLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { user } = useSession();
  const { data, isLoading } = useConversations(!!user);
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState<"all" | "unread">("all");
  const inThread = pathname !== "/messages";
  const unreadCount = data?.filter((c) => c.unread).length ?? 0;

  const rows = (data ?? []).filter((r) => {
    if (filter === "unread" && !r.unread) return false;
    if (!q.trim()) return true;
    const other = user?.id === r.conversation.customerId ? r.professional.name : r.customer.name;
    return `${other} ${r.conversation.lastMessagePreview}`.toLowerCase().includes(q.trim().toLowerCase());
  });

  return (
    <div className="-mx-4 -my-6 grid h-[calc(100dvh-10rem)] grid-rows-[minmax(0,1fr)] overflow-hidden bg-paper sm:-mx-6 sm:-my-8 md:mx-0 md:my-0 md:h-[calc(100dvh-11rem)] md:grid-cols-[22rem_minmax(0,1fr)] md:rounded-2xl md:border md:border-line md:shadow-xs lg:h-[calc(100dvh-9.5rem)]">
      <aside className={cn("flex min-h-0 flex-col md:border-r md:border-line", inThread && "hidden md:flex")}>
        <div className="space-y-4 px-5 pb-0 pt-6 md:pt-5">
          <div className="flex items-baseline justify-between">
            <h1 className="font-semiwide text-2xl font-bold">Messages</h1>
            {unreadCount > 0 && <span className="text-sm font-semibold text-stellar">{unreadCount} unread</span>}
          </div>
          <div className="relative">
            <Search className="pointer-events-none absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-ink-3" aria-hidden />
            <input
              type="search"
              aria-label="Search messages"
              placeholder="Search messages"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              className="h-11 w-full rounded-xl border border-line bg-plaster pl-10 pr-4 text-base outline-none transition placeholder:text-ink-3 focus-visible:border-stellar focus-visible:bg-paper focus-visible:ring-4 focus-visible:ring-stellar-soft"
            />
          </div>
          <div className="flex gap-5" role="group" aria-label="Filter conversations">
            {(["all", "unread"] as const).map((f) => (
              <button
                key={f}
                aria-pressed={filter === f}
                onClick={() => setFilter(f)}
                className={cn(
                  "relative pb-3 text-sm font-semibold transition-colors",
                  filter === f ? "text-ink after:absolute after:inset-x-0 after:bottom-0 after:h-0.5 after:rounded-full after:bg-ink" : "text-ink-3 hover:text-ink",
                )}
              >
                {f === "all" ? "All" : `Unread${unreadCount ? ` (${unreadCount})` : ""}`}
              </button>
            ))}
          </div>
        </div>
        <ul className="min-h-0 flex-1 overflow-y-auto border-t border-line py-2">
          {isLoading &&
            [0, 1, 2].map((i) => (
              <li key={i} className="flex gap-3 px-4 py-4">
                <Skeleton className="size-11 rounded-full" />
                <div className="flex-1 space-y-2">
                  <Skeleton className="h-3.5 w-32" />
                  <Skeleton className="h-3 w-44" />
                </div>
              </li>
            ))}
          {!isLoading && rows.length === 0 && (
            <li className="px-4 py-8 text-sm text-ink-3">
              {q || filter === "unread" ? (
                "No conversations match."
              ) : (
                <>
                  No conversations yet.{" "}
                  {user?.role === "customer" && (
                    <Link href="/discover" className="font-semibold text-stellar hover:underline">
                      Find a professional
                    </Link>
                  )}
                </>
              )}
            </li>
          )}
          {rows.map(({ conversation: c, professional, customer, unread }) => {
            const viewerIsCustomer = user?.id === c.customerId;
            const other = viewerIsCustomer ? professional.name : customer.name;
            const online = viewerIsCustomer && professional.availability === "now";
            const sub = viewerIsCustomer ? categoryLabel(professional.category) : customer.city;
            const active = pathname === `/messages/${c.id}`;
            return (
              <li key={c.id}>
                <Link
                  href={`/messages/${c.id}`}
                  aria-current={active ? "page" : undefined}
                  className={cn("relative mx-2 my-0.5 flex gap-3 rounded-xl px-3 py-3 transition-colors", active ? "bg-stellar-soft" : "hover:bg-plaster")}
                >
                                    <span className="relative">
                    <Avatar name={other} size={46} />
                    {online && <span className="absolute bottom-0 right-0 size-3 rounded-full border-2 border-paper bg-lagoon" aria-label="Online" />}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-baseline justify-between gap-2">
                      <p className={cn("truncate", unread ? "font-semibold text-ink" : "font-semibold text-ink-2")}>{other}</p>
                      <span className={cn("shrink-0 text-xs", unread ? "font-semibold text-stellar" : "text-ink-3")}>{timeAgo(c.lastMessageAt)}</span>
                    </div>
                    <p className="truncate text-xs text-ink-3">{sub}</p>
                    <div className="mt-0.5 flex items-center gap-2">
                      <p className={cn("min-w-0 flex-1 truncate text-sm", unread ? "font-semibold text-ink" : "text-ink-3")}>{c.lastMessagePreview}</p>
                      {unread && <span className="size-2 shrink-0 rounded-full bg-stellar" aria-label="Unread" />}
                    </div>
                  </div>
                </Link>
              </li>
            );
          })}
        </ul>
      </aside>
      <section className={cn("min-h-0 min-w-0", !inThread && "hidden md:block")}>{children}</section>
    </div>
  );
}
