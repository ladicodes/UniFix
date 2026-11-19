import Link from "next/link";
import { AuthAside } from "@/components/auth-aside";
import { Logo } from "@/components/ui";

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid min-h-dvh bg-paper lg:grid-cols-[minmax(0,1fr)_minmax(0,520px)] xl:grid-cols-[minmax(0,1fr)_minmax(0,600px)]">
      <div className="flex flex-col px-4 py-6 sm:px-10">
        <Link href="/" aria-label="UniFix home" className="self-start">
          <Logo />
        </Link>
        <div className="flex flex-1 items-center py-10">
          <div className="mx-auto w-full max-w-2xl">{children}</div>
        </div>
      </div>
      <AuthAside />
    </div>
  );
}
