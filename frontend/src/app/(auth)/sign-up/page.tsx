"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { AnimatePresence, MotionConfig, motion } from "motion/react";
import { ArrowLeft, ArrowRight, BadgeCheck, Bell, Check, Hammer, House, Lock, Star } from "lucide-react";
import { api } from "@/lib/api";
import type { SignUpInput } from "@/lib/api";
import { CATEGORIES, cn } from "@/lib/format";
import type { CategoryId, Professional } from "@/lib/types";
import { useSession } from "@/components/providers";
import { Button, ErrorNote, Field, Input, Select, Textarea } from "@/components/ui";

const EASE = [0.22, 1, 0.36, 1] as const;

type Role = "customer" | "professional";
type Step = "role" | "account" | "profile";

const ROLES = [
  {
    v: "customer" as const,
    Icon: House,
    t: "Hire a professional",
    d: "Hire a verified professional and pay only when the job is done.",
    perks: ["Compare verified ratings", "Locked quotations", "Payment held in escrow"],
  },
  {
    v: "professional" as const,
    Icon: Hammer,
    t: "Offer my services",
    d: "Offer your services and start every job with the money already held.",
    perks: ["Get booked by nearby customers", "Paid to your Stellar wallet", "Ratings from paying customers"],
  },
];

function CustomerPreview() {
  return (
    <div className="w-full rounded-xl bg-paper p-3 text-xs shadow-lift">
      <div className="flex items-center gap-2">
        <span className="grid size-8 place-items-center rounded-full bg-stellar-soft text-[11px] font-bold text-stellar-ink">TB</span>
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-1 font-semibold text-ink">
            Tunde B. <BadgeCheck className="size-3 text-lagoon" aria-hidden />
          </span>
          <span className="flex items-center gap-0.5 text-ink-3">
            <Star className="size-3 fill-danfo text-danfo" aria-hidden /> 4.8 · AC technician
          </span>
        </span>
      </div>
      <div className="mt-2 flex items-center justify-between border-t border-line pt-2">
        <span className="text-ink-3">From</span>
        <span className="tnum font-semibold text-ink">₦15,000</span>
      </div>
    </div>
  );
}

function ProPreview() {
  return (
    <div className="w-full overflow-hidden rounded-xl bg-paper text-xs shadow-lift">
      <div className="flex items-start gap-2 p-3">
        <span className="grid size-6 shrink-0 place-items-center rounded-md bg-stellar text-white">
          <Bell className="size-3" aria-hidden />
        </span>
        <span>
          <span className="block font-semibold text-ink">Payment secured</span>
          <span className="block text-ink-3">You can start the job.</span>
        </span>
      </div>
      <div className="hazard h-1.5 animate-stripe" />
      <div className="flex items-center gap-1.5 bg-danfo px-3 py-1.5 font-semibold text-ink">
        <Lock className="size-3" aria-hidden /> 30.65 USDC held
      </div>
    </div>
  );
}

const PREVIEW: Record<Role, () => React.ReactElement> = { customer: CustomerPreview, professional: ProPreview };

