import type { Metadata } from "next";
import { Plus_Jakarta_Sans } from "next/font/google";
import "./globals.css";
import { AppToastProvider } from "@/components/providers/toast-provider";
import { APP_NAME, COMPANY_NAME } from "@/lib/constants";
import { WhatsAppButton } from "@/components/whatsapp-button";

const font = Plus_Jakarta_Sans({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-sans",
});

export const metadata: Metadata = {
  title: `${APP_NAME} - ${COMPANY_NAME}`,
  description: "Live Fiverr lead extraction — US/Canada reviews only — FT Solutions",
  icons: { icon: "/icon.svg", apple: "/icon.svg" },
};

/**
 * Inline script that strips `bis_skin_checked` attributes injected by the
 * Bitdefender browser extension. It must run **synchronously** during HTML
 * parsing (before React hydration) so the client DOM matches the server HTML.
 *
 * Using a raw `<script dangerouslySetInnerHTML>` instead of Next.js `<Script>`
 * because `strategy="beforeInteractive"` in the App Router is still deferred
 * and doesn't execute early enough.
 */
const STRIP_EXTENSION_ATTRS_SCRIPT = `
(function(){
  var a="bis_skin_checked";
  function s(r){
    if(!r)return;
    if(r.nodeType===1&&r.hasAttribute&&r.hasAttribute(a))r.removeAttribute(a);
    if(r.querySelectorAll)r.querySelectorAll("["+a+"]").forEach(function(e){e.removeAttribute(a)});
  }
  s(document);
  new MutationObserver(function(m){
    for(var i=0;i<m.length;i++){
      s(m[i].target);
      if(m[i].addedNodes)m[i].addedNodes.forEach(s);
    }
  }).observe(document.documentElement,{subtree:true,childList:true,attributes:true,attributeFilter:[a]});
})();
`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark" suppressHydrationWarning>
      <head>
        <script
          dangerouslySetInnerHTML={{ __html: STRIP_EXTENSION_ATTRS_SCRIPT }}
          suppressHydrationWarning
        />
      </head>
      <body className={font.className} suppressHydrationWarning>
        <AppToastProvider>{children}</AppToastProvider>
        <WhatsAppButton />
      </body>
    </html>
  );
}
