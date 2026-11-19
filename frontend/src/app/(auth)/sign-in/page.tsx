"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
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

  return (
    <div>
      <h1 className="font-semiwide text-3xl font-bold">Sign in</h1>
      <p className="mt-2 text-ink-3">
        New to UniFix?{" "}
        <Link href="/sign-up" className="font-semibold text-stellar hover:underline">
          Create an account
        </Link>
      </p>

      <form
        className="mt-8 flex flex-col gap-4"
        onSubmit={(e) => {
          e.preventDefault();
          go(email, password);
        }}
      >
        <Field label="Email">{(id) => <Input id={id} type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />}</Field>
        <Field label="Password" hint={IS_DEMO ? "Demo mode accepts any password." : undefined}>
          {(id) => <Input id={id} type="password" autoComplete="current-password" required={!IS_DEMO} value={password} onChange={(e) => setPassword(e.target.value)} />}
        </Field>
        <ErrorNote error={error} />
        <Button type="submit" size="lg" loading={busy === email && !!email}>
          Sign in
        </Button>
      </form>

      {IS_DEMO && (
        <div className="mt-10">
          <h2 className="font-semibold">Or continue as a demo account</h2>
          <p className="mt-1 text-sm text-ink-3">Switch between them to play both sides of a booking.</p>
          <ul className="mt-4 divide-y divide-line border-y border-line">
            {DEMO_ACCOUNTS.map((a) => (
              <li key={a.email}>
                <button
                  onClick={() => go(a.email, "demo")}
                  disabled={!!busy}
                  className="group flex w-full items-center gap-3 py-3 text-left disabled:opacity-60"
                >
                  <Avatar name={a.name} size={38} />
                  <span className="flex-1">
                    <span className="block font-semibold transition-colors group-hover:text-stellar">{a.name}</span>
                    <span className="block text-sm text-ink-3">{a.role}</span>
                  </span>
                  {busy === a.email && <span className="text-sm text-ink-3">Signing in…</span>}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
