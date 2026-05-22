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
COUNTRY_IN_TEXT = re.compile(
    r"\b(United States|USA|U\.S\.?|Canada)\b",
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


def username_from_gig_url(url: str) -> str:
    """First path segment on fiverr.com/{username}/... — canonical seller id."""
    try:
        parts = [p for p in urlparse(url).path.strip("/").split("/") if p]
        if not parts:
            return ""
        first = parts[0].lower()
        if first in BLOCKED_PATH_PREFIXES:
            return ""
        return parts[0]
    except Exception:
        return ""


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


def looks_like_rating(value: str) -> bool:
    n = clean_text(value)
    if not n:
        return True
    if re.match(r"^\d+(\.\d+)?$", n):
        return True
    if re.match(r"^[1-5](?:\.\d)?$", n):
        return True
    if re.search(r"\bstars?\b", n, re.I):
        return True
    return False


def _slug_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _name_is_seller(name: str, seller_username: str) -> bool:
    """Skip when inferred text refers to the gig seller, not the buyer."""
    seller = _slug_key(seller_username)
    if not seller:
        return False
    return _slug_key(name) == seller


def infer_reviewer_from_text(review_text: str, seller_username: str = "") -> str:
    """Guess buyer name from review body when DOM only exposes star rating."""
    text = clean_text(review_text)
    if len(text) < 20:
        return ""
    seller = clean_text(seller_username)

    name_cap = r"([A-Za-z][A-Za-z0-9_.'-]+(?:\s+[A-Za-z][A-Za-z0-9_.'-]+){0,3})"
    patterns = [
        r"(?:great experience with|experience with|pleasure with|working with|thanks to|recommend)\s+"
        r"([A-Za-z][A-Za-z0-9_.'-]+)",
        r"^([A-Za-z][A-Za-z0-9_.'-]{1,40})\s+"
        r"(?:did|was|is|has|truly|really|always|delivered|provided|went|made|took|helped|gave|"
        r"exceptional|fantastic|great|excellent|outstanding|once|just|another|absolute)\b",
        r"^([A-Za-z][A-Za-z0-9_.'-]{1,40})\s+truly\b",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if not m:
            continue
        name = clean_text(m.group(1)).lstrip("@").rstrip(".")
        if _name_is_seller(name, seller):
            continue
        if is_valid_reviewer_name(name):
            return name
    return ""


def reviewer_name_before_country(text: str) -> str:
    """
    Fiverr review cards: [Reviewer Name] [Country] [Rating] [Review body...]
    Take the label immediately before the country — not the rating after it.
    """
    raw = clean_text(text)
    if len(raw) < 10:
        return ""
    m = COUNTRY_IN_TEXT.search(raw)
    if not m:
        return ""

    before = raw[: m.start()].strip()
    before = re.sub(r"^[1-5](?:\.\d)?\s*", "", before).strip()
    before = re.sub(
        r"\b\d+\s+(?:day|days|week|weeks|month|months|year|years)\s+ago\b",
        "",
        before,
        flags=re.I,
    ).strip()
    before = re.sub(r"\b(?:published|posted|replied)\b.*$", "", before, flags=re.I).strip()

    candidates: list[str] = []
    if before:
        candidates.append(before)
        words = before.split()
        for n in range(min(4, len(words)), 0, -1):
            candidates.append(" ".join(words[-n:]))

    for cand in candidates:
        name = clean_text(cand).lstrip("@").rstrip(".")
        if name and not looks_like_rating(name) and is_valid_reviewer_name(name):
            return name
    return ""


def parse_rating_after_country(text: str) -> float:
    """Rating sits after country in Fiverr review card chrome."""
    raw = clean_text(text)
    m = COUNTRY_IN_TEXT.search(raw)
    if m:
        tail = raw[m.end() : m.end() + 40]
        rm = re.search(r"^\s*([1-5](?:\.\d)?)\b", tail)
        if rm:
            v = float(rm.group(1))
            if 1 <= v <= 5:
                return v
    m = re.search(r"\b([1-5](?:\.\d)?)\b(?=.*\b(?:stars?|rating)\b)", raw, re.I)
    if m:
        v = float(m.group(1))
        if 1 <= v <= 5:
            return v
    return 5.0


def resolve_reviewer_name(review: dict, gig: dict) -> str:
    seller = username_from_gig_url(gig.get("gigUrl", "")) or clean_text(
        gig.get("sellerUsername") or ""
    )
    card_text = clean_text(review.get("cardText") or review.get("reviewText") or "")

    from_country = reviewer_name_before_country(card_text)
    if from_country and not _name_is_seller(from_country, seller):
        return from_country

    raw = clean_text(review.get("reviewerName", "")).lstrip("@")
    if raw and not looks_like_rating(raw) and is_valid_reviewer_name(raw):
        if not _name_is_seller(raw, seller):
            return raw

    inferred = infer_reviewer_from_text(review.get("reviewText", ""), seller)
    if inferred:
        return inferred
    return ""


def seller_name_from_gig(gig: dict) -> str:
    """Canonical seller id — always from gig URL path, never page brand 'Fiverr'."""
    url = clean_text(gig.get("gigUrl") or gig.get("gigLink") or "")
    slug = username_from_gig_url(url)
    if slug and slug.lower() != "fiverr" and not looks_like_rating(slug):
        return slug
    return ""


def is_valid_reviewer_name(name: str) -> bool:
    n = clean_text(name).lstrip("@")
    if len(n) < 2 or len(n) > 60:
        return False
    if BAD_REVIEWER_NAMES.match(n):
        return False
    if looks_like_rating(n):
        return False
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9_'. -]{1,59}$", n):
        return False
    words = n.split()
    return 1 <= len(words) <= 4


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

    seller_name = seller_name_from_gig(gig)
    if not seller_name:
        return False

    title = clean_text(gig.get("gigTitle"))
    if len(title) < 3:
        return False

    reviewer = clean_text(review.get("reviewerName", "")).lstrip("@")
    if looks_like_rating(reviewer) or not is_valid_reviewer_name(reviewer):
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
