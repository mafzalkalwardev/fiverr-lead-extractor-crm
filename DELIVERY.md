# Delivery - Fiverr Lead Extractor CRM

## Important

Fiverr blocks unattended bots. This app does not bypass CAPTCHA. It uses a persistent browser profile so the customer verifies when Fiverr asks, then jobs reuse that session.

## Customer Local Database

Customer delivery uses bundled portable MongoDB, not Atlas, Compass, winget, or the MongoDB Windows Service.

Startup runs:

```powershell
scripts\start-local-mongo.ps1
```

Database files:

```text
C:\Users\<User>\AppData\Local\FiverrLeadCRM\data\db
C:\Users\<User>\AppData\Local\FiverrLeadCRM\logs\mongod.log
```

Default local URI:

```env
MONGODB_URI=mongodb://127.0.0.1:27017/fiverr-lead-extractor-crm
```

If `27017` is busy, startup uses `27018` and updates `.env`.

## 5-minute Working Setup

Double-click `Start Fiverr Lead CRM.bat` or run:

```powershell
npm run client:start:fast
```

Login: `admin@ftsolutions.local` / `Admin@FT2024`

If login fails, clear site data or sign in from an incognito window once. If the admin account is missing, run `npm run seed:admin` after portable MongoDB is ready.

## Create A Job That Works

### Option A - Manual URLs

1. In Chrome, search Fiverr for your niche and open 3-5 gigs.
2. Copy full URLs like `https://www.fiverr.com/seller/gig-slug`.
3. App -> Create Job -> Manual Browser Mode -> paste URLs.
4. Monitor -> Export.

### Option B - Live Mode

1. Create Job -> Live Mode -> enter a niche such as `car wrap`.
2. If `verification_required` appears, complete verification in the scraper browser, then retry if needed.

### Option C - HTML Import

1. Save gig pages as `.html`.
2. HTML Import -> upload files.

## Client .env Defaults

```env
MONGODB_URI=mongodb://127.0.0.1:27017/fiverr-lead-extractor-crm
SCRAPER_ENGINE=python
SCRAPER_MODE=playwright
PLAYWRIGHT_HEADLESS=false
KEEP_BROWSER_PROFILE=true
PYTHON_AUTO_VERIFICATION_MAX_ATTEMPTS=0
```