function RolePicker({ onPick }: { onPick: (r: Role) => void }) {
  return (
    <div>
      <p className="text-sm font-semibold text-stellar">Step 1</p>
      <h1 className="font-semiwide mt-1 text-3xl font-bold sm:text-4xl">How will you use UniFix?</h1>
      <p className="mt-2 max-w-lg text-ink-3">
        Pick one to continue. Already have an account?{" "}
        <Link href="/sign-in" className="font-semibold text-stellar hover:underline">
          Sign in
        </Link>
      </p>
      <ul className="mt-8 grid gap-4 sm:grid-cols-2">
        {ROLES.map(({ v, Icon, t, d, perks }, i) => {
          const Preview = PREVIEW[v];
          return (
            <li key={v} className="animate-rise" style={{ animationDelay: `${0.08 + i * 0.1}s` }}>
              <button
                type="button"
                onClick={() => onPick(v)}
                className="group relative flex h-full w-full flex-col overflow-hidden rounded-2xl border-2 border-line bg-paper text-left transition duration-300 hover:-translate-y-1 hover:border-stellar hover:shadow-ticket focus-visible:border-stellar"
              >
                <span
                  className={cn(
                    "flex h-44 items-center justify-center p-6",
                    v === "customer" ? "bg-stellar-soft" : "bg-ink",
                  )}
                  aria-hidden
                >
                  <span className="block w-full max-w-60 transition-transform duration-300 group-hover:-rotate-2 group-hover:scale-105">
                    <Preview />
                  </span>
                </span>
                <span className="flex min-w-0 flex-1 flex-col p-6">
                  <span className="flex items-center gap-2">
                    <Icon className="size-5 text-stellar" aria-hidden />
                    <span className="text-lg font-semibold">{t}</span>
                  </span>
                  <span className="mt-1 block text-sm leading-relaxed text-ink-2">{d}</span>
                  <span className="mt-3 flex flex-col gap-1">
                    {perks.map((p) => (
                      <span key={p} className="flex items-center gap-1.5 text-sm text-ink-3">
                        <Check className="size-3.5 shrink-0 text-lagoon" aria-hidden />
                        {p}
                      </span>
                    ))}
                  </span>
                  <span className="mt-4 flex items-center gap-1.5 text-sm font-semibold text-stellar">
                    Continue
                    <ArrowRight className="size-4 transition-transform duration-300 group-hover:translate-x-1" aria-hidden />
                  </span>
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function StepHeader({ role, step, onBack }: { role: Role; step: Step; onBack: () => void }) {
  const total = role === "professional" ? 3 : 2;
  const n = step === "account" ? 2 : 3;
  const r = ROLES.find((x) => x.v === role)!;
  return (
    <div className="mb-8">
      <div className="flex items-center justify-between gap-4">
        <button type="button" onClick={onBack} className="flex items-center gap-1.5 text-sm font-semibold text-ink-3 hover:text-ink">
          <ArrowLeft className="size-4" aria-hidden />
          Back
        </button>
        <span className="tnum text-sm text-ink-3">
          Step {n} of {total}
        </span>
      </div>
      <div className="mt-3 flex gap-1.5" aria-hidden>
        {Array.from({ length: total }, (_, i) => (
          <span key={i} className="h-1 flex-1 overflow-hidden rounded-full bg-line">
            <motion.span
              className="block h-full origin-left rounded-full bg-stellar"
              initial={false}
              animate={{ scaleX: i < n ? 1 : 0 }}
              transition={{ duration: 0.5, ease: EASE }}
            />
          </span>
        ))}
      </div>
      <span className="mt-6 inline-flex items-center gap-2 rounded-full bg-stellar-soft px-3 py-1 text-sm font-semibold text-stellar-ink">
        <r.Icon className="size-4" aria-hidden />
        {r.t}
      </span>
    </div>
  );
}

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
  const preset = params.get("role");
  const [role, setRole] = useState<Role>(preset === "professional" ? "professional" : "customer");
  const [step, setStep] = useState<Step>(preset === "professional" || preset === "customer" ? "account" : "role");
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

  const back = () => setStep(step === "profile" ? "account" : "role");

  return (
    <MotionConfig reducedMotion="user">
      <AnimatePresence mode="wait" initial={false}>
        <motion.div
          key={step}
          initial={{ opacity: 0, x: 24 }}
          animate={{ opacity: 1, x: 0 }}
          exit={{ opacity: 0, x: -24 }}
          transition={{ duration: 0.35, ease: EASE }}
        >
          {step === "role" ? (
            <RolePicker
              onPick={(r) => {
                setRole(r);
                setStep("account");
              }}
            />
          ) : step === "account" ? (
            <div className="mx-auto max-w-lg">
              <StepHeader role={role} step={step} onBack={back} />
              <h1 className="font-semiwide text-3xl font-bold">Create your account</h1>
              <p className="mb-8 mt-2 text-ink-3">
                Already on UniFix?{" "}
                <Link href="/sign-in" className="font-semibold text-stellar hover:underline">
                  Sign in
                </Link>
              </p>
              <form
                className="flex flex-col gap-5"
                onSubmit={(e) => {
                  e.preventDefault();
                  if (role === "professional") setStep("profile");
                  else submit();
                }}
              >
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
            </div>
          ) : (
            <div className="mx-auto max-w-lg">
              <StepHeader role={role} step={step} onBack={back} />
              <h1 className="font-semiwide text-3xl font-bold">Your professional profile</h1>
              <p className="mt-2 text-ink-3">Customers see this when they compare professionals. Verification documents stay private.</p>
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
                <Button type="submit" size="lg" loading={busy}>
                  Create professional account
                </Button>
              </form>
            </div>
          )}
        </motion.div>
      </AnimatePresence>
    </MotionConfig>
  );
}

export default function SignUpPage() {
  return (
    <Suspense>
      <SignUpForm />
    </Suspense>
  );
}
