import type { Metadata } from "next";
import "./globals.css";
import { AppShell } from "@/components/shell/AppShell";

export const metadata: Metadata = { title: "OpenTalos" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body className="flex h-screen overflow-hidden">
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
