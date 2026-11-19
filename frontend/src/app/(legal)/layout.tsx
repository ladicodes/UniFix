import { LandingNav } from "@/components/landing/nav";
import { SiteFooter } from "@/components/site-footer";

export default function LegalLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-dvh bg-plaster">
      <LandingNav />
      <main className="px-4 py-12 sm:px-6 lg:px-10 lg:py-16">{children}</main>
      <SiteFooter />
    </div>
  );
}
