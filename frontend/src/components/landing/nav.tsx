"use client";

import Link from "next/link";
import { useSession } from "@/components/providers";
import { Logo } from "@/components/ui";

export function LandingNav() {
  const { user } = useSession();
  return (
    <header className="flex w-full items-center justify-between gap-4 px-4 py-5 sm:px-6 lg:px-10">
      <Link href="/" aria-label="Handi home">
        <Logo />
      </Link>
      <nav className="flex items-center gap-1 text-base font-semibold sm:gap-2">
        <a href="#how" className="hidden rounded-lg px-3 py-2 hover:bg-plaster-2 md:block">
          How it works
        </a>
        <a href="#pros" className="hidden rounded-lg px-3 py-2 hover:bg-plaster-2 md:block">
          For professionals
        </a>
        {user ? (
          <Link href={user.role === "admin" ? "/admin" : "/home"} className="rounded-lg bg-stellar px-4 py-3 text-white hover:bg-stellar-ink">
            Open Handi
          </Link>
        ) : (
          <>
            <Link href="/sign-in" className="rounded-lg px-3 py-2 hover:bg-plaster-2">
              Sign in
            </Link>
            <Link href="/sign-up" className="rounded-lg bg-stellar px-4 py-3 text-white hover:bg-stellar-ink">
              Create account
            </Link>
          </>
        )}
      </nav>
    </header>
  );
}
