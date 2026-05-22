# Delivery — Fiverr Lead Extractor CRM (working setup)

## Important

Fiverr blocks **unattended** bots. This app does **not** bypass CAPTCHA.
It uses a **persistent browser profile** so you verify **once**, then jobs reuse that session.

---

## 5-minute working setup

### Terminal 1 — Redis
```powershell
cd "C:\Users\pc\Desktop\Fiverr Scraper"
powershell -ExecutionPolicy Bypass -File scripts\start-redis5.ps1
```

### Terminal 2 — One-time browser setup (visible window)
```powershell
cd "C:\Users\pc\Desktop\Fiverr Scraper"
npm run setup:browser
```
Complete "Press & Hold" in the Chromium window → press ENTER in terminal.

### Terminal 3 — Worker
```powershell
npm run worker
```

### Terminal 4 — App
```powershell
npm run dev
```

Login: `admin@ftsolutions.local` / `Admin@FT2024`

If login fails (invalid token): clear site data / use incognito once, or re-login after `npm run seed:admin`.

---

## Create a job that WORKS

### Option A — Manual URLs (fastest, always works after setup)
1. In **Chrome**, search Fiverr for your niche, open 3–5 gigs.
2. Copy full URLs (`https://www.fiverr.com/seller/gig-slug`).
3. App → **Create Job** → **Manual Browser Mode** → paste URLs.
4. Monitor → Export.

### Option B — Live mode (after setup:browser)
1. **Create Job** → **Live Mode** → niche `car wrap`.
2. If `verification_required` → complete in worker browser → **Retry**.

### Option C — HTML Import (no live Fiverr)
1. Save gig pages as `.html` (Ctrl+S).
2. **HTML Import** → upload files.

## .env (required)
```
SCRAPER_MODE=playwright
PLAYWRIGHT_HEADLESS=false
KEEP_BROWSER_PROFILE=true
PLAYWRIGHT_CHANNEL=chrome
```
(Use Chrome if installed — often passes verification better than bundled Chromium.)
