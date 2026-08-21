import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Nexa — Wealify statement review (WLF-01)",
  description:
    "Read-only review of statements, receipts, wallet balance and card activity. "
    + "Suggestions only — you decide.",
};

// Runs before first paint. An explicit choice wins; with no choice stored the
// attribute stays absent and the prefers-color-scheme rules in globals.css
// decide. Without this the page paints the light palette, then repaints dark.
const THEME_BOOTSTRAP = `(function(){try{
  var choice = localStorage.getItem("nexa-theme");
  if (choice === "light" || choice === "dark") {
    document.documentElement.setAttribute("data-theme", choice);
  }
}catch(e){}})();`;

/** React warns in development about rendering a <script>, because one inserted
 *  through a DOM update never executes. This one is only ever meant to run
 *  while the browser parses the server's HTML, so it is inert markup on the
 *  client — which is what the type swap says out loud. */
function InlineScript({ html }: { html: string }) {
  return (
    <script
      type={typeof window === "undefined" ? "text/javascript" : "text/plain"}
      suppressHydrationWarning
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="vi" suppressHydrationWarning>
      <head>
        <InlineScript html={THEME_BOOTSTRAP} />
      </head>
      <body>{children}</body>
    </html>
  );
}
