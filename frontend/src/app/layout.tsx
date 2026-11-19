import type { Metadata, Viewport } from "next";
import { Archivo } from "next/font/google";
import { Providers } from "@/components/providers";
import "./globals.css";

const archivo = Archivo({
  variable: "--font-archivo",
  subsets: ["latin"],
  axes: ["wdth"],
  display: "swap",
});

export const metadata: Metadata = {
  title: { default: "UniFix: hire professionals, pay when the job is done", template: "%s | UniFix" },
  description:
    "Hire electricians, plumbers, AC technicians and mechanics in Nigeria and Ghana. Agree on a quotation, hold the payment in Stellar escrow, and release it when the job is done.",
};

export const viewport: Viewport = {
  themeColor: "white",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${archivo.variable} h-full antialiased`}>
      <body className="min-h-full">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
