"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { BadgeCheck, LayoutGrid, Search, SlidersHorizontal, Star } from "lucide-react";
import { TRADE_ICON } from "@/components/trade-icon";
import { CATEGORIES, cn } from "@/lib/format";
import { useProfessionals } from "@/lib/hooks";
import type { CategoryId, ProfessionalFilters } from "@/lib/types";
import { ProCard } from "@/components/pro-row";
import { Button, Dialog, Empty, Input, Select, Skeleton } from "@/components/ui";

const CITIES = ["all", "Lagos", "Abuja", "Accra", "Kumasi"];

function Filters({ f, set }: { f: ProfessionalFilters; set: (p: Partial<ProfessionalFilters>) => void }) {
  return (
    <div className="flex flex-col gap-6">
      <div>
        <label htmlFor="f-city" className="text-sm font-semibold">
          City
        </label>
        <Select id="f-city" className="mt-2" value={f.city ?? "all"} onChange={(e) => set({ city: e.target.value })}>
          {CITIES.map((c) => (
            <option key={c} value={c}>
              {c === "all" ? "All cities" : c}
            </option>
          ))}
        </Select>
      </div>
      <fieldset>
        <legend className="text-sm font-semibold">Availability</legend>
        <div className="mt-2 grid grid-cols-3 rounded-lg bg-plaster-2 p-1 text-sm font-semibold">
          {(
            [
              ["any", "Any"],
              ["today", "Today"],
              ["now", "Now"],
            ] as const
          ).map(([v, l]) => (
            <button
              key={v}
              type="button"
              aria-pressed={(f.availability ?? "any") === v}
              onClick={() => set({ availability: v })}
              className={cn("rounded-lg py-2 transition-colors", (f.availability ?? "any") === v ? "bg-paper shadow-sm" : "text-ink-3 hover:text-ink")}
            >
              {l}
            </button>
          ))}
        </div>
      </fieldset>
      <fieldset>
        <legend className="text-sm font-semibold">Minimum rating</legend>
        <div className="mt-2 flex flex-wrap gap-2">
          {[0, 4, 4.5, 4.8].map((r) => (
            <button
              key={r}
              type="button"
              aria-pressed={(f.minRating ?? 0) === r}
              onClick={() => set({ minRating: r })}
              className={cn(
                "tnum rounded-lg border px-3 py-2 text-sm font-semibold transition-colors",
                (f.minRating ?? 0) === r ? "border-stellar bg-stellar text-white" : "border-line bg-paper hover:border-ink-4",
              )}
            >
              {r === 0 ? "Any" : `${r}+`}
            </button>
          ))}
        </div>
      </fieldset>
      <label className="flex cursor-pointer items-start gap-3">
        <input
          type="checkbox"
          checked={!!f.verifiedOnly}
          onChange={(e) => set({ verifiedOnly: e.target.checked })}
          className="mt-0.5 size-5 shrink-0 accent-ink"
        />
        <span>
          <span className="block text-sm font-semibold">ID and trade verified only</span>
          <span className="block text-sm text-ink-3">UniFix checked their ID and a trade certificate.</span>
        </span>
      </label>
    </div>
  );
}

