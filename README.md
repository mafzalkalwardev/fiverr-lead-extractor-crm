# Fiverr Lead Extractor CRM

FT Solutions - +92307-9670503

Next.js CRM plus a Python Playwright scraper for collecting Fiverr leads from public US/Canada reviews. Jobs are created in the web UI, stored in MongoDB, and processed by the Python scraper service.

## Main Features

- Login, dashboard, job monitor, lead table, and Excel export.
- Automatic Fiverr search or pasted gig URLs.
- Review image mode per job:
  - With review image link: saves only US/Canada reviews with a valid buyer review/delivery image.
  - Without review image link: faster mode that saves US/Canada reviews and leaves the review image column empty.
- Same-keyword continuation: a new live job with the same niche skips gig URLs already queued by earlier jobs for that user.
- Failed gig logging: failed URLs are recorded, screenshots/HTML are saved under `test-results/`, and failed gigs are retried once before the job completes.
- Agency/gig image protection: seller, agency, profile, and main gig images are no longer accepted as review image links.
- Fiverr verification handling: the scraper watches for Fiverr verification pages, keeps the browser open, and resumes automatically after the client completes the check.
- Browser-extension hydration cleanup for `bis_skin_checked` so extension-injected attributes do not trigger Next hydration errors.

## Quick Start

```powershell
cd "C:\Users\pc\Desktop\Fiverr Scraper"
npm install
python -m venv venv
venv\Scripts\activate
pip install -r python_scraper\requirements.txt
playwright install chromium
npm run seed:admin
```

The app starts bundled portable MongoDB automatically. It stores local customer data in:

```text
C:\Users\<User>\AppData\Local\FiverrLeadCRM\data\db
C:\Users\<User>\AppData\Local\FiverrLeadCRM\logs\mongod.log
```

The default local database URI is:

```env
MONGODB_URI=mongodb://127.0.0.1:27017/fiverr-lead-extractor-crm
```

If port `27017` is already busy, startup uses `27018` and updates `.env` automatically.

Run app and scraper together:

```powershell
npm run client:start:fast
```

Open `http://localhost:3000/login`.

Default admin from `.env`:

```text
admin@ftsolutions.local
Admin@FT2024
```

## Windows EXE Launcher

The launcher has been built here:

```text
dist\Fiverr Lead Extractor.exe
```

It starts `Start Fiverr Lead CRM.bat`, which frees port 3000, clears browser locks, starts the Next.js app and Python scraper, and opens the login page.

## Useful Commands

```powershell
npm run build
npx tsc --noEmit
npm run scraper:py
npm run setup:browser:py
npm run migrate:jobs
```

Use `npm run setup:browser:py` once if Fiverr shows verification before scraping.

## Notes

This software does not bypass CAPTCHA. If Fiverr asks for human verification, solve it in the scraper browser window and leave that window open. The scraper will continue after verification clears.
