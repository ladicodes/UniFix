import { Suspense } from "react";
import { AppShell } from "@/components/app-shell";

// The shell reads the URL (usePathname/useParams), so it renders inside Suspense
// for Cache Components prerendering.
export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <Suspense fallback={<div className="min-h-dvh bg-paper" />}>
      <AppShell>{children}</AppShell>
    </Suspense>
  );
}
