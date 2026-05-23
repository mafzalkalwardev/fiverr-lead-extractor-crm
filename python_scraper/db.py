from datetime import timedelta
import re
from typing import Optional
from urllib.parse import urlparse

from bson import ObjectId
from pymongo import MongoClient, ReturnDocument
from pymongo.collection import Collection

import config  # noqa: E402 — used for STALE_RUNNING_MINUTES
from utils import (
    activity_line,
    build_dedupe_key,
    clean_text,
    is_target_country,
    is_valid_real_lead,
    looks_like_rating,
    normalize_country,
    normalize_fiverr_url,
    now_utc,
    resolve_reviewer_name,
    seller_name_from_gig,
)

_client: Optional[MongoClient] = None


def _db_name() -> str:
    path = urlparse(config.MONGODB_URI).path.strip("/")
    return path or "fiverr-lead-extractor-crm"


def get_client() -> MongoClient:
    global _client
    if _client is None:
        _client = MongoClient(config.MONGODB_URI, serverSelectionTimeoutMS=5000)
    return _client


def get_db():
    return get_client()[_db_name()]


def jobs_col() -> Collection:
    return get_db()[config.JOBS_COLLECTION]


def leads_col() -> Collection:
    return get_db()[config.LEADS_COLLECTION]


def heartbeat_col() -> Collection:
    return get_db()[config.HEARTBEAT_COLLECTION]


def failed_urls_col() -> Collection:
    return get_db()["failedurls"]


def reset_stale_running_jobs() -> int:
    """Jobs left 'running' after a crash are reset to pending."""
    cutoff = now_utc() - timedelta(minutes=config.STALE_RUNNING_MINUTES)
    result = jobs_col().update_many(
        {"status": "running", "updatedAt": {"$lt": cutoff}},
        {"$set": {"status": "pending", "updatedAt": now_utc()}},
    )
    if result.modified_count:
        print(f"[db] Reset {result.modified_count} stale running job(s) to pending")
    return result.modified_count


def set_heartbeat() -> None:
    heartbeat_col().update_one(
        {"_id": config.HEARTBEAT_ID},
        {"$set": {"ts": now_utc(), "service": "python_scraper"}},
        upsert=True,
    )


def claim_next_job() -> Optional[dict]:
    """Claim new/retry jobs only. verification_required resumes in-process via wait loop."""
    return jobs_col().find_one_and_update(
        {"status": "pending"},
        {
            "$set": {
                "status": "running",
                "verificationMessage": "",
                "updatedAt": now_utc(),
            }
        },
        sort=[("createdAt", 1)],
        return_document=ReturnDocument.AFTER,
    )


def get_job(job_id: str) -> Optional[dict]:
    return jobs_col().find_one({"_id": ObjectId(job_id)})


def append_activity(job_id: str, message: str) -> None:
    line = activity_line(message)
    jobs_col().update_one(
        {"_id": ObjectId(job_id)},
        {"$push": {"activityLog": line}},
    )
    print(f"[job {job_id}] {message}")


def update_job(job_id: str, fields: dict) -> None:
    fields["updatedAt"] = now_utc()
    jobs_col().update_one({"_id": ObjectId(job_id)}, {"$set": fields})


def push_error(job_id: str, message: str) -> None:
    jobs_col().update_one(
        {"_id": ObjectId(job_id)},
        {"$push": {"errorLog": message}},
    )


def record_failed_url(job_id: str, url: str, reason: str) -> None:
    failed_urls_col().update_one(
        {"jobId": ObjectId(job_id), "url": url},
        {
            "$set": {
                "reason": reason,
                "updatedAt": now_utc(),
            },
            "$setOnInsert": {
                "jobId": ObjectId(job_id),
                "url": url,
                "retryCount": 0,
                "createdAt": now_utc(),
            },
        },
        upsert=True,
    )


def mark_failed_url_retry(job_id: str, url: str) -> None:
    failed_urls_col().update_one(
        {"jobId": ObjectId(job_id), "url": url},
        {"$inc": {"retryCount": 1}, "$set": {"updatedAt": now_utc()}},
        upsert=False,
    )


def clear_failed_url(job_id: str, url: str) -> None:
    failed_urls_col().delete_one({"jobId": ObjectId(job_id), "url": url})


