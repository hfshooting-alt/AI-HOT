import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const assetBase = process.env.GITHUB_PAGES === "true" ? "/AI-HOT" : "";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "AI HOT · AI 情报仪表盘",
  description: "全部 AI 动态 / 公司与产品全景 / 热点榜 / 日报周报，一站式 AI 情报看板。",
  icons: {
    icon: `${assetBase}/favicon.svg`,
    shortcut: `${assetBase}/favicon.svg`,
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased`}
      >
        {children}
      </body>
    </html>
  );
}
