"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { Check, Hammer, House } from "lucide-react";
import { api } from "@/lib/api";
import type { SignUpInput } from "@/lib/api";
import { CATEGORIES, cn } from "@/lib/format";
import type { CategoryId, Professional } from "@/lib/types";
import { useSession } from "@/components/providers";
import { Button, ErrorNote, Field, Input, Select, Textarea } from "@/components/ui";

const CITIES = [
  { city: "Lagos", country: "NG" as const },
  { city: "Abuja", country: "NG" as const },
  { city: "Accra", country: "GH" as const },
  { city: "Kumasi", country: "GH" as const },
];

function SignUpForm() {
  const params = useSearchParams();
  const router = useRouter();
  const { refresh } = useSession();
  const [role, setRole] = useState<"customer" | "professional">(params.get("role") === "professional" ? "professional" : "customer");
  const [step, setStep] = useState<1 | 2>(1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const [acct, setAcct] = useState({ name: "", email: "", password: "", city: "Lagos" });
  const [pro, setPro] = useState({
    category: "electrician" as CategoryId,
    headline: "",
    bio: "",
    area: "",
    coverage: "",
    yearsExperience: 3,
    startingPrice: 10000,
    availability: "today" as Professional["availability"],
    skills: "",
  });

  const country = CITIES.find((c) => c.city === acct.city)!.country;

  async function submit() {
    setBusy(true);
    setError(null);
    const input: SignUpInput = {
      ...acct,
      role,
      country,
      professional:
        role === "professional"
          ? {
              ...pro,
              coverage: pro.coverage.split(",").map((s) => s.trim()).filter(Boolean),
              skills: pro.skills.split(",").map((s) => s.trim()).filter(Boolean),
            }
          : undefined,
    };
    try {
      await api.signUp(input);
      await refresh();
      router.push("/home");
    } catch (e) {
      setError(e);
      setBusy(false);
    }
  }

  return (
    <div>
      <h1 className="font-semiwide text-3xl font-bold">{step === 1 ? "Create your account" : "Your professional profile"}</h1>
      <p className="mt-2 text-ink-3">
        {step === 1 ? (
          <>
            Already on Handi?{" "}
            <Link href="/sign-in" className="font-semibold text-stellar hover:underline">
              Sign in
            </Link>
          </>
        ) : (
          "Customers see this when they compare professionals. Verification documents stay private."
        )}
      </p>

      {step === 1 ? (
        <form
          className="mt-8 flex flex-col gap-5"
          onSubmit={(e) => {
            e.preventDefault();
            if (role === "professional") setStep(2);
            else submit();
          }}
        >
          <fieldset>
            <legend className="text-sm font-semibold">I want to</legend>
            <div className="mt-2 grid grid-cols-2 gap-2">
              {[
                { v: "customer" as const, icon: House, t: "Hire a professional" },
                { v: "professional" as const, icon: Hammer, t: "Offer my services" },
              ].map((o) => (
                <label
                  key={o.v}
                  className={cn(
                    "relative flex cursor-pointer flex-col gap-3 rounded-2xl border-2 bg-paper p-4 transition-colors",
                    role === o.v ? "border-stellar" : "border-line hover:border-line-2",
                  )}
                >
                  <input type="radio" name="role" value={o.v} checked={role === o.v} onChange={() => setRole(o.v)} className="sr-only" />
                  <o.icon className="size-5" aria-hidden />
                  <span className="font-semibold leading-tight">{o.t}</span>
                  {role === o.v && <Check className="absolute right-3 top-3 size-4" aria-hidden />}
                </label>
              ))}
            </div>
          </fieldset>
          <Field label="Full name">{(id) => <Input id={id} required autoComplete="name" value={acct.name} onChange={(e) => setAcct({ ...acct, name: e.target.value })} />}</Field>
          <Field label="Email">{(id) => <Input id={id} type="email" required autoComplete="email" value={acct.email} onChange={(e) => setAcct({ ...acct, email: e.target.value })} />}</Field>
          <Field label="Password" hint="At least 8 characters.">
            {(id) => <Input id={id} type="password" required minLength={8} autoComplete="new-password" value={acct.password} onChange={(e) => setAcct({ ...acct, password: e.target.value })} />}
          </Field>
          <Field label="City">
            {(id) => (
              <Select id={id} value={acct.city} onChange={(e) => setAcct({ ...acct, city: e.target.value })}>
                {CITIES.map((c) => (
                  <option key={c.city}>{c.city}</option>
                ))}
              </Select>
            )}
          </Field>
          <ErrorNote error={error} />
          <Button type="submit" size="lg" loading={busy}>
            {role === "professional" ? "Continue to profile" : "Create account"}
          </Button>
        </form>
      ) : (
        <form
          className="mt-8 flex flex-col gap-5"
          onSubmit={(e) => {
            e.preventDefault();
            submit();
          }}
        >
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Service">
              {(id) => (
                <Select id={id} value={pro.category} onChange={(e) => setPro({ ...pro, category: e.target.value as CategoryId })}>
                  {CATEGORIES.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.label}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            <Field label="Years of experience">
              {(id) => <Input id={id} type="number" min={0} max={60} value={pro.yearsExperience} onChange={(e) => setPro({ ...pro, yearsExperience: Number(e.target.value) })} />}
            </Field>
          </div>
          <Field label="Headline" hint="One line about what you do best.">
            {(id) => <Input id={id} required maxLength={90} placeholder="House wiring, inverter and solar backup" value={pro.headline} onChange={(e) => setPro({ ...pro, headline: e.target.value })} />}
          </Field>
          <Field label="About your work">
            {(id) => <Textarea id={id} required maxLength={600} value={pro.bio} onChange={(e) => setPro({ ...pro, bio: e.target.value })} />}
          </Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Base area">{(id) => <Input id={id} required placeholder="Yaba" value={pro.area} onChange={(e) => setPro({ ...pro, area: e.target.value })} />}</Field>
            <Field label={`Starting price (${country === "NG" ? "₦" : "GH₵"})`}>
              {(id) => <Input id={id} type="number" min={0} value={pro.startingPrice} onChange={(e) => setPro({ ...pro, startingPrice: Number(e.target.value) })} />}
            </Field>
          </div>
          <Field label="Areas you cover" hint="Separate with commas.">
            {(id) => <Input id={id} placeholder="Yaba, Surulere, Ikoyi" value={pro.coverage} onChange={(e) => setPro({ ...pro, coverage: e.target.value })} />}
          </Field>
          <Field label="Skills" hint="Separate with commas.">
            {(id) => <Input id={id} placeholder="Rewiring, fault tracing" value={pro.skills} onChange={(e) => setPro({ ...pro, skills: e.target.value })} />}
          </Field>
          <Field label="Availability">
            {(id) => (
              <Select id={id} value={pro.availability} onChange={(e) => setPro({ ...pro, availability: e.target.value as Professional["availability"] })}>
                <option value="now">Available now</option>
                <option value="today">Available today</option>
                <option value="this-week">This week</option>
              </Select>
            )}
          </Field>
          <p className="rounded-lg bg-plaster-2 px-4 py-3 text-sm text-ink-2">
            After sign-up, upload ID and trade certificates from your profile settings to get the verified badges. Until then your
            profile shows as unverified.
          </p>
          <ErrorNote error={error} />
          <div className="flex gap-2">
            <Button type="button" variant="outline" size="lg" onClick={() => setStep(1)}>
              Back
            </Button>
            <Button type="submit" size="lg" loading={busy} className="flex-1">
              Create professional account
            </Button>
          </div>
        </form>
      )}
    </div>
  );
}

export default function SignUpPage() {
  return (
    <Suspense>
      <SignUpForm />
    </Suspense>
  );
}
