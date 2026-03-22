import type { Metadata } from "next";
import "./globals.css";
import Sidebar from "@/components/layout/Sidebar";
import TopBar from "@/components/layout/TopBar";
import Providers from "@/lib/providers";
import WebSocketInit from "@/lib/WebSocketInit";

export const metadata: Metadata = {
  title: "Small-Cap Trading Platform",
  description: "AI-powered small-cap equity research and paper trading platform",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark">
      <body className="antialiased">
        <Providers>
          <WebSocketInit />
          <Sidebar />
          <TopBar />
          <main
            className="pt-14 min-h-screen"
            style={{ marginLeft: "60px" }}
          >
            <div className="p-6">{children}</div>
          </main>
        </Providers>
      </body>
    </html>
  );
}
