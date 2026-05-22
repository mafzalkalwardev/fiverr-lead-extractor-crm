import type { Metadata } from "next";
import { Plus_Jakarta_Sans } from "next/font/google";
import "./globals.css";
import { AppToastProvider } from "@/components/providers/toast-provider";
import { APP_NAME, COMPANY_NAME } from "@/lib/constants";

const font = Plus_Jakarta_Sans({ subsets: ["latin"], variable: "--font-sans" });

export const metadata: Metadata = {
  title: `${APP_NAME} - ${COMPANY_NAME}`,
  description: "Live Fiverr lead extraction — US/Canada reviews only — FT Solutions",
  icons: { icon: "/icon.svg", apple: "/icon.svg" },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark" suppressHydrationWarning>
      <body className={font.className} suppressHydrationWarning>
        <AppToastProvider>{children}</AppToastProvider>
      </body>
    </html>
  );
}
