import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")

MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://127.0.0.1:27017/fiverr-lead-extractor-crm")
POLL_INTERVAL_SEC = float(os.getenv("PYTHON_SCRAPER_POLL_SEC", "1.5"))
BLOCK_HEAVY_RESOURCES = os.getenv("BLOCK_HEAVY_RESOURCES", "true").lower() == "true"
REVIEW_LOAD_MORE_MAX = int(os.getenv("REVIEW_LOAD_MORE_MAX", "60"))
GIG_PAGE_WAIT_SEC = float(os.getenv("GIG_PAGE_WAIT_SEC", "1"))
DISCOVERY_SCROLL_LOOPS = int(os.getenv("DISCOVERY_SCROLL_LOOPS", "4"))
DISCOVERY_PAGE_WAIT_SEC = float(os.getenv("DISCOVERY_PAGE_WAIT_SEC", "1.5"))
VERIFICATION_POLL_SEC = float(os.getenv("PYTHON_VERIFICATION_POLL_SEC", "2"))
VERIFICATION_TIMEOUT_SEC = int(os.getenv("PYTHON_VERIFICATION_TIMEOUT_SEC", "600"))

PLAYWRIGHT_HEADLESS = os.getenv("PLAYWRIGHT_HEADLESS", "false").lower() == "true"
KEEP_BROWSER_PROFILE = os.getenv("KEEP_BROWSER_PROFILE", "true").lower() == "true"

# Python scraper: bundled Playwright Chromium only unless PYTHON_USE_SYSTEM_CHROME=true.
# PLAYWRIGHT_CHANNEL in .env is for the legacy Node worker — ignored here by default.
_use_system = os.getenv("PYTHON_USE_SYSTEM_CHROME", "false").lower() == "true"
PLAYWRIGHT_CHANNEL: Optional[str]
if _use_system:
    PLAYWRIGHT_CHANNEL = (
        os.getenv("PYTHON_PLAYWRIGHT_CHANNEL")
        or os.getenv("PLAYWRIGHT_CHANNEL")
        or "chrome"
    )
else:
    PLAYWRIGHT_CHANNEL = os.getenv("PYTHON_PLAYWRIGHT_CHANNEL") or None

# Separate from Node/legacy profile to avoid SingletonLock conflicts on Windows
_profile = os.getenv("PYTHON_BROWSER_PROFILE", "browser-profile-py")
BROWSER_PROFILE_DIR = ROOT_DIR / _profile
FIVERR_ORIGIN = "https://www.fiverr.com"

DEFAULT_TARGET_COUNTRIES = ["United States", "Canada"]
VERIFICATION_MESSAGE = (
    "Complete Fiverr verification in the browser window that opens automatically, "
    "then wait — the scraper will continue automatically when verification clears."
)

BLOCKED_PATH_PREFIXES = {
    "search", "categories", "users", "support", "login", "join",
    "inbox", "collections", "pro", "cp", "cart", "checkout",
}

JOBS_COLLECTION = "scrapejobs"
LEADS_COLLECTION = "leads"
HEARTBEAT_COLLECTION = "system_heartbeats"
HEARTBEAT_ID = "python_scraper"

STALE_RUNNING_MINUTES = int(os.getenv("PYTHON_STALE_JOB_MINUTES", "2"))
# 0 = paginate through all search result pages (until last page / safety cap)
MAX_SEARCH_PAGES = int(os.getenv("MAX_PAGES_LIMIT", "0"))
MAX_SEARCH_PAGES_SAFETY = int(os.getenv("MAX_SEARCH_PAGES_SAFETY", "100"))
PRESS_HOLD_SECONDS = float(os.getenv("PYTHON_PRESS_HOLD_SECONDS", "5"))
