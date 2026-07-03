import type { Metadata } from "next";
import { Fira_Code, Fira_Sans } from "next/font/google";
import "./globals.css";
import Sidebar from "../components/Sidebar";
import AuthProvider from "../components/AuthProvider";
import { WebSocketProvider } from "../components/WebSocketProvider";
import { WalletProvider } from "../components/WalletProvider";
import { Suspense } from "react";

const firaSans = Fira_Sans({
  variable: "--font-fira-sans",
  subsets: ["latin"],
  weight: ["300", "400", "500", "600", "700"],
  display: "swap",
});

const firaCode = Fira_Code({
  variable: "--font-fira-code",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "PolyTracker Analytics",
  description: "Polymarket analytics platform — alpha calls, wallet tracking, leaderboard, and research.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`${firaSans.variable} ${firaCode.variable} dark`}>
      <body className="flex h-screen overflow-hidden bg-background text-[#F8FAFC] antialiased">
        <Suspense fallback={null}>
          <WalletProvider>
            <AuthProvider>
              <WebSocketProvider>
                <Sidebar />
                <main className="flex-1 overflow-auto p-4 bg-background">
                  {children}
                </main>
              </WebSocketProvider>
            </AuthProvider>
          </WalletProvider>
        </Suspense>
      </body>
    </html>
  );
}
