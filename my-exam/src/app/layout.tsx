import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "PrepDesk — AI exam & interview prep",
  description:
    "Train on your own materials, generate quizzes, mocks, flashcards and interview questions with AI. Track topic weightage and mastery.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} antialiased dark`}
      suppressHydrationWarning
    >
      <body className="min-h-svh noise">
        <div className="fixed inset-0 -z-10 bg-[radial-gradient(1200px_600px_at_70%_-10%,rgba(139,92,246,0.18),transparent),radial-gradient(900px_500px_at_10%_110%,rgba(99,102,241,0.14),transparent)]" />
        {children}
      </body>
    </html>
  );
}