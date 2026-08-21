import type { Metadata } from "next";
import "../globals.css";

export const metadata: Metadata = {
  title: "Nexa — Sign in",
  description: "Sign in to Nexa statement review assistant",
};

export default function LoginLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="vi">
      <body>{children}</body>
    </html>
  );
}