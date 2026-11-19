"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { Search, SlidersHorizontal } from "lucide-react";
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

  return (
    <div>
      <h1 className="font-semiwide text-3xl font-bold">
        {catLabel} {f.city && f.city !== "all" ? `in ${f.city}` : "in Nigeria and Ghana"}
      </h1>

      {/* Search and categories stay under the app header while the list scrolls */}
      <div className="sticky top-16 z-30 -mx-4 mt-4 border-b border-line bg-plaster/95 px-4 pb-4 pt-3 backdrop-blur sm:-mx-6 sm:px-6 lg:-mx-10 lg:px-10">
      <div className="flex gap-2">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-ink-3" aria-hidden />
          <Input
            aria-label="Search professionals"
            placeholder="Search by name, skill or area, like inverter or Lekki"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            className="h-12 rounded-full pl-10"
          />
        </div>
        <Button variant="outline" className="h-12 lg:hidden" onClick={() => setSheet(true)} aria-label="Filters">
          <SlidersHorizontal className="size-4" aria-hidden />
          <span className="hidden sm:inline">Filters</span>
          {activeCount > 0 && <span className="grid size-5 place-items-center rounded-full bg-stellar text-xs text-white">{activeCount}</span>}
        </Button>
      </div>

      <div className="-mx-4 mt-3 flex gap-2 overflow-x-auto px-4 sm:mx-0 sm:flex-wrap sm:px-0" role="group" aria-label="Service category">
        {[{ id: "all", plural: "All services" }, ...CATEGORIES].map((c) => (
          <button
            key={c.id}
            aria-pressed={f.category === c.id}
            onClick={() => set({ category: c.id as CategoryId | "all" })}
            className={cn(
              "shrink-0 rounded-full border px-4 py-2 text-sm font-semibold transition-colors",
              f.category === c.id ? "border-stellar bg-stellar text-white" : "border-line bg-paper text-ink-2 hover:border-ink-4",
            )}
          >
            {c.plural}
          </button>
        ))}
      </div>
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-[18rem_minmax(0,1fr)]">
        <aside className="hidden rounded-2xl border border-line bg-paper p-5 shadow-xs lg:sticky lg:top-52 lg:block lg:max-h-[calc(100dvh-14rem)] lg:self-start lg:overflow-y-auto" aria-label="Filters">
          <Filters f={f} set={set} />
        </aside>

        <div>
          <div className="mb-3 flex items-center justify-between gap-4">
            <p className="text-sm text-ink-3" aria-live="polite">
              {isLoading ? "Searching…" : `${data?.length ?? 0} result${data?.length === 1 ? "" : "s"}`}
              {isFetching && !isLoading && " (updating)"}
            </p>
            <label className="flex items-center gap-2 text-sm">
              <span className="text-ink-3">Sort</span>
              <Select value={f.sort} onChange={(e) => set({ sort: e.target.value as ProfessionalFilters["sort"] })} className="h-9 w-auto py-0 text-sm">
                <option value="best">Best rated</option>
                <option value="most-jobs">Most jobs done</option>
                <option value="experience">Most experience</option>
              </Select>
            </label>
          </div>

          {isLoading ? (
            <div className="grid gap-4 sm:grid-cols-2 2xl:grid-cols-3">
              {[0, 1, 2, 3, 4, 5].map((i) => (
                <Skeleton key={i} className="h-60 rounded-2xl" />
              ))}
            </div>
          ) : data?.length ? (
            <div className={cn("grid gap-4 transition-opacity sm:grid-cols-2 2xl:grid-cols-3", isFetching && "opacity-70")}>
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
        </div>
      </div>

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
