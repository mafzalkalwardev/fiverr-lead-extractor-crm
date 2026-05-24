# Client Delivery Guide - Fiverr Lead Extractor CRM

Do not hand the client this editable project folder as the final product.

Use one of these delivery models:

## Recommended: Hosted Web Link

Host the app on a Windows VPS or desktop/server you control, then give the client only:

- The app URL, for example `https://crm.yourdomain.com`
- A client login
- Basic usage instructions

The code, `.env`, MongoDB connection string, admin account, scraper profile, and browser session stay on your server.

This is the safest option because the client cannot edit code or see secrets. The Python scraper also needs a persistent Chromium profile, which is much easier to manage on a server than inside a public static/web host.

Do not use serverless-only hosting for the scraper. The scraper needs a long-running Python process and a persistent browser profile.

Production process on the server:

```powershell
npm install
npm run build
npm run seed:admin
concurrently -n web,scraper "npm start" "npm run scraper:py"
```

Run those under a process manager or Windows service for real delivery.

## Alternative: Packaged Windows App

If the client must run it locally, build an installer/executable yourself and give them that installer, not source code.

The current repo already has an Electron shell, but packaging this app properly must bundle or install:

- The built Next.js app
- The Python scraper
- A Python runtime or prepared venv
- Playwright Chromium
- The configured `.env`
- Portable MongoDB at `tools\mongodb\bin\mongod.exe`

Do not depend on MongoDB Atlas, MongoDB Compass, winget, or the MongoDB Windows Service for local customer delivery. Startup should run `scripts\start-local-mongo.ps1`, which uses:

```text
C:\Users\<User>\AppData\Local\FiverrLeadCRM\data\db
C:\Users\<User>\AppData\Local\FiverrLeadCRM\logs\mongod.log
```

After packaging, the client should only see an app icon/login screen. They should not receive `.ts`, `.tsx`, `.py`, `.env`, or project folders.

## Safe Scraper Defaults

Client machines should keep these settings:

```env
SCRAPER_ENGINE=python
PLAYWRIGHT_HEADLESS=false
ALLOW_OS_MOUSE_AUTOMATION=false
FOCUS_BROWSER_ON_VERIFICATION=true
```

`ALLOW_OS_MOUSE_AUTOMATION=false` prevents the scraper from moving/clicking the user's real desktop mouse. The scraper waits for the client to complete verification in the opened browser window.

If Fiverr verification appears, the client solves it in the scraper Chromium window. The app will continue after the session is verified.

## What Not To Deliver

Do not deliver:

- A raw ZIP of the repo
- `.env` with admin secrets visible
- Source files as the runnable product
- Browser profile/cache folders
- A dev command such as `npm run dev` as the client-facing launch method

For a professional handoff, use either a hosted link or a packaged installer.
