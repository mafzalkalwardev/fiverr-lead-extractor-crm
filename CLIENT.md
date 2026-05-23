# Client Run Guide

## Start the Software

Double-click:

```text
dist\Fiverr Lead Extractor.exe
```

Keep the black command window open while using the CRM.

Login page:

```text
http://localhost:3000/login
```

Default login:

```text
admin@ftsolutions.local
Admin@FT2024
```

## First-Time Requirements

Install these before running on a new PC:

- Node.js 18 or newer
- Python 3.11 or newer
- MongoDB

From the project folder, run once:

```powershell
npm install
python -m venv venv
venv\Scripts\activate
pip install -r python_scraper\requirements.txt
playwright install chromium
npm run seed:admin
```

## Creating a Job

1. Open Create Job.
2. Choose Automatic Search or Paste Gig Links.
3. Enter the service/niche, for example `Wordpress Web Development`.
4. Choose one review image option:
   - With review image link: only reviews that have a review image.
   - Without review image link: faster, saves US/Canada reviews without image links.
5. Click Start Lead Extraction.

If you run the same keyword again, the app skips gigs already used by earlier jobs and continues with further search results.

## Fiverr Verification

If Fiverr shows Press & Hold verification, complete it in the scraper browser window. The app will keep checking and continue automatically. Use Retry only if the job stays paused after verification is solved.

## Export

Open Leads or Job Monitor and click Export. The Excel file includes seller details, gig URL, review, rating, country, service niche, and review image link when that mode was selected.

## Troubleshooting

If the app does not open:

```powershell
Repair Start.bat
```

If the scraper browser is locked:

```powershell
npm run free:browser
```

If port 3000 is busy:

```powershell
npm run free:port
```
