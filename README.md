# Fiverr Lead Extractor CRM

**FT Solutions** · +92307-9670503

Full-stack CRM (Next.js + Electron) with a **Python Playwright scraper** for reliable Fiverr lead extraction.

- **Next.js / Electron** — login, admin CRM, create jobs, live monitor, leads, Excel export  
- **Python scraper** — Fiverr search, gig pages, verification wait, review extraction, MongoDB updates  

No demo data. No fake fallbacks. No CAPTCHA bypass.

## Architecture

```
┌─────────────────────┐     MongoDB      ┌──────────────────────┐
│  Next.js + Electron │ ◄──────────────► │  python_scraper/     │
│  (UI + APIs)        │   jobs + leads   │  Playwright service  │
└─────────────────────┘                  └──────────────────────┘
```

Jobs are created with `status: pending`. The Python service polls MongoDB and processes jobs automatically.

**Handing off to a client?** See [CLIENT_DELIVERY.md](./CLIENT_DELIVERY.md).

## Quick start (Windows)

### 1. Node.js app

```powershell
cd "C:\Users\pc\Desktop\Fiverr Scraper"
npm install
npm run seed:admin
```

### 2. Python scraper

```powershell
python -m venv venv
venv\Scripts\activate
pip install -r python_scraper\requirements.txt
playwright install chromium
```

### 3. MongoDB

Ensure MongoDB is running (default `mongodb://127.0.0.1:27017/fiverr-lead-extractor-crm`).

### 4. Run everything

**Terminal A — app + scraper:**

```powershell
npm run dev:all
```

Or separately:

```powershell
npm run dev
npm run scraper:py
```

**Electron desktop:**

```powershell
npm run electron:dev
```

Open **http://localhost:3000** · Login: `admin@ftsolutions.local` / `Admin@FT2024`

### 5. One-time Fiverr verification

```powershell
npm run free:browser
npm run setup:browser:py
```

Complete “Press & Hold” in the browser window. Session is saved in `./browser-profile-py`.

**Browser won’t start?** Another Chrome instance is using the profile:

```powershell
npm run free:browser
npm run scraper:py
```

### Fix Next.js `routes-manifest.json` missing

```powershell
npm run clean
npm run dev
```

Stop other `npm run dev` terminals first (only one dev server).

## `.env` (scraper)

```env
MONGODB_URI=mongodb://127.0.0.1:27017/fiverr-lead-extractor-crm
SCRAPER_MODE=playwright
PLAYWRIGHT_HEADLESS=false
KEEP_BROWSER_PROFILE=true
PLAYWRIGHT_CHANNEL=chrome
```

Redis is **optional** (legacy Node worker only).

## npm scripts

| Command | Description |
|---------|-------------|
| `npm run dev` | Next.js dev server |
| `npm run scraper:py` | Python scraper service |
| `npm run dev:all` | Dev + Python scraper |
| `npm run worker` | Legacy Node/BullMQ worker (optional) |
| `npm run setup:browser:py` | One-time Fiverr verification (Python) |
| `npm run electron:dev` | Dev + Python scraper + Electron |
| `npm run build` | Production Next.js build |

## Python scraper layout

```
python_scraper/
  main.py           # Poll loop + heartbeat
  config.py         # .env settings
  db.py             # MongoDB jobs/leads
  browser.py        # Persistent Chrome profile
  discovery.py      # Fiverr search URL discovery
  gig_parser.py     # Seller, title, main image
  review_parser.py  # US/Canada reviews only
  verification.py   # Wait for Press & Hold (2s poll)
  worker.py         # Job processor
  utils.py          # URLs, countries, dedupe
  requirements.txt
```

## Verification flow

1. Fiverr shows human verification → job `verification_required`
2. Chrome stays open; Python checks every **2 seconds**
3. When verification clears → extraction continues automatically
4. User can also click **Retry** in the CRM (sets `pending` again)

## Extraction modes (UI)

- **Automatic Search** — niche → Fiverr search → gig URLs → reviews  
- **Paste Gig Links** — one Fiverr URL per line (non-technical friendly)  

## Excel export

Sheet **Fiverr Leads** — full URLs, US/Canada only, dedupe by gig + reviewer + review text.

## Requirements

- Node.js 18+
- Python 3.11+
- MongoDB
- Google Chrome (recommended via `PLAYWRIGHT_CHANNEL=chrome`)
