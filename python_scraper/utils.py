import re
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urljoin, urlparse

from config import BLOCKED_PATH_PREFIXES, FIVERR_ORIGIN

BAD_SELLER_NAMES = re.compile(
    r"^(fiverr|customer support|seller|reviews?|about|contact|message|order now|profile)$",
    re.I,
)
BAD_REVIEWER_NAMES = re.compile(
    r"^(fiverr|seller|buyer|reviews?|show more|see more|helpful|customer|anonymous|\d+(\.\d+)?)$",
    re.I,
)
DELIVERY_IMAGE = re.compile(
    r"delivery|attachments|t_delivery|t_smartwm|/image/upload/|cloudinary|fiverr-res|fiverrstatic|review",
    re.I,
)


def now_utc():
    return datetime.now(timezone.utc)


def log_ts() -> str:
    return now_utc().strftime("%H:%M:%S")


def activity_line(message: str) -> str:
    return f"[{log_ts()}] {message}"


def clean_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_country(country: str) -> str:
    c = clean_text(country)
    if not c:
        return ""
    if re.match(r"^(us|usa|u\.s\.?)$", c, re.I) or re.search(r"united states", c, re.I):
        return "United States"
    if re.match(r"^ca$", c, re.I) or re.search(r"\bcanada\b", c, re.I):
        return "Canada"
    return c


def is_target_country(country: str, targets: list[str]) -> bool:
    norm = normalize_country(country)
    if not norm:
        return False
    target_set = {normalize_country(t).lower() for t in targets}
    return norm.lower() in target_set


def normalize_fiverr_url(href: str) -> Optional[str]:
    if not href or href.startswith("javascript:"):
        return None
    try:
        url = urlparse(href if href.startswith("http") else urljoin(FIVERR_ORIGIN, href))
        if "fiverr.com" not in url.netloc:
            return None
        parts = [p for p in url.path.split("/") if p]
        if len(parts) < 2:
            return None
        if parts[0].lower() in BLOCKED_PATH_PREFIXES:
            return None
        return f"{FIVERR_ORIGIN}/{'/'.join(parts)}"
    except Exception:
        return None


def absolutize_url(src: Optional[str]) -> str:
    if not src:
        return ""
    if src.startswith("//"):
        return f"https:{src}"
    if src.startswith("/"):
        return f"{FIVERR_ORIGIN}{src}"
    return src


def build_dedupe_key(gig_link: str, reviewer_name: str, review: str) -> str:
    parts = [gig_link, reviewer_name, review]
    return "|||".join(p.strip().lower() for p in parts)


def is_valid_fiverr_url(value: str) -> bool:
    try:
        u = urlparse(value)
        return u.scheme == "https" and (
            u.hostname == "fiverr.com" or (u.hostname or "").endswith(".fiverr.com")
        )
    except Exception:
        return False


def is_valid_seller_name(name: str, username: str, gig_title: str) -> bool:
    n = clean_text(name).lstrip("@")
    if len(n) < 2 or len(n) > 80:
        return False
    if BAD_SELLER_NAMES.match(n):
        return False
    if gig_title and n.lower() == gig_title.lower():
        return False
    if username and n.lower() == username.lower():
        return True
    if re.search(r"\d+(\.\d+)?\s*stars?", n, re.I):
        return False
    return bool(re.match(r"^[a-zA-Z0-9_\-\s'.]{2,80}$", n))


def is_valid_reviewer_name(name: str) -> bool:
    n = clean_text(name).lstrip("@")
    if len(n) < 2 or len(n) > 50:
        return False
    if BAD_REVIEWER_NAMES.match(n):
        return False
    if re.match(r"^\d+(\.\d+)?$", n):
        return False
    if " " in n and len(n.split()) > 4:
        return False
    return bool(re.match(r"^[a-zA-Z0-9_][a-zA-Z0-9_\-\.]{1,49}$", n))


def is_valid_review_image(url: str) -> bool:
    if not url or not url.startswith("http"):
        return False
    lower = url.lower()
    if not ("fiverr" in lower or "cloudinary" in lower):
        return False
    if re.search(r"trophy|generic_asset|badge|avatar|profile|seller|\.gif", url, re.I):
        return False
    if DELIVERY_IMAGE.search(url):
        return True
    if re.search(r"\.(jpg|jpeg|png|webp)(\?|$)", url, re.I) and "fiverr" in lower:
        return True
    return False


def is_valid_real_lead(gig: dict, review: dict) -> bool:
    if not is_valid_fiverr_url(gig.get("gigUrl", "")):
        return False

    username = clean_text(gig.get("sellerUsername") or "")
    seller = clean_text(gig.get("sellerName") or username)
    if not username or len(username) < 2:
        return False
    if BAD_SELLER_NAMES.match(seller) or BAD_SELLER_NAMES.match(username):
        return False

    title = clean_text(gig.get("gigTitle"))
    if len(title) < 3:
        return False

    reviewer = clean_text(review.get("reviewerName"))
    if not is_valid_reviewer_name(reviewer):
        return False

    text = clean_text(review.get("reviewText"))
    if len(text) < 15:
        return False

    if not clean_text(review.get("reviewerCountry")):
        return False

    img = clean_text(review.get("reviewedImageLink"))
    if not is_valid_review_image(img):
        return False

    rating = review.get("reviewRating", 0)
    try:
        rating = float(rating)
    except (TypeError, ValueError):
        return False
    return 1 <= rating <= 5


def count_lead_bucket(country: str) -> str:
    c = normalize_country(country).lower()
    if c == "united states":
        return "us"
    if c == "canada":
        return "canada"
    return "other"
