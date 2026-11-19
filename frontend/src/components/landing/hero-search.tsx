"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Check, ChevronDown, MapPin, Search } from "lucide-react";
import { CATEGORIES, cn } from "@/lib/format";
import type { CategoryId } from "@/lib/types";

const CITIES = [
  { city: "Lagos", country: "Nigeria" },
  { city: "Abuja", country: "Nigeria" },
  { city: "Accra", country: "Ghana" },
  { city: "Kumasi", country: "Ghana" },
];

const POPULAR: CategoryId[] = ["ac-technician", "electrician", "plumber", "generator", "cleaner"];

/** Free-text search with a city picker. A typed trade name searches by category. */
export function HeroSearch() {
  const router = useRouter();
  const [q, setQ] = useState("");
  const [city, setCity] = useState("Lagos");
  const [open, setOpen] = useState(false);
  const pickerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !pickerRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", close);
    };
  }, [open]);

  function go(category?: CategoryId) {
    const text = q.trim().toLowerCase();
    const match = category ?? CATEGORIES.find((c) => [c.label, c.plural, c.id].some((x) => x.toLowerCase() === text))?.id;
    const qs = new URLSearchParams({ city });
    if (match) qs.set("category", match);
    else if (text) qs.set("q", q.trim());
    router.push(`/discover?${qs}`);
  }

  return (
    <div className="w-full max-w-xl">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          go();
        }}
        className="flex flex-col rounded-2xl border border-line bg-paper shadow-ticket transition focus-within:border-stellar focus-within:ring-4 focus-within:ring-stellar-soft sm:flex-row sm:items-center"
      >
        <label htmlFor="hero-q" className="flex min-w-0 flex-1 items-center gap-3 px-5 py-4">
          <Search className="size-5 shrink-0 text-ink-3" aria-hidden />
          <span className="sr-only">What needs fixing?</span>
          <input
            id="hero-q"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="What needs fixing?"
            autoComplete="off"
            className="w-full min-w-0 bg-transparent text-base text-ink outline-none placeholder:text-ink-3"
          />
        </label>

        <div ref={pickerRef} className="relative border-t border-line sm:border-l sm:border-t-0">
          <button
            type="button"
            aria-haspopup="listbox"
            aria-expanded={open}
            onClick={() => setOpen((o) => !o)}
            className="flex w-full items-center gap-2 px-5 py-4 text-left text-base font-semibold text-ink sm:w-40"
          >
            <MapPin className="size-5 shrink-0 text-stellar" aria-hidden />
            <span className="flex-1">{city}</span>
            <ChevronDown className={cn("size-4 text-ink-3 transition-transform", open && "rotate-180")} aria-hidden />
          </button>
          {open && (
            <ul role="listbox" aria-label="City" className="absolute left-0 right-0 top-full z-20 mt-2 overflow-hidden rounded-xl border border-line bg-paper p-1 shadow-lift sm:left-auto sm:w-56">
              {CITIES.map((c) => (
                <li key={c.city}>
                  <button
                    type="button"
                    role="option"
                    aria-selected={c.city === city}
                    onClick={() => {
                      setCity(c.city);
                      setOpen(false);
                    }}
                    className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left hover:bg-plaster"
                  >
                    <span className="flex-1">
                      <span className="block font-semibold">{c.city}</span>
                      <span className="block text-sm text-ink-3">{c.country}</span>
                    </span>
                    {c.city === city && <Check className="size-4 text-stellar" aria-hidden />}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="p-2">
          <button
            type="submit"
            className="inline-flex h-12 w-full items-center justify-center gap-2 rounded-xl bg-stellar px-6 font-semibold text-white transition-colors hover:bg-stellar-ink sm:w-auto"
          >
            Search
          </button>
        </div>
      </form>

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <span className="text-sm text-ink-3">Popular:</span>
        {POPULAR.map((id) => {
          const c = CATEGORIES.find((x) => x.id === id)!;
          return (
            <button
              key={id}
              type="button"
              onClick={() => go(id)}
              className="rounded-full border border-line bg-paper px-3 py-1.5 text-sm font-semibold text-ink-2 transition-colors hover:border-stellar hover:text-stellar"
            >
              {c.plural}
            </button>
          );
        })}
      </div>
    </div>
  );
}
