import "@/lib/load-env";
import { discoverGigsViaHttpSearch } from "@/scraper/discovery/httpSearch";

async function main() {
  const urls = await discoverGigsViaHttpSearch("car wrap", 15);
  urls.forEach((u, i) => console.log(`${i + 1}. ${u}`));
  if (urls.length === 0) {
    const q = "site:fiverr.com car wrap";
    const res = await fetch(`https://html.duckduckgo.com/html/?q=${encodeURIComponent(q)}`, {
      headers: { "User-Agent": "Mozilla/5.0" },
    });
    const html = await res.text();
    console.log("HTML length:", html.length);
    const idx = html.indexOf("fiverr.com");
    console.log("Sample:", html.slice(Math.max(0, idx - 50), idx + 200));
  }
  process.exit(urls.length ? 0 : 1);
}

main().catch(console.error);