function Discover() {
  const params = useSearchParams();
  const router = useRouter();
  const [f, setF] = useState<ProfessionalFilters>({
    category: (params.get("category") as CategoryId) ?? "all",
    city: params.get("city") ?? "all",
    q: params.get("q") ?? "",
    availability: "any",
    minRating: 0,
    sort: "best",
  });
  const [q, setQ] = useState(f.q ?? "");
  const [sheet, setSheet] = useState(false);
  const set = (p: Partial<ProfessionalFilters>) => setF((x) => ({ ...x, ...p }));

  useEffect(() => {
    const t = setTimeout(() => set({ q }), 250);
    return () => clearTimeout(t);
  }, [q]);

  useEffect(() => {
    const sp = new URLSearchParams();
    if (f.category && f.category !== "all") sp.set("category", f.category);
    if (f.city && f.city !== "all") sp.set("city", f.city);
    if (f.q) sp.set("q", f.q);
    router.replace(`/discover${sp.size ? `?${sp}` : ""}`, { scroll: false });
  }, [f.category, f.city, f.q, router]);

  const { data, isLoading, isFetching } = useProfessionals(f);
  const catLabel = f.category && f.category !== "all" ? CATEGORIES.find((c) => c.id === f.category)?.plural : "Professionals";
  const activeCount = [f.city !== "all", f.availability !== "any", (f.minRating ?? 0) > 0, f.verifiedOnly].filter(Boolean).length;

  const chip = (on: boolean) =>
    cn(
      "inline-flex h-10 items-center gap-2 rounded-full border px-4 text-sm font-semibold transition-colors",
      on ? "border-ink bg-ink text-white" : "border-line bg-paper text-ink-2 hover:border-line-2 hover:text-ink",
    );

  return (
    <div className="space-y-6">
      <section className="rounded-2xl border border-line bg-paper p-6 shadow-xs lg:p-8">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="font-semiwide text-3xl font-bold sm:text-4xl">
              {catLabel} {f.city && f.city !== "all" ? `in ${f.city}` : "near you"}
            </h1>
            <p className="mt-2 text-ink-2">Verified professionals with ratings from paying customers. You only pay into escrow when you accept a quotation.</p>
          </div>
        </div>

        <div className="relative mt-6">
          <Search className="pointer-events-none absolute left-5 top-1/2 size-5 -translate-y-1/2 text-ink-3" aria-hidden />
          <Input
            aria-label="Search professionals"
            placeholder="Search by name, skill or area, like inverter or Lekki"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            className="h-14 rounded-2xl pl-13 text-lg"
          />
        </div>

        <div className="-mx-6 mt-6 overflow-x-auto px-6 lg:-mx-8 lg:px-8">
          <div className="flex gap-3" role="group" aria-label="Service category">
            {[{ id: "all" as const, plural: "All services" }, ...CATEGORIES].map((c) => {
              const on = f.category === c.id;
              const Icon = c.id === "all" ? LayoutGrid : TRADE_ICON[c.id];
              return (
                <button
                  key={c.id}
                  aria-pressed={on}
                  onClick={() => set({ category: c.id as CategoryId | "all" })}
                  className={cn(
                    "flex w-28 shrink-0 flex-col items-center gap-2 rounded-2xl border px-3 py-4 text-center text-sm font-semibold transition",
                    on ? "border-stellar bg-stellar-soft text-stellar-ink ring-1 ring-stellar" : "border-line bg-paper text-ink-2 hover:border-line-2 hover:text-ink",
                  )}
                >
                  <span className={cn("grid size-11 place-items-center rounded-xl", on ? "bg-stellar text-white" : "bg-plaster text-ink-2")}>
                    <Icon className="size-5" aria-hidden />
                  </span>
                  <span className="leading-tight">{c.plural}</span>
                </button>
              );
            })}
          </div>
        </div>
      </section>

      <div className="flex flex-wrap items-center gap-2">
        <div className="hidden flex-wrap items-center gap-2 lg:flex">
          <label className="sr-only" htmlFor="f-city">
            City
          </label>
          <div className="w-44">
            <Select id="f-city" value={f.city ?? "all"} onChange={(e) => set({ city: e.target.value })} className="h-10 rounded-full text-sm font-semibold">
              {CITIES.map((c) => (
                <option key={c} value={c}>
                  {c === "all" ? "All cities" : c}
                </option>
              ))}
            </Select>
          </div>
          {(
            [
              ["any", "Any time"],
              ["today", "Today"],
              ["now", "Available now"],
            ] as const
          ).map(([v, l]) => (
            <button key={v} type="button" aria-pressed={(f.availability ?? "any") === v} onClick={() => set({ availability: v })} className={chip((f.availability ?? "any") === v)}>
              {l}
            </button>
          ))}
          <span className="mx-1 h-6 w-px bg-line" aria-hidden />
          {[4, 4.5, 4.8].map((r) => (
            <button key={r} type="button" aria-pressed={f.minRating === r} onClick={() => set({ minRating: f.minRating === r ? 0 : r })} className={chip(f.minRating === r)}>
              <Star className="size-4" aria-hidden />
              {r}+
            </button>
          ))}
          <button type="button" aria-pressed={!!f.verifiedOnly} onClick={() => set({ verifiedOnly: !f.verifiedOnly })} className={chip(!!f.verifiedOnly)}>
            <BadgeCheck className="size-4" aria-hidden />
            Verified only
          </button>
        </div>
        <Button variant="outline" className="h-10 rounded-full lg:hidden" onClick={() => setSheet(true)} aria-label="Filters">
          <SlidersHorizontal className="size-4" aria-hidden />
          Filters
          {activeCount > 0 && <span className="grid size-5 place-items-center rounded-full bg-stellar text-xs text-white">{activeCount}</span>}
        </Button>

        <div className="ml-auto flex items-center gap-3">
          <p className="text-sm text-ink-3" aria-live="polite">
            {isLoading ? "Searching…" : `${data?.length ?? 0} result${data?.length === 1 ? "" : "s"}`}
            {isFetching && !isLoading && " (updating)"}
          </p>
          <label className="sr-only" htmlFor="f-sort">
            Sort
          </label>
          <div className="w-44">
            <Select id="f-sort" value={f.sort} onChange={(e) => set({ sort: e.target.value as ProfessionalFilters["sort"] })} className="h-10 rounded-full text-sm font-semibold">
              <option value="best">Best rated</option>
              <option value="most-jobs">Most jobs done</option>
              <option value="experience">Most experience</option>
            </Select>
          </div>
        </div>
      </div>

      {isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
          {[0, 1, 2, 3, 4, 5, 6, 7].map((i) => (
            <Skeleton key={i} className="h-60 rounded-2xl" />
          ))}
        </div>
      ) : data?.length ? (
        <div className={cn("grid gap-4 transition-opacity sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4", isFetching && "opacity-70")}>
          {data.map((p) => (
            <ProCard key={p.id} p={p} />
          ))}
        </div>
      ) : (
        <Empty
          title="No professionals match"
          body="Try another city, lower the minimum rating, or include unverified professionals."
          action={
            <Button variant="outline" onClick={() => setF({ category: "all", city: "all", availability: "any", minRating: 0, sort: "best", q: "" })}>
              Clear all filters
            </Button>
          }
        />
      )}

      <Dialog open={sheet} onClose={() => setSheet(false)} title="Filters">
        <Filters f={f} set={set} />
        <Button className="mt-6 w-full" onClick={() => setSheet(false)}>
          Show {data?.length ?? 0} results
        </Button>
      </Dialog>
    </div>
  );
}

export default function DiscoverPage() {
  return (
    <Suspense>
      <Discover />
    </Suspense>
  );
}
