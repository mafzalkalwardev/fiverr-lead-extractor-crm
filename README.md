<div align="center">

# Fiverr Lead Extractor CRM

<img src="https://readme-typing-svg.demolab.com?font=Inter&weight=700&size=28&duration=2800&pause=700&color=1DBF73&center=true&vCenter=true&width=900&lines=Fiverr+Review+Lead+CRM;Playwright+Extraction+Workers;Full-Stack+Lead+Pipeline;Research-to-CRM+workflow" alt="Typing SVG" />

<p>
  <img src="https://komarev.com/ghpvc/?username=mafzalkalwardev&label=Project%20Views&color=1dbf73&style=for-the-badge" alt="Project views" />
  <img src="https://img.shields.io/github/stars/mafzalkalwardev/fiverr-lead-extractor-crm?style=for-the-badge&color=22c55e" alt="GitHub stars" />
  <img src="https://img.shields.io/github/forks/mafzalkalwardev/fiverr-lead-extractor-crm?style=for-the-badge&color=f59e0b" alt="GitHub forks" />
  <img src="https://img.shields.io/github/license/mafzalkalwardev/fiverr-lead-extractor-crm?style=for-the-badge&color=64748b" alt="License" />
</p>

<p>
  <img src="https://skillicons.dev/icons?i=ts,playwright,nodejs,react" alt="Skill icons" />
</p>

<p>
  <strong>Full-stack lead extraction CRM for Fiverr review research with Playwright workers and a research-to-CRM workflow.</strong>
</p>

</div>

---

## Trophy Cards

<div align="center">
  <img src="https://github-profile-trophy.vercel.app/?username=mafzalkalwardev&theme=algolia&no-frame=true&no-bg=true&margin-w=12&margin-h=12&column=4" alt="GitHub trophy cards" />
</div>

---

## Stats Cards

<div align="center">
  <img height="165" src="https://github-readme-stats-sigma-five.vercel.app/api?username=mafzalkalwardev&show_icons=true&theme=tokyonight&hide_border=true&rank_icon=github" alt="GitHub stats" />
  <img height="165" src="https://github-readme-stats-sigma-five.vercel.app/api/top-langs/?username=mafzalkalwardev&layout=compact&theme=tokyonight&hide_border=true" alt="Top languages" />
</div>

---

## Activity Graph

<div align="center">
  <img src="https://github-readme-activity-graph.vercel.app/graph?username=mafzalkalwardev&theme=react-dark&hide_border=true&area=true" alt="GitHub activity graph" />
</div>

---

## Contribution Snake

<div align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/mafzalkalwardev/google-voice-dispatch-agent/output/github-contribution-grid-snake-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/mafzalkalwardev/google-voice-dispatch-agent/output/github-contribution-grid-snake.svg">
    <img alt="Contribution snake" src="https://raw.githubusercontent.com/mafzalkalwardev/google-voice-dispatch-agent/output/github-contribution-grid-snake.svg">
  </picture>
</div>

---

## SEO Keywords

`Fiverr leads` `Playwright CRM` `lead extractor`

---

## Quick Start

```powershell
git clone https://github.com/mafzalkalwardev/fiverr-lead-extractor-crm.git
cd fiverr-lead-extractor-crm
npm install
python -m venv venv
venv\Scripts\activate
pip install -r python_scraper\requirements.txt
playwright install chromium
npm run seed:admin
npm run client:start:fast
```

Open:

```text
http://localhost:3000/login
```

Default local admin comes from `.env`:

```text
admin@ftsolutions.local
Admin@FT2024
```

## Local Data

The app starts a bundled or downloaded portable MongoDB runtime and stores customer data per Windows user:

```text
C:\Users\<User>\AppData\Local\FiverrLeadCRM\data\db
C:\Users\<User>\AppData\Local\FiverrLeadCRM\logs\mongod.log
```

Default database URI:

```env
MONGODB_URI=mongodb://127.0.0.1:27017/fiverr-lead-extractor-crm
```

If port `27017` is busy, startup can use `27018` and update `.env` automatically.

## Useful Commands

```powershell
npm run client:start:fast
npm run client:repair
npm run build
npx tsc --noEmit
npm run scraper:py
npm run setup:browser:py
npm run migrate:jobs
```

## Reverse Engineering Workbench

This repo also includes a local static-analysis workbench for authorized file review. It can inspect EXE/PE files, PowerShell scripts, Python/scripts, ZIP archives, and other file types without executing the target. Reports include hashes, strings, indicators, structure, Markdown/JSON output, and a runnable Python behavior scaffold.

Run the GUI:

```powershell
py -3 -m reverse_engineering_workbench.app
```

Analyze from the CLI:

```powershell
py -3 -m reverse_engineering_workbench.app "path\to\file.exe" -o analysis_reports
```

Generated code is a behavior scaffold, not exact recovered source. Install `pefile` for deeper PE import and section parsing.

## Windows Launcher

`Start Fiverr Lead CRM.bat` starts the local CRM flow: frees port `3000`, clears browser locks, starts MongoDB, launches the Next.js app and Python scraper, and opens the login page. The Electron entry is wired through `electron/main.js` for desktop-style launching.

## Focused SEO Keywords

`Fiverr lead extractor`, `Fiverr scraper CRM`, `Fiverr review scraper`, `Fiverr buyer leads`, `Playwright Fiverr automation`, `Next.js CRM dashboard`, `MongoDB lead management`, `automatic press and hold verification`, `PerimeterX verification handling`, `US Canada Fiverr leads`, `Fiverr gig review extraction`, `Fiverr lead generation software`.
