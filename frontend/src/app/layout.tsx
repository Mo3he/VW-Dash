import type { Metadata } from "next";
import "./globals.css";
import Nav from "@/components/Nav";

export const metadata: Metadata = {
  title: "VW Dash",
  description: "ID.4 monitoring dashboard",
  viewport: "width=device-width, initial-scale=1, maximum-scale=1",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-[#0f1117]">
        <Nav />
        <main className="max-w-4xl mx-auto px-4 pb-24 pt-4">{children}</main>
      </body>
    </html>
  );
}
