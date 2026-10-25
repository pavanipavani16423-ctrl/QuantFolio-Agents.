import type { Metadata, Viewport } from "next";
import { Inter, Instrument_Serif } from "next/font/google";
import { SiteNav } from "@/components/site-nav";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter", display: "swap" });
const instrument = Instrument_Serif({
  subsets: ["latin"],
  weight: "400",
  style: ["normal", "italic"],
  variable: "--font-instrument",
  display: "swap",
});

export const metadata: Metadata = {
  title: { default: "QuantFolio Agents", template: "%s · QuantFolio Agents" },
  description:
    "An AI investment team: agents read SEC filings, check client rules and pick a portfolio with a normal and a (simulated) quantum computer. You approve every trade.",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: dark)", color: "#141210" },
    { media: "(prefers-color-scheme: light)", color: "#faf9f8" },
  ],
};

// A stored theme choice is applied before paint (no flash); otherwise the OS setting wins.
const themeScript = `try{var t=localStorage.getItem("theme");if(t==="light"||t==="dark"){document.documentElement.dataset.theme=t;document.documentElement.classList.toggle("dark",t==="dark")}else if(matchMedia("(prefers-color-scheme: dark)").matches){document.documentElement.classList.add("dark")}}catch(e){}`;

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${inter.variable} ${instrument.variable}`} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body className="flex min-h-dvh flex-col">
        <SiteNav />
        <main className="flex-1">{children}</main>
        <footer className="border-t">
          <div className="mx-auto flex max-w-6xl flex-col gap-2 px-4 py-8 text-sm text-muted-foreground sm:flex-row sm:items-center sm:justify-between sm:px-6">
            <p>
              <span className="font-semibold text-foreground">QuantFolio Agents</span> · research
              project · paper trading only, not investment advice
            </p>
            <p>Real SEC filings and Yahoo Finance prices · quantum results come from a simulator</p>
          </div>
        </footer>
      </body>
    </html>
  );
}
