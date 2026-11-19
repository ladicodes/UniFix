"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ArrowRight, Menu, X } from "lucide-react";
import { useSession } from "@/components/providers";
import { Avatar, Logo } from "@/components/ui";
import { cn } from "@/lib/format";

const LINKS = [
  { href: "#how", label: "How it works" },
  { href: "#services", label: "Services" },
  { href: "#safety", label: "Disputes" },
  { href: "#pros", label: "For professionals" },
];

export function LandingNav() {
  const { user } = useSession();
  const [scrolled, setScrolled] = useState(false);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const on = () => setScrolled(window.scrollY > 8);
    on();
    window.addEventListener("scroll", on, { passive: true });
    return () => window.removeEventListener("scroll", on);
  }, []);

  const home = user ? (user.role === "admin" ? "/admin" : "/home") : "/sign-up";

  return (
    <header className={cn("sticky top-0 z-40 border-b bg-paper transition-colors", scrolled || open ? "border-line" : "border-transparent")}>
      <div className="grid h-18 grid-cols-[1fr_auto] items-center gap-4 px-4 sm:px-6 lg:grid-cols-[1fr_auto_1fr] lg:px-10">
        <Link href="/" aria-label="UniFix home" className="justify-self-start">
          <Logo />
        </Link>

        <nav aria-label="Sections" className="hidden items-center gap-1 rounded-full border border-line bg-plaster p-1 lg:flex">
          {LINKS.map((l) => (
            <a key={l.href} href={l.href} className="rounded-full px-4 py-2 text-sm font-semibold text-ink-2 transition-colors hover:bg-paper hover:text-ink">
              {l.label}
            </a>
          ))}
        </nav>

        <div className="flex items-center gap-2 justify-self-end">
          {user ? (
            <Link
              href={home}
              className="group inline-flex h-11 items-center gap-2 rounded-full border border-line bg-paper py-1 pl-1 pr-4 text-sm font-semibold text-ink transition-colors hover:border-line-2"
            >
              <Avatar name={user.name} size={34} />
              <span className="hidden sm:inline">Go to dashboard</span>
              <ArrowRight className="size-4 transition-transform group-hover:translate-x-0.5" aria-hidden />
            </Link>
          ) : (
            <>
              <Link href="/sign-in" className="hidden rounded-lg px-3 py-2 text-sm font-semibold text-ink-2 hover:text-ink sm:block">
                Sign in
              </Link>
              <Link
                href="/sign-up"
                className="group inline-flex h-11 items-center gap-2 rounded-full bg-ink px-5 text-sm font-semibold text-white transition-colors hover:bg-stellar"
              >
                Get started
                <ArrowRight className="size-4 transition-transform group-hover:translate-x-0.5" aria-hidden />
              </Link>
            </>
          )}
          <button
            type="button"
            onClick={() => setOpen((o) => !o)}
            aria-expanded={open}
            aria-controls="landing-menu"
            aria-label={open ? "Close menu" : "Open menu"}
            className="grid size-11 place-items-center rounded-full border border-line lg:hidden"
          >
            {open ? <X className="size-5" aria-hidden /> : <Menu className="size-5" aria-hidden />}
          </button>
        </div>
      </div>

      {open && (
        <nav id="landing-menu" aria-label="Sections" className="border-t border-line px-4 pb-4 pt-2 sm:px-6 lg:hidden">
          <ul>
            {LINKS.map((l) => (
              <li key={l.href}>
                <a href={l.href} onClick={() => setOpen(false)} className="block rounded-lg px-2 py-3 font-semibold text-ink-2 hover:bg-plaster hover:text-ink">
                  {l.label}
                </a>
              </li>
            ))}
            {!user && (
              <li>
                <Link href="/sign-in" className="block rounded-lg px-2 py-3 font-semibold text-ink-2 hover:bg-plaster hover:text-ink">
                  Sign in
                </Link>
              </li>
            )}
          </ul>
        </nav>
      )}
    </header>
  );
}
