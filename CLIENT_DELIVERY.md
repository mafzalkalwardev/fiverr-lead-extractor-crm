# Client delivery guide — Fiverr Lead Extractor CRM

This project is a **local business application**, not a public website like Fiverr.com. The client runs it on their PC (or on a server you manage). There is no single “app link” unless you deploy it yourself.

---

## What to give the client

| Deliverable | Purpose |
|-------------|---------|
| **Project folder** (or ZIP) | Full app + Python scraper |
| **`.env`** (configured by you) | MongoDB URL, JWT secret — **never** put admin password on the login page |
| **`CLIENT_DELIVERY.md`** (this file) | How to run |
| **Admin login** (email + password) | Send privately (email/WhatsApp) — created with `npm run seed:admin` |
| **Optional:** Desktop shortcut | Runs `npm run client:start` (see below) |

Do **not** commit `.env` to Git. Admin credentials live only in `.env` and your private message to the client.

---

## Two ways to deliver

### Option A — Client’s computer (recommended)

Everything runs locally: CRM in the browser + Python scraper + MongoDB.

**Requirements on client PC**

- Windows 10/11
- [Node.js 20+](https://nodejs.org/)
- [MongoDB](https://www.mongodb.com/try/download/community) (running as a service)
- Python 3.11+ (for scraper)

**One-time setup (you or client)**

```powershell
cd "C:\path\to\Fiverr Scraper"
python -m venv venv
.\venv\Scripts\activate
pip install -r python_scraper\requirements.txt
playwright install chromium
npm install
copy .env.example .env
# Edit .env: MONGODB_URI, JWT_SECRET, ADMIN_EMAIL, ADMIN_PASSWORD
npm run seed:admin
npm run setup:browser:py
```

**Every day — start the app (no coding required)**

Double-click:

**`Start Fiverr Lead CRM.bat`**

(in the project folder — copy a shortcut to the client’s Desktop)

Or run:

```powershell
npm run client:start
```

Then open: **http://localhost:3000/setup** (or the port shown in the terminal).

Sign in with the credentials you sent privately.

**Optional desktop window (Electron — feels like an “app”)**

```powershell
npm run electron:app
```

Starts the CRM + scraper and opens a desktop window (not a separate `.exe` installer unless you package with electron-builder later).

**There is no public website link** unless you deploy to a VPS yourself. The client uses **localhost** on their PC.

---

### Option B — You host on a VPS (advanced)

Deploy Next.js + MongoDB + Python scraper on a server (e.g. DigitalOcean, AWS). Client opens:

`https://your-domain.com`

You must:

1. Build: `npm run build` → `npm start` (port 3000 behind nginx)
2. Run Python scraper as a **system service** (always on): `npm run scraper:py`
3. Set `NEXT_PUBLIC_APP_URL` and `NEXT_PUBLIC_CLIENT_MODE=true` in `.env`
4. Use HTTPS and a strong `JWT_SECRET`

This is more work; most clients use **Option A**.

---

## How it works after “deployment”

1. **CRM (web UI)** — Create jobs, view leads, export Excel.
2. **Python scraper** — Polls MongoDB every ~1.5s, picks `pending` jobs, opens Fiverr in Chromium, saves US/Canada leads.
3. **MongoDB** — Stores jobs, leads, users.

The scraper must be running for jobs to move from **Pending** → **Running**. `npm run client:start` starts both CRM and scraper automatically.

---

## Client-facing settings (`.env`)

```env
NEXT_PUBLIC_CLIENT_MODE=true
PLAYWRIGHT_HEADLESS=false
BLOCK_HEAVY_RESOURCES=true
PYTHON_SCRAPER_POLL_SEC=1.5
DEFAULT_DELAY_SECONDS=2
MAX_PAGES_LIMIT=10
```

- `BLOCK_HEAVY_RESOURCES=true` — faster pages, less RAM (review image URLs still captured from HTML).
- `PLAYWRIGHT_HEADLESS=true` — no visible browser (use after Fiverr verification is saved in profile).

---

## Admin credentials

- Set in `.env`: `ADMIN_EMAIL`, `ADMIN_PASSWORD`
- Create user: `npm run seed:admin`
- **Never** display these on the login screen (already removed in the UI).

To add client users: sign in as admin → **Users** → create accounts with role `user`.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Jobs stay **pending** | Start scraper: `npm run scraper:py` or `npm run client:start` |
| “Scraper service offline” banner | Same as above |
| Browser profile locked | `npm run free:browser` then restart |
| Slow UI in dev | Use production: `npm run build` then `npm run client:prod` |
| Fiverr verification | Complete once in browser; click **Retry** on the job |

---

## Support contact

Configured in branding: **FT Solutions** · phone in `src/lib/constants.ts`.

For delivery, you can white-label `COMPANY_NAME` / `COMPANY_PHONE` before handing off the ZIP.
