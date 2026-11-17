import type { Metadata } from "next";
import Script from "next/script";
import "./globals.css";
import { AppShell } from "@/components/shell/AppShell";

export const metadata: Metadata = { title: "OpenTalos" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body className="flex h-screen overflow-hidden">
        <Script
          id="opentalos-client-errors"
          strategy="beforeInteractive"
          dangerouslySetInnerHTML={{
            __html: `
              window.__opentalosClientErrors = [];
              window.addEventListener("error", function (event) {
                window.__opentalosClientErrors.push({
                  type: "error",
                  message: event.message,
                  filename: event.filename,
                  lineno: event.lineno,
                  colno: event.colno,
                  stack: event.error && event.error.stack
                });
              }, true);
              window.addEventListener("unhandledrejection", function (event) {
                window.__opentalosClientErrors.push({
                  type: "rejection",
                  reason: String(event.reason),
                  stack: event.reason && event.reason.stack
                });
              });
            `,
          }}
        />
        {/* 首屏前根据 localStorage/系统偏好预置 .dark，避免主题闪烁（FOUC）。 */}
        <script
          dangerouslySetInnerHTML={{
            __html: `try{var t=localStorage.getItem("opentalos.theme");if(t==="dark"||(!t&&window.matchMedia("(prefers-color-scheme: dark)").matches))document.documentElement.classList.add("dark")}catch(e){}`,
          }}
        />
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
