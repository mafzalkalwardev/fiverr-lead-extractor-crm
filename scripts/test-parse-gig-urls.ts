import { parseGigUrlsFromText } from "../src/lib/extraction-modes";
import { normalizeFiverrUrl } from "../src/scraper/fiverr/urls";

const samples = `
https://www.fiverr.com/seller1/do-something-cool
http://fiverr.com/seller2/another-gig,
www.fiverr.com/seller3/third-gig
seller4/fourth-gig
not a url
https://www.fiverr.com/search/gigs?query=test
`;

const parsed = parseGigUrlsFromText(samples);
const normalized = parsed.flatMap((u) => {
  const n = normalizeFiverrUrl(u);
  return n ? [n] : [];
});

console.log("parsed:", parsed);
console.log("normalized:", normalized);

if (normalized.length < 3) {
  console.error("FAIL: expected at least 3 valid gig URLs");
  process.exit(1);
}
if (normalized.some((u) => u.includes("/search/"))) {
  console.error("FAIL: search URL should be rejected");
  process.exit(1);
}
console.log("OK");
