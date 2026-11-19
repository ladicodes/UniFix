"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { AnimatePresence, MotionConfig, motion } from "motion/react";
import {
  ArrowLeft,
  ArrowRight,
  BadgeCheck,
  Bell,
  Car,
  Check,
  Droplets,
  Fuel,
  Hammer,
  House,
  KeyRound,
  Lock,
  Mail,
  MapPin,
  PaintRoller,
  ShieldCheck,
  Snowflake,
  Sparkles,
  Star,
  UserRound,
  Zap,
} from "lucide-react";
import { api } from "@/lib/api";
import type { SignUpInput } from "@/lib/api";
import { CATEGORIES, cn } from "@/lib/format";
import type { CategoryId, Professional } from "@/lib/types";
import { useSession } from "@/components/providers";
import { Button, ChipInput, ErrorNote, Field, Input, Segmented, Textarea } from "@/components/ui";

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

const TRADE_ICON: Record<CategoryId, typeof Zap> = {
  electrician: Zap,
  plumber: Droplets,
  "ac-technician": Snowflake,
  mechanic: Car,
  generator: Fuel,
  carpenter: Hammer,
  cleaner: Sparkles,
  painter: PaintRoller,
};

function passwordStrength(pw: string) {
  if (!pw) return { score: 0, label: "Use at least 8 characters.", bar: "bg-line" };
  let score = 0;
  if (pw.length >= 8) score++;
  if (pw.length >= 12) score++;
  if (/[a-z]/.test(pw) && /[A-Z]/.test(pw)) score++;
  if (/\d/.test(pw) && /[^A-Za-z0-9]/.test(pw)) score++;
  if (pw.length < 8) return { score: 1, label: `${8 - pw.length} more characters needed.`, bar: "bg-clay" };
  const labels = ["Weak", "Weak", "Fair", "Good", "Strong"];
  const bars = ["bg-clay", "bg-clay", "bg-danfo", "bg-lagoon", "bg-lagoon"];
  return { score, label: `${labels[score]} password.`, bar: bars[score] };
}

function FormSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <fieldset className="flex flex-col gap-5 border-t border-line pt-6">
      <legend className="float-left mb-1 w-full text-base font-semibold">{title}</legend>
      {children}
    </fieldset>
  );
}

