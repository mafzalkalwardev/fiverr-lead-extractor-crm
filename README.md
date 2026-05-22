# Fiverr Lead Extractor CRM

**FT Solutions** · +92307-9670503

**LIVE-ONLY** Fiverr lead extraction: real search → real gigs → real reviews → US/Canada filter → Excel export.

> `SCRAPER_MODE` must be `playwright`. If extraction fails, nothing is fabricated.

## Live workflow

1. User enters niche (e.g. `car wrap`)
2. Opens `https://www.fiverr.com/search/gigs?query=...`
3. Collects real gig URLs from search cards
4. For each gig: seller name, gig link, title, main image
5. Scrolls reviews, loads more, extracts reviewer/country/text/rating/date/image
6. Saves **only** United States & Canada reviews
7. Stops on max gigs, max leads, user stop, or Fiverr block/CAPTCHA

## Quick start (Windows PowerShell)

```powershell
cd "C:\Users\pc\Desktop\Fiverr Scraper"
npm install
npx playwright install chromium
npm run seed:admin

# Terminal 1 — Redis 5+
powershell -ExecutionPolicy Bypass -File scripts\start-redis5.ps1

# Terminal 2 — App
npm run dev

# Terminal 3 — Worker (required)
npm run worker
```

`.env` settings:

```
SCRAPER_MODE=playwright
PLAYWRIGHT_HEADLESS=false
```

Login: `admin@ftsolutions.local` / `Admin@FT2024`

## Excel export

- Sheet: **Fiverr Leads**
- Columns: Seller Name, Gig Link, Gig Title, Reviewer Name, Country, Review, Reviewed Image Link, Main Gig Image, Service/Niche, Scraped At
- Full URLs in cells (not "View"/"Image" labels)
- Dedupe: Gig Link + Reviewer Name + Review

## Scripts

| Command | Description |
|---------|-------------|
| `npm run clean` | Clear `.next` cache |
| `npm run dev` | Next.js dev server |
| `npm run worker` | BullMQ live scrape worker |
| `npm run dev:all` | Dev + worker |
| `npm run build` | Production build |
| `npm run electron:dev` | Dev + worker + Electron window |
| `npm run electron:build` | Build + Electron |

## Fiverr CAPTCHA / PerimeterX

Fiverr may show **"It needs a human touch"** for automated browsers. When this happens, the job is marked **blocked**.

**Fix (one-time):**

1. Set `PLAYWRIGHT_HEADLESS=false` in `.env`
2. Run `npm run worker` — a Chromium window opens
3. Start a job; when Fiverr shows the challenge, complete it manually in that window
4. Cookies are saved in `browser-profile/` for later runs

Optional: `PLAYWRIGHT_CHANNEL=chrome` to use installed Google Chrome.

## Requirements

- Node.js 18+
- MongoDB
- Redis **5.0+** (`scripts/start-redis5.ps1`)
- Playwright Chromium (`npx playwright install chromium`)
