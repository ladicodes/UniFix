"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { ChevronDown, MapPin, Search, Wrench } from "lucide-react";
import { CATEGORIES } from "@/lib/format";

function Picker({
  id,
  label,
  icon: Icon,
  value,
  onChange,
  options,
  className,
}: {
  id: string;
  label: string;
  icon: typeof Wrench;
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
  className?: string;
}) {
  return (
    <label htmlFor={id} className={`group relative flex min-w-0 cursor-pointer items-center gap-3 rounded-xl px-4 py-2.5 transition-colors hover:bg-plaster ${className ?? ""}`}>
      <Icon className="size-5 shrink-0 text-stellar" aria-hidden />
      <span className="min-w-0 flex-1">
        <span className="block text-xs font-semibold text-ink-3">{label}</span>
        <select
          id={id}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="w-full cursor-pointer appearance-none truncate bg-transparent pr-6 text-base font-semibold text-ink outline-none"
        >
          {options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </span>
      <ChevronDown className="pointer-events-none absolute right-4 top-1/2 size-4 -translate-y-1/2 text-ink-3" aria-hidden />
    </label>
  );
}

export function HeroSearch() {
  const router = useRouter();
  const [category, setCategory] = useState("ac-technician");
  const [city, setCity] = useState("Lagos");
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        router.push(`/discover?category=${category}&city=${encodeURIComponent(city)}`);
      }}
      className="flex w-full max-w-xl flex-col gap-1 rounded-2xl border border-line bg-paper p-1.5 shadow-ticket sm:flex-row sm:items-center"
    >
      <Picker
        id="hero-cat"
        label="I need a"
        icon={Wrench}
        value={category}
        onChange={setCategory}
        options={CATEGORIES.map((c) => ({ value: c.id, label: c.label }))}
        className="flex-1"
      />
      <span className="hidden h-8 w-px bg-line sm:block" aria-hidden />
      <Picker
        id="hero-city"
        label="In"
        icon={MapPin}
        value={city}
        onChange={setCity}
        options={["Lagos", "Abuja", "Accra", "Kumasi"].map((c) => ({ value: c, label: c }))}
        className="sm:w-40"
      />
      <button
        type="submit"
        className="group inline-flex h-12 items-center justify-center gap-2 rounded-xl bg-stellar px-5 font-semibold text-white transition-colors hover:bg-stellar-ink sm:h-14"
      >
        <Search className="size-4 transition-transform group-hover:scale-110" aria-hidden />
        Search
      </button>
    </form>
  );
}
