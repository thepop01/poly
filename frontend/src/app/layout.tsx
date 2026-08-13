import type { Metadata } from "next";
import { Fira_Code, Fira_Sans } from "next/font/google";
import "./globals.css";
import Sidebar from "../components/Sidebar";
import HeaderBar from "../components/HeaderBar";
import AuthProvider from "../components/AuthProvider";
import { WebSocketProvider } from "../components/WebSocketProvider";
import { WalletProvider } from "../components/WalletProvider";
import { ShellProvider } from "../components/ShellProvider";
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
  description: "Polymarket analytics platform — feed, wallet tracking, leaderboard, and research.",
};

import ErrorBoundary from "../components/ErrorBoundary";

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`${firaSans.variable} ${firaCode.variable} dark`}>
      <body className="flex h-screen overflow-hidden bg-background text-foreground antialiased">
        <Suspense fallback={null}>
          <WalletProvider>
            <AuthProvider>
              <WebSocketProvider>
                <ShellProvider>
                  <Sidebar />
                  <div className="flex-1 flex flex-col min-w-0">
                    <HeaderBar />
                    <main className="flex-1 overflow-auto p-5 bg-background">
                      <ErrorBoundary>
                        {children}
                      </ErrorBoundary>
                    </main>
                  </div>
                </ShellProvider>
              </WebSocketProvider>
            </AuthProvider>
          </WalletProvider>
        </Suspense>
      </body>
    </html>
  );
}
