import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")

MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://127.0.0.1:27017/fiverr-lead-extractor-crm")
POLL_INTERVAL_SEC = float(os.getenv("PYTHON_SCRAPER_POLL_SEC", "1.5"))
BLOCK_HEAVY_RESOURCES = os.getenv("BLOCK_HEAVY_RESOURCES", "true").lower() == "true"
DISCOVERY_SCROLL_LOOPS = int(os.getenv("DISCOVERY_SCROLL_LOOPS", "4"))
DISCOVERY_PAGE_WAIT_SEC = float(os.getenv("DISCOVERY_PAGE_WAIT_SEC", "1.5"))
VERIFICATION_POLL_SEC = float(os.getenv("PYTHON_VERIFICATION_POLL_SEC", "2"))
VERIFICATION_TIMEOUT_SEC = int(os.getenv("PYTHON_VERIFICATION_TIMEOUT_SEC", "600"))

PLAYWRIGHT_HEADLESS = os.getenv("PLAYWRIGHT_HEADLESS", "false").lower() == "true"
KEEP_BROWSER_PROFILE = os.getenv("KEEP_BROWSER_PROFILE", "true").lower() == "true"

# Bundled Playwright Chromium is default (avoids "profile already in use" with system Chrome on Windows).
# Set PYTHON_USE_SYSTEM_CHROME=true to use installed Google Chrome via PLAYWRIGHT_CHANNEL.
_use_system = os.getenv("PYTHON_USE_SYSTEM_CHROME", "").lower() == "true"
PLAYWRIGHT_CHANNEL = (
    (os.getenv("PYTHON_PLAYWRIGHT_CHANNEL") or os.getenv("PLAYWRIGHT_CHANNEL") or "chrome")
    if _use_system
    else (os.getenv("PYTHON_PLAYWRIGHT_CHANNEL") or None)
)

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
MAX_SEARCH_PAGES = int(os.getenv("MAX_PAGES_LIMIT", "10"))
PRESS_HOLD_SECONDS = float(os.getenv("PYTHON_PRESS_HOLD_SECONDS", "5"))
