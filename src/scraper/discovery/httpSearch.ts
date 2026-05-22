import { normalizeFiverrUrl } from "../fiverr/urls";

const UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36";

/** Discover Fiverr gig URLs via HTTP search (no Fiverr navigation) */
export async function discoverGigsViaHttpSearch(
  niche: string,
  maxGigs: number
): Promise<string[]> {
  const query = `site:fiverr.com ${niche} "I will"`;
  const engines = [
    `https://html.duckduckgo.com/html/?q=${encodeURIComponent(query)}`,
    `https://www.bing.com/search?q=${encodeURIComponent(query)}&count=50`,
  ];

  const seen = new Set<string>();
  const results: string[] = [];

  for (const searchUrl of engines) {
    try {
      console.log(`[discovery] HTTP fetch: ${searchUrl.slice(0, 60)}...`);
      const res = await fetch(searchUrl, {
        headers: { "User-Agent": UA, Accept: "text/html", "Accept-Language": "en-US,en;q=0.9" },
        signal: AbortSignal.timeout(25_000),
      });
      const html = await res.text();

      const urlMatches = html.match(/https?:\/\/[^"'<>\s]+/g) || [];
      for (let raw of urlMatches) {
        if (raw.includes("uddg=")) {
          const m = raw.match(/uddg=([^&]+)/);
          if (m) raw = decodeURIComponent(m[1]);
        }
        const full = normalizeFiverrUrl(raw);
        if (!full || seen.has(full)) continue;
        if (!/\/[a-z0-9_-]+\/[a-z0-9_-]+/i.test(full)) continue;
        seen.add(full);
        results.push(full);
        if (results.length >= maxGigs) return results;
      }

      const relMatches = html.match(/href="(\/[^"]*fiverr[^"]*)"/gi) || [];
      for (const m of relMatches) {
        const href = m.replace(/href="/i, "").replace(/"$/, "");
        const full = normalizeFiverrUrl(href);
        if (full && !seen.has(full)) {
          seen.add(full);
          results.push(full);
          if (results.length >= maxGigs) return results;
        }
      }
    } catch (err) {
      console.warn("[discovery] HTTP search failed:", err);
    }
  }

  console.log(`[discovery] HTTP found ${results.length} Fiverr URLs`);
  return results;
}