def _niche_regex(niche: str) -> re.Pattern:
    compact = r"\s+".join(re.escape(part) for part in clean_text(niche).split())
    return re.compile(rf"^\s*{compact}\s*$", re.I)


def previous_gig_urls_for_niche(job: dict, niche: str, current_job_id: str) -> set[str]:
    """URLs already queued for earlier jobs with the same user + niche."""
    user_id = job.get("userId")
    if not user_id or not niche:
        return set()

    query = {
        "_id": {"$ne": ObjectId(current_job_id)},
        "userId": user_id,
        "niche": _niche_regex(niche),
    }
    projection = {"gigQueue": 1, "manualGigUrls": 1}
    seen: set[str] = set()
    for doc in jobs_col().find(query, projection):
        for key in ("gigQueue", "manualGigUrls"):
            for url in doc.get(key) or []:
                norm = normalize_fiverr_url(url) or url
                if norm:
                    seen.add(norm)
    return seen


def save_lead_if_qualified(job: dict, gig: dict, review: dict) -> tuple[bool, str, str]:
    country = normalize_country(review.get("reviewerCountry", ""))
    targets = job.get("targetCountries") or config.DEFAULT_TARGET_COUNTRIES
    image_mode = job.get("reviewImageMode") or "with_image"

    if not country:
        return False, country, "missing_country"
    if country not in ("United States", "Canada"):
        return False, country, "non_target_country"
    if not is_target_country(country, targets):
        return False, country, "non_target_country"
    if image_mode == "with_image" and not clean_text(review.get("reviewedImageLink")):
        return False, country, "missing_review_image"
    if image_mode == "without_image":
        review = {**review, "reviewedImageLink": ""}
    reviewer_resolved = resolve_reviewer_name(review, gig)
    if not reviewer_resolved:
        return False, country, "invalid_real_lead"
    review = {**review, "reviewerName": reviewer_resolved}

    if not is_valid_real_lead(gig, review):
        return False, country, "invalid_real_lead"

    seller_username = seller_name_from_gig(gig)
    if not seller_username:
        return False, country, "invalid_seller"
    seller_name = (
        gig.get("sellerDisplayName")
        or gig.get("sellerName")
        or seller_username
    )
    seller_name = str(seller_name).strip()
    if not seller_name or seller_name.lower() == "fiverr" or looks_like_rating(seller_name):
        seller_name = seller_username
    dedupe_key = build_dedupe_key(
        gig["gigUrl"],
        review["reviewerName"],
        review["reviewText"],
    )

    doc = {
        "jobId": job["_id"],
        "userId": job["userId"],
        "sellerName": seller_name,
        "sellerUsername": seller_username,
        "gigLink": gig["gigUrl"].strip(),
        "gigTitle": gig.get("gigTitle", "").strip(),
        "reviewerName": review["reviewerName"].strip(),
        "country": country,
        "review": review["reviewText"].strip(),
        "reviewRating": review.get("reviewRating", 0),
        "reviewDate": review.get("reviewDate"),
        "reviewedImageLink": (review.get("reviewedImageLink") or "").strip(),
        "mainGigImage": (gig.get("mainGigImage") or "").strip(),
        "serviceNiche": job.get("niche", ""),
        "scrapedAt": now_utc(),
        "dedupeKey": dedupe_key,
    }

    try:
        leads_col().insert_one(doc)
        return True, country, "saved"
    except Exception as e:
        if getattr(e, "code", None) == 11000:
            return False, country, "duplicate"
        raise


def refresh_job_counters(job_id: str, state: dict) -> None:
    total = state["us_leads"] + state["canada_leads"]
    queue_len = max(len(state.get("gig_queue") or []), 1)
    idx = state.get("resume_index", 0)
    update_job(
        job_id,
        {
            "gigsScanned": state["gigs_scanned"],
            "reviewsChecked": state["reviews_checked"],
            "usLeadsFound": state["us_leads"],
            "canadaLeadsFound": state["canada_leads"],
            "totalLeadsFound": total,
            "failedGigs": state["failed_gigs"],
            "resumeIndex": idx,
            "totalReviewsParsed": state["reviews_checked"],
            "progressPercent": int((idx / queue_len) * 100),
        },
    )
