import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import { TickerProvider } from "@/hooks/useTicker";

const inter = Inter({ subsets: ["latin"], variable: "--font-sans", display: "swap" });
const jetbrainsMono = JetBrains_Mono({ subsets: ["latin"], variable: "--font-mono", display: "swap" });

export const metadata: Metadata = {
  title: "FLAB MASA System",
  description: "FLAB MASA — multi-agent trading analysis system",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body className={`${inter.variable} ${jetbrainsMono.variable} h-screen overflow-hidden bg-[#0a0d13] text-[#f7f8f8] antialiased`}>
        <TickerProvider>{children}</TickerProvider>
      </body>
    </html>
  );
}
