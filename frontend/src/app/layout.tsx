import type { Metadata, Viewport } from "next";
import { Bricolage_Grotesque, Instrument_Sans } from "next/font/google";
import { Providers } from "@/components/providers";
import "./globals.css";

/* Display: Bricolage Grotesque, a grotesque with optical sizes, for titles and money.
   Text: Instrument Sans, a quiet sans for everything you read. */
const display = Bricolage_Grotesque({
  variable: "--font-bricolage",
  subsets: ["latin"],
  axes: ["opsz"],
  display: "swap",
});

const text = Instrument_Sans({
  variable: "--font-instrument",
  subsets: ["latin"],
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
    <html lang="en" className={`${display.variable} ${text.variable} h-full antialiased`}>
      <body className="min-h-full">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