function CustomerPreview() {
  return (
    <div className="w-full rounded-xl bg-paper p-3 text-xs shadow-lift">
      <div className="flex items-center gap-2">
        <span className="grid size-8 place-items-center rounded-full bg-stellar-soft text-xs font-bold text-stellar-ink">TB</span>
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
    coverage: [] as string[],
    yearsExperience: 3,
    startingPrice: 10000,
    availability: "today" as Professional["availability"],
    skills: [] as string[],
  });
  const [showPw, setShowPw] = useState(false);
  const strength = passwordStrength(acct.password);

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
          ? pro
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
                <Field label="Full name">
                  {(id) => <Input id={id} icon={UserRound} required autoComplete="name" placeholder="Adaeze Okafor" value={acct.name} onChange={(e) => setAcct({ ...acct, name: e.target.value })} />}
                </Field>
                <Field label="Email">
                  {(id) => <Input id={id} icon={Mail} type="email" required autoComplete="email" placeholder="you@example.com" value={acct.email} onChange={(e) => setAcct({ ...acct, email: e.target.value })} />}
                </Field>
                <Field label="Password">
                  {(id) => (
                    <div>
                      <Input
                        id={id}
                        icon={KeyRound}
                        type={showPw ? "text" : "password"}
                        required
                        minLength={8}
                        autoComplete="new-password"
                        aria-describedby={`${id}-strength`}
                        value={acct.password}
                        onChange={(e) => setAcct({ ...acct, password: e.target.value })}
                        trailing={
                          <button type="button" onClick={() => setShowPw((x) => !x)} className="rounded-lg px-2 py-1 text-sm font-semibold text-ink-3 hover:bg-plaster hover:text-ink">
                            {showPw ? "Hide" : "Show"}
                          </button>
                        }
                      />
                      <div className="mt-2.5 flex gap-1.5" aria-hidden>
                        {[0, 1, 2, 3].map((i) => (
                          <span key={i} className={cn("h-1 flex-1 rounded-full transition-colors", i < strength.score ? strength.bar : "bg-line")} />
                        ))}
                      </div>
                      <p id={`${id}-strength`} className="mt-1.5 text-sm text-ink-3">
                        {strength.label}
                      </p>
                    </div>
                  )}
                </Field>
                <div className="flex flex-col gap-2">
                  <span className="text-sm font-semibold">City</span>
                  <Segmented
                    label="City"
                    value={acct.city}
                    onChange={(city) => setAcct({ ...acct, city })}
                    options={CITIES.map((c) => ({ value: c.city, label: c.city, hint: c.country === "NG" ? "Nigeria" : "Ghana" }))}
                    className="grid-cols-2! sm:grid-cols-4!"
                  />
                </div>
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
                className="mt-8 flex flex-col gap-8"
                onSubmit={(e) => {
                  e.preventDefault();
                  submit();
                }}
              >
                <FormSection title="What you do">
                  <div role="radiogroup" aria-label="Service" className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                    {CATEGORIES.map((c) => {
                      const on = pro.category === c.id;
                      const Icon = TRADE_ICON[c.id];
                      return (
                        <button
                          key={c.id}
                          type="button"
                          role="radio"
                          aria-checked={on}
                          onClick={() => setPro({ ...pro, category: c.id })}
                          className={cn(
                            "flex flex-col items-start gap-2 rounded-xl border p-3 text-left text-sm font-semibold transition",
                            on ? "border-stellar bg-stellar-soft text-stellar-ink ring-1 ring-stellar" : "border-line text-ink-2 hover:border-line-2 hover:text-ink",
                          )}
                        >
                          <Icon className="size-5" aria-hidden />
                          {c.label}
                        </button>
                      );
                    })}
                  </div>
                  <Field label="Headline" hint="One line about what you do best.">
                    {(id, d) => <Input id={id} aria-describedby={d} required maxLength={90} placeholder="House wiring, inverter and solar backup" value={pro.headline} onChange={(e) => setPro({ ...pro, headline: e.target.value })} />}
                  </Field>
                  <Field label="About your work" hint={`${pro.bio.length}/600`}>
                    {(id, d) => <Textarea id={id} aria-describedby={d} required maxLength={600} placeholder="What kind of jobs you take, how you work, what customers can expect." value={pro.bio} onChange={(e) => setPro({ ...pro, bio: e.target.value })} />}
                  </Field>
                  <Field label="Skills" hint="Press Enter after each one.">
                    {(id, d) => <ChipInput id={id} describedBy={d} value={pro.skills} onChange={(skills) => setPro({ ...pro, skills })} placeholder="Rewiring, fault tracing" />}
                  </Field>
                </FormSection>

                <FormSection title="Where you work">
                  <Field label="Base area">
                    {(id) => <Input id={id} icon={MapPin} required placeholder="Yaba" value={pro.area} onChange={(e) => setPro({ ...pro, area: e.target.value })} />}
                  </Field>
                  <Field label="Areas you cover" hint="Press Enter after each one." optional>
                    {(id, d) => <ChipInput id={id} describedBy={d} value={pro.coverage} onChange={(coverage) => setPro({ ...pro, coverage })} placeholder="Yaba, Surulere, Ikoyi" />}
                  </Field>
                  <div className="flex flex-col gap-2">
                    <span className="text-sm font-semibold">Availability</span>
                    <Segmented
                      label="Availability"
                      value={pro.availability === "unavailable" ? "today" : pro.availability}
                      onChange={(availability) => setPro({ ...pro, availability })}
                      options={[
                        { value: "now", label: "Now" },
                        { value: "today", label: "Today" },
                        { value: "this-week", label: "This week" },
                      ]}
                    />
                  </div>
                </FormSection>

                <FormSection title="Experience and pricing">
                  <div className="grid gap-4 sm:grid-cols-2">
                    <Field label="Years of experience">
                      {(id) => <Input id={id} type="number" min={0} max={60} value={pro.yearsExperience} onChange={(e) => setPro({ ...pro, yearsExperience: Number(e.target.value) })} />}
                    </Field>
                    <Field label="Starting price" hint="Customers see it as From …">
                      {(id, d) => (
                        <Input
                          id={id}
                          aria-describedby={d}
                          type="number"
                          min={0}
                          step={500}
                          value={pro.startingPrice}
                          onChange={(e) => setPro({ ...pro, startingPrice: Number(e.target.value) })}
                          trailing={<span className="px-2 text-sm font-semibold text-ink-3">{country === "NG" ? "NGN" : "GHS"}</span>}
                        />
                      )}
                    </Field>
                  </div>
                </FormSection>

                <p className="flex gap-3 rounded-xl bg-plaster px-4 py-3 text-sm text-ink-2">
                  <ShieldCheck className="mt-0.5 size-4 shrink-0 text-lagoon" aria-hidden />
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
