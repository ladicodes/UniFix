import Link from "next/link";

export interface LegalSection {
  id: string;
  title: string;
  body: React.ReactNode;
}

/** A legal document: title, status note, a sticky contents list and numbered sections. */
export function LegalDoc({ title, updated, intro, sections }: { title: string; updated: string; intro: React.ReactNode; sections: LegalSection[] }) {
  return (
    <div className="grid gap-8 lg:grid-cols-[16rem_minmax(0,1fr)]">
      <aside className="lg:sticky lg:top-24 lg:self-start">
        <nav aria-label="Contents" className="rounded-2xl border border-line bg-paper p-5 shadow-xs">
          <p className="text-sm font-semibold">Contents</p>
          <ol className="mt-3 space-y-2 text-sm">
            {sections.map((s, i) => (
              <li key={s.id}>
                <a href={`#${s.id}`} className="flex gap-2 text-ink-2 hover:text-stellar">
                  <span className="tnum w-5 shrink-0 text-ink-3">{i + 1}.</span>
                  {s.title}
                </a>
              </li>
            ))}
          </ol>
        </nav>
      </aside>
      <article className="min-w-0 rounded-2xl border border-line bg-paper p-6 shadow-xs sm:p-10">
        <p className="text-sm text-ink-3">Last updated {updated}</p>
        <h1 className="font-semiwide mt-2 text-3xl font-bold sm:text-4xl">{title}</h1>
        <div className="mt-6 max-w-prose rounded-xl bg-danfo-soft px-5 py-4 text-sm leading-relaxed text-danfo-ink">
          UniFix is a pilot. Payments run on Stellar testnet with test funds that have no monetary value. This document describes how the
          pilot works today and will be reviewed by counsel before UniFix handles real money.
        </div>
        <div className="mt-8 max-w-prose text-lg leading-relaxed text-ink-2">{intro}</div>
        <ol className="mt-10 max-w-prose space-y-10">
          {sections.map((s, i) => (
            <li key={s.id} id={s.id} className="scroll-mt-24">
              <h2 className="text-xl font-semibold">
                <span className="tnum mr-2 text-ink-3">{i + 1}.</span>
                {s.title}
              </h2>
              <div className="mt-3 space-y-3 leading-relaxed text-ink-2 [&_li]:ml-5 [&_li]:list-disc [&_ul]:space-y-2">{s.body}</div>
            </li>
          ))}
        </ol>
        <p className="mt-12 max-w-prose border-t border-line pt-6 text-sm text-ink-3">
          See also the{" "}
          <Link href={title.startsWith("Terms") ? "/privacy" : "/terms"} className="font-semibold text-stellar hover:underline">
            {title.startsWith("Terms") ? "privacy policy" : "terms and conditions"}
          </Link>
          .
        </p>
      </article>
    </div>
  );
}
