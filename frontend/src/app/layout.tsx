import type { Metadata } from "next";
import "./globals.css";
import Sidebar from "@/components/layout/Sidebar";
import TopBar from "@/components/layout/TopBar";

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
        <Sidebar />
        <TopBar />
        <main
          className="pt-14 min-h-screen"
          style={{ marginLeft: "60px" }}
        >
          <div className="p-6">{children}</div>
        </main>
      </body>
    </html>
  );
}
