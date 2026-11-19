"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { Bell, BriefcaseBusiness, ChevronDown, House, LogOut, MessageCircle, RotateCcw, Scale, Search, UserRound, Wallet } from "lucide-react";
import { api, IS_DEMO } from "@/lib/api";
import { DEMO_ACCOUNTS, resetDemo } from "@/lib/api/demo";
import { nextStep } from "@/lib/booking";
import { cn, shortAddress, timeAgo } from "@/lib/format";
import { useBookings, useConversations, useNotifications } from "@/lib/hooks";
import { useSession, useToast, useWallet } from "./providers";
import { Avatar, Logo } from "./ui";

const PUBLIC = [/^\/discover/, /^\/pros\//];

type NavItem = { href: string; label: string; icon: typeof Search; count?: number; urgent?: boolean; mobile?: boolean };

function useNav(): NavItem[] {
  const { user } = useSession();
  const { data: convos } = useConversations(!!user);
  const { data: bookings } = useBookings(!!user && user.role !== "admin");
  const unread = convos?.filter((c) => c.unread).length ?? 0;
  const todo = user ? (bookings ?? []).filter((b) => nextStep(b, b.booking.customerId === user.id)).length : 0;

  if (!user) return [{ href: "/discover", label: "Find", icon: Search }];
  if (user.role === "admin")
    return [
      { href: "/admin", label: "Disputes", icon: Scale },
      { href: "/profile", label: "Profile", icon: UserRound },
    ];
  return [
    { href: "/home", label: "Home", icon: House, mobile: true },
    ...(user.role === "customer" ? [{ href: "/discover", label: "Find", icon: Search, mobile: true }] : []),
    { href: "/messages", label: "Messages", icon: MessageCircle, count: unread, urgent: unread > 0, mobile: true },
    { href: "/bookings", label: "Bookings", icon: BriefcaseBusiness, count: todo, urgent: todo > 0, mobile: true },
    { href: "/wallet", label: "Wallet", icon: Wallet, mobile: user.role === "professional" },
    { href: "/profile", label: "Profile", icon: UserRound, mobile: user.role === "professional" },
  ];
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { user, ready } = useSession();
  const nav = useNav();
  const mobileNav = nav.filter((n) => n.mobile !== false);

  useEffect(() => {
    if (ready && !user && !PUBLIC.some((r) => r.test(pathname))) router.replace(`/sign-in?next=${encodeURIComponent(pathname)}`);
  }, [ready, user, pathname, router]);

  return (
    <div className="min-h-dvh bg-plaster pb-20 lg:pb-0">
      {IS_DEMO && (
        <div className="bg-ink px-4 py-1.5 text-center text-xs text-mist">
          Demo mode: payments are simulated and data stays in this browser.
          <span className="hidden sm:inline">
            {" "}
            Set <code className="font-semibold text-white">NEXT_PUBLIC_API_URL</code> to use the live backend.
          </span>
        </div>
      )}

      <header className="sticky top-0 z-40 border-b border-line bg-paper/95 backdrop-blur supports-[backdrop-filter]:bg-paper/85">
        <div className="flex h-16 items-center gap-6 px-4 sm:px-6 lg:px-10">
          <Link href="/" aria-label="UniFix home" className="shrink-0">
            <Logo />
          </Link>

          {user && (
            <nav aria-label="Main" className="hidden h-16 items-stretch gap-1 lg:flex">
              {nav.map((n) => {
                const active = pathname.startsWith(n.href);
                return (
                  <Link
                    key={n.href}
                    href={n.href}
                    aria-current={active ? "page" : undefined}
                    className={cn(
                      "relative flex items-center gap-2 px-3 text-sm font-semibold transition-colors",
                      active ? "text-ink" : "text-ink-3 hover:text-ink",
                    )}
                  >
                    <n.icon className="size-4" aria-hidden />
                    {n.label}
                    {!!n.count && (
                      <span className={cn("tnum grid h-5 min-w-5 place-items-center rounded-full px-1.5 text-xs", n.urgent ? "bg-stellar text-white" : "bg-plaster text-ink-3")}>
                        {n.count}
                      </span>
                    )}
                    {active && <motion.span layoutId="nav-underline" className="absolute inset-x-3 -bottom-px h-0.5 rounded-full bg-ink" transition={{ type: "spring", stiffness: 500, damping: 40 }} />}
                  </Link>
                );
              })}
            </nav>
          )}

          {!user && (
            <nav className="hidden items-center gap-1 md:flex" aria-label="Main">
              <Link href="/discover" className="rounded-lg px-3 py-2 text-sm font-semibold text-ink">
                Find professionals
              </Link>
            </nav>
          )}

          <div className="ml-auto flex items-center gap-2">
            {user ? (
              <>
                <WalletChip />
                <NotificationsMenu />
                <AccountMenu />
              </>
            ) : (
              ready && (
                <Link href="/sign-in" className="rounded-lg bg-stellar px-4 py-2 text-sm font-semibold text-white hover:bg-stellar-ink">
                  Sign in
                </Link>
              )
            )}
          </div>
        </div>
      </header>

      <main className="min-w-0 px-4 py-6 sm:px-6 sm:py-8 lg:px-10">{children}</main>

      {user && (
        <nav aria-label="Main" className="fixed inset-x-0 bottom-0 z-40 border-t border-line bg-paper lg:hidden">
          <ul className="grid" style={{ gridTemplateColumns: `repeat(${mobileNav.length}, minmax(0,1fr))` }}>
            {mobileNav.map((n) => {
              const active = pathname.startsWith(n.href);
              return (
                <li key={n.href}>
                  <Link
                    href={n.href}
                    aria-current={active ? "page" : undefined}
                    className={cn("relative flex flex-col items-center gap-1 py-3 text-xs font-semibold", active ? "text-stellar" : "text-ink-3")}
                  >
                    <n.icon className="size-5" aria-hidden />
                    {n.label}
                    {n.urgent && <span className="absolute right-1/2 top-2 mr-[-14px] size-2 rounded-full bg-stellar" aria-label={`${n.count} need attention`} />}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
      )}
    </div>
  );
}

/* Avatar button with the account, demo switcher and sign out. */
function AccountMenu() {
  const router = useRouter();
  const toast = useToast();
  const { user, signOut, refresh } = useSession();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useOutside(ref, () => setOpen(false));
  if (!user) return null;

  async function switchTo(email: string) {
    const u = await api.signIn(email, "demo");
    await refresh();
    setOpen(false);
    toast({ title: `Now viewing as ${u.name}`, tone: "info" });
    router.push(u.role === "admin" ? "/admin" : "/home");
  }

  const item = "flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm hover:bg-plaster";

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-label="Account menu"
        className="flex items-center gap-2 rounded-full p-0.5 pr-2 transition-colors hover:bg-plaster"
      >
        <Avatar name={user.name} size={34} />
        <ChevronDown className={cn("size-4 text-ink-3 transition-transform", open && "rotate-180")} aria-hidden />
      </button>
      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: -6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -6 }}
            transition={{ duration: 0.15 }}
            className="absolute right-0 top-12 z-50 w-72 overflow-hidden rounded-2xl border border-line bg-paper p-2 shadow-lift"
          >
            <Link href="/profile" onClick={() => setOpen(false)} className="flex items-center gap-3 rounded-xl p-2 hover:bg-plaster">
              <Avatar name={user.name} size={40} />
              <span className="min-w-0">
                <span className="block truncate font-semibold">{user.name}</span>
                <span className="block truncate text-sm text-ink-3">{user.email}</span>
              </span>
            </Link>
            <div className="my-2 h-px bg-line" />
            <Link href="/profile" onClick={() => setOpen(false)} className={item}>
              <UserRound className="size-4 text-ink-3" aria-hidden />
              Profile and settings
            </Link>
            {user.role !== "admin" && (
              <Link href="/wallet" onClick={() => setOpen(false)} className={item}>
                <Wallet className="size-4 text-ink-3" aria-hidden />
                Wallet
              </Link>
            )}
            {IS_DEMO && (
              <>
                <div className="my-2 h-px bg-line" />
                <p className="px-3 pb-1 pt-1 text-xs font-semibold text-ink-3">Switch demo account</p>
                {DEMO_ACCOUNTS.filter((a) => a.email !== user.email).map((a) => (
                  <button key={a.email} onClick={() => switchTo(a.email)} className={item}>
                    <Avatar name={a.name} size={26} />
                    <span className="min-w-0">
                      <span className="block truncate font-semibold">{a.name}</span>
                      <span className="block truncate text-xs text-ink-3">{a.role}</span>
                    </span>
                  </button>
                ))}
                <button
                  onClick={() => {
                    resetDemo();
                    setOpen(false);
                    toast({ title: "Demo data reset", body: "Bookings and messages are back to the starting state.", tone: "info" });
                  }}
                  className={item}
                >
                  <RotateCcw className="size-4 text-ink-3" aria-hidden />
                  Reset demo data
                </button>
              </>
            )}
            <div className="my-2 h-px bg-line" />
            <button
              onClick={async () => {
                await signOut();
                router.push("/");
              }}
              className={cn(item, "text-clay-ink hover:bg-clay-soft")}
            >
              <LogOut className="size-4" aria-hidden />
              Sign out
            </button>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function WalletChip() {
  const w = useWallet();
  const { user } = useSession();
  if (user?.role === "admin") return null;
  return (
    <Link
      href="/wallet"
      className={cn(
        "hidden h-9 items-center gap-2 rounded-lg border px-3 text-sm font-semibold sm:inline-flex",
        w.address ? "border-transparent bg-stellar-soft text-stellar-ink" : "border-line bg-paper text-ink-2 hover:border-ink-4",
      )}
    >
      <span className={cn("size-2 rounded-full", w.address ? (w.wrongNetwork ? "bg-clay" : "bg-lagoon") : "bg-ink-4")} aria-hidden />
      {w.address ? shortAddress(w.address) : "Connect wallet"}
    </Link>
  );
}

function useOutside(ref: React.RefObject<HTMLElement | null>, onOut: () => void) {
  useEffect(() => {
    const h = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && onOut();
    const k = (e: KeyboardEvent) => e.key === "Escape" && onOut();
    document.addEventListener("mousedown", h);
    document.addEventListener("keydown", k);
    return () => {
      document.removeEventListener("mousedown", h);
      document.removeEventListener("keydown", k);
    };
  }, [ref, onOut]);
}

function NotificationsMenu() {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useOutside(ref, () => setOpen(false));
  const { data } = useNotifications();
  const unread = data?.filter((n) => !n.read).length ?? 0;

  return (
    <div ref={ref} className="relative">
      <button
        aria-label={`Notifications${unread ? `, ${unread} unread` : ""}`}
        aria-expanded={open}
        onClick={() => {
          setOpen((o) => !o);
          if (!open && unread) setTimeout(() => api.markNotificationsRead(), 1500);
        }}
        className="relative grid size-10 place-items-center rounded-lg hover:bg-plaster"
      >
        <Bell className="size-5" />
        {unread > 0 && <span className="absolute right-2 top-2 size-2 rounded-full bg-clay" />}
      </button>
      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: -6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -6 }}
            transition={{ duration: 0.15 }}
            className="fixed inset-x-3 top-18 z-50 overflow-hidden rounded-2xl border border-line bg-paper shadow-lift sm:absolute sm:inset-x-auto sm:right-0 sm:top-12 sm:w-96"
          >
            <p className="border-b border-line px-4 py-3 font-semibold">Notifications</p>
            <ul className="max-h-[60vh] divide-y divide-line overflow-y-auto">
              {!data?.length && <li className="px-4 py-6 text-sm text-ink-3">Nothing yet. Updates about your jobs and payments appear here.</li>}
              {data?.map((n) => (
                <li key={n.id}>
                  <Link href={n.href} onClick={() => setOpen(false)} className="flex gap-3 px-4 py-3 hover:bg-plaster">
                    <span className={cn("mt-2 size-2 shrink-0 rounded-full", n.read ? "bg-transparent" : "bg-stellar")} aria-hidden />
                    <span className="min-w-0">
                      <span className="block text-sm font-semibold">{n.title}</span>
                      <span className="block truncate text-sm text-ink-3">{n.body}</span>
                      <span className="mt-1 block text-xs text-ink-3">{timeAgo(n.at)}</span>
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
