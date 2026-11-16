"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Search } from "lucide-react";
import { CATEGORIES } from "@/lib/format";

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
      className="flex w-full max-w-xl flex-col gap-2 sm:flex-row sm:items-center"
    >
      <label className="sr-only" htmlFor="hero-cat">Service</label>
      <select
        id="hero-cat"
        value={category}
        onChange={(e) => setCategory(e.target.value)}
        className="h-12 flex-1 rounded-lg bg-plaster px-3 text-base font-semibold text-ink"
      >
        {CATEGORIES.map((c) => (
          <option key={c.id} value={c.id}>
            {c.label}
          </option>
        ))}
      </select>
      <label className="sr-only" htmlFor="hero-city">City</label>
      <select
        id="hero-city"
        value={city}
        onChange={(e) => setCity(e.target.value)}
        className="h-12 rounded-lg bg-plaster px-3 text-base font-semibold text-ink sm:w-36"
      >
        {["Lagos", "Abuja", "Accra", "Kumasi"].map((c) => (
          <option key={c}>{c}</option>
        ))}
      </select>
      <button type="submit" className="inline-flex h-12 items-center justify-center gap-2 rounded-lg bg-stellar px-5 font-semibold text-white hover:bg-stellar-ink">
        <Search className="size-4" aria-hidden />
        Find professionals
      </button>
    </form>
  );
}
