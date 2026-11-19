"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { ArrowRight } from "lucide-react";
import { api, IS_DEMO } from "@/lib/api";
import { DEMO_ACCOUNTS } from "@/lib/api/demo";
import { useSession } from "@/components/providers";
import { Avatar, Button, ErrorNote, Field, Input } from "@/components/ui";
import type { User } from "@/lib/types";

const home = (u: User) => (u.role === "admin" ? "/admin" : "/home");

export default function SignInPage() {
  const router = useRouter();
  const { refresh } = useSession();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [show, setShow] = useState(false);

  async function go(e: string, p: string) {
    setBusy(e);
    setError(null);
    try {
      const u = await api.signIn(e, p);
      await refresh();
      const next = new URLSearchParams(window.location.search).get("next");
      router.push(next?.startsWith("/") && !next.startsWith("//") ? next : home(u));
    } catch (err) {
      setError(err);
      setBusy(null);
    }
  }

  const tone = (role: string) =>
    role.startsWith("Admin")
      ? { label: "Admin", cls: "bg-clay-soft text-clay-ink" }
      : role.startsWith("Customer")
        ? { label: "Customer", cls: "bg-stellar-soft text-stellar-ink" }
        : { label: "Professional", cls: "bg-lagoon-soft text-lagoon-ink" };

  return (
    <div className="mx-auto max-w-lg">
      <p className="animate-rise text-sm font-semibold text-stellar">Welcome back</p>
      <h1 className="font-semiwide animate-rise mt-1 text-3xl font-bold sm:text-4xl" style={{ animationDelay: "0.05s" }}>
        Sign in to UniFix
      </h1>
      <p className="animate-rise mt-2 text-ink-3" style={{ animationDelay: "0.1s" }}>
        New here?{" "}
        <Link href="/sign-up" className="font-semibold text-stellar hover:underline">
          Create an account
        </Link>
      </p>

      <form
        className="animate-rise mt-8 flex flex-col gap-4"
        style={{ animationDelay: "0.15s" }}
        onSubmit={(e) => {
          e.preventDefault();
          go(email, password);
        }}
      >
        <Field label="Email">{(id) => <Input id={id} type="email" autoComplete="email" placeholder="you@example.com" required value={email} onChange={(e) => setEmail(e.target.value)} />}</Field>
        <Field label="Password" hint={IS_DEMO ? "Demo mode accepts any password." : undefined}>
          {(id) => (
            <div className="relative">
              <Input
                id={id}
                type={show ? "text" : "password"}
                autoComplete="current-password"
                required={!IS_DEMO}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="pr-16"
              />
              <button
                type="button"
                onClick={() => setShow((x) => !x)}
                className="absolute right-2 top-1/2 -translate-y-1/2 rounded-md px-2 py-1 text-sm font-semibold text-ink-3 hover:text-ink"
              >
                {show ? "Hide" : "Show"}
              </button>
            </div>
          )}
        </Field>
        <ErrorNote error={error} />
        <Button type="submit" size="lg" loading={busy === email && !!email}>
          Sign in
          <ArrowRight className="size-4" aria-hidden />
        </Button>
      </form>

      {IS_DEMO && (
        <div className="animate-rise mt-10" style={{ animationDelay: "0.25s" }}>
          <div className="flex items-center gap-3">
            <span className="h-px flex-1 bg-line" />
            <span className="text-sm font-semibold text-ink-3">or try a demo account</span>
            <span className="h-px flex-1 bg-line" />
          </div>
          <p className="mt-2 text-center text-sm text-ink-3">Switch between them to play both sides of a booking.</p>
          <ul className="mt-5 grid gap-3 sm:grid-cols-2">
            {DEMO_ACCOUNTS.map((a) => {
              const t = tone(a.role);
              return (
                <li key={a.email}>
                  <button
                    type="button"
                    onClick={() => go(a.email, "demo")}
                    disabled={!!busy}
                    className="group flex h-full w-full flex-col gap-3 rounded-2xl border border-line bg-paper p-4 text-left transition duration-300 hover:-translate-y-0.5 hover:border-stellar hover:shadow-lift disabled:opacity-60"
                  >
                    <span className="flex w-full items-center justify-between">
                      <Avatar name={a.name} size={36} />
                      <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${t.cls}`}>{t.label}</span>
                    </span>
                    <span>
                      <span className="block font-semibold transition-colors group-hover:text-stellar">{a.name}</span>
                      <span className="mt-0.5 block text-sm text-ink-3">{a.role}</span>
                    </span>
                    <span className="mt-auto flex items-center gap-1 text-sm font-semibold text-stellar">
                      {busy === a.email ? "Signing in…" : "Continue"}
                      <ArrowRight className="size-4 transition-transform group-hover:translate-x-1" aria-hidden />
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}
