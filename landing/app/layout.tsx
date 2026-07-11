import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono, Instrument_Serif } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

// The paper world's court-record voice. Not a variable font — 400 only.
const instrumentSerif = Instrument_Serif({
  variable: "--font-instrument-serif",
  weight: "400",
  style: ["normal", "italic"],
  subsets: ["latin"],
});

const description =
  "Proofloop is the correctness gate for AI-written code. Deterministic checks decide at the deploy moment, an LLM explains why, every verdict ships with a reproducible proof record — and every catch is remembered.";

export const metadata: Metadata = {
  title: "Proofloop — The last command before production",
  description,
  openGraph: {
    title: "Proofloop — The last command before production",
    description,
    siteName: "Proofloop",
    type: "website",
  },
  twitter: {
    card: "summary",
    title: "Proofloop — The last command before production",
    description,
  },
};

export const viewport: Viewport = {
  themeColor: "#0a0e14",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      data-world="night"
      className={`${geistSans.variable} ${geistMono.variable} ${instrumentSerif.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col bg-surface text-body">
        {children}
      </body>
    </html>
  );
}
