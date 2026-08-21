import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Nexa — Wealify statement review (WLF-01)",
  description:
    "Read-only review of statements, receipts, wallet balance and card activity. "
    + "Suggestions only — you decide.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="vi" data-theme="dark" suppressHydrationWarning>
      <body>{children}</body>
    </html>
  );
}
