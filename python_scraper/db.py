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
    """
    Jobs left mid-flight after a crash/scraper restart are reset to pending.
    verification_required uses a longer cutoff so a live wait loop is not stolen.
    """
    now = now_utc()
    cutoff = now - timedelta(minutes=config.STALE_RUNNING_MINUTES)
    verif_cutoff = now - timedelta(
        minutes=max(config.STALE_RUNNING_MINUTES + 2, config.VERIFICATION_TIMEOUT_SEC // 60 + 1)
    )
    total = 0
    r1 = jobs_col().update_many(
        {
            "status": {"$in": ["running", "extracting_reviews", "discovering"]},
            "updatedAt": {"$lt": cutoff},
        },
        {
            "$set": {
                "status": "pending",
                "verificationMessage": "",
                "updatedAt": now,
            }
        },
    )
    total += r1.modified_count
    r2 = jobs_col().update_many(
        {
            "status": "verification_required",
            "updatedAt": {"$lt": verif_cutoff},
        },
        {
            "$set": {
                "status": "pending",
                "verificationMessage": "",
                "updatedAt": now,
            }
        },
    )
    total += r2.modified_count
    if total:
        print(f"[db] Reset {total} stale in-progress job(s) to pending")
    return total


_last_heartbeat_mono: float = 0.0


def set_heartbeat(*, force: bool = False) -> None:
    """
    Touch the Python scraper heartbeat. Throttled to ~once per 15s unless force=True
    so hot paths (live scan pushes) can call it freely without hammering Mongo.
    """
    global _last_heartbeat_mono
    import time as _time

    now = _time.monotonic()
    if not force and _last_heartbeat_mono and (now - _last_heartbeat_mono) < 15.0:
        return
    _last_heartbeat_mono = now
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


def lead_keys_for_gig(job_id: str, gig_url: str) -> tuple[set[str], set[str]]:
    """
    Reviewer|text keys already saved for this job+gig — used to resume after
    verification without treating the gig as brand new.
    """
    seen_keys: set[str] = set()
    seen_text: set[str] = set()
    target = normalize_fiverr_url(gig_url) or clean_text(gig_url)
    if not target:
        return seen_keys, seen_text
    try:
        oid = ObjectId(job_id)
    except Exception:
        return seen_keys, seen_text
    for doc in leads_col().find(
        {"jobId": oid},
        {"reviewerName": 1, "review": 1, "gigLink": 1},
    ):
        link = normalize_fiverr_url(doc.get("gigLink") or "") or clean_text(
            doc.get("gigLink") or ""
        )
        if link.rstrip("/").lower() != target.rstrip("/").lower():
            continue
        reviewer = clean_text(doc.get("reviewerName") or "").lower()
        text = clean_text(doc.get("review") or "")
        if reviewer and text:
            seen_keys.add(f"{reviewer}|{text[:100].lower()}")
            seen_text.add(text[:140].lower())
    return seen_keys, seen_text


def save_gig_review_checkpoint(
    job_id: str,
    *,
    gig_url: str,
    checked: int,
    review_page: int,
    load_clicks: int,
    processed_fps: set[str] | None = None,
    progress_base: int = 0,
) -> None:
    """
    Persist mid-gig resume state. `checked` is gig-local; Live Monitor totals use
    progress_base + checked so multi-gig jobs do not lose earlier scan counts.
    """
    fps = list(processed_fps or ())
    # Cap size so the job document stays light
    if len(fps) > 4000:
        fps = fps[-4000:]
    gig_local = max(0, int(checked))
    display = max(0, int(progress_base)) + gig_local
    update_job(
        job_id,
        {
            "gigReviewCheckpoint": {
                "gigUrl": (normalize_fiverr_url(gig_url) or gig_url or "").strip(),
                "checked": gig_local,
                "reviewPage": max(1, int(review_page)),
                "loadClicks": max(0, int(load_clicks)),
                "processedFps": fps,
            },
            "reviewsChecked": display,
            "totalReviewsParsed": display,
            "currentReviewPage": max(1, int(review_page)),
        },
    )


def append_activity(job_id: str, message: str) -> None:
    line = activity_line(message)
    jobs_col().update_one(
        {"_id": ObjectId(job_id)},
        # Keep enough history for the Live Monitor (UI shows the tail)
        {"$push": {"activityLog": {"$each": [line], "$slice": -200}}},
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
    """URLs already queued or scraped for earlier jobs with the same user + niche."""
    user_id = job.get("userId")
    if not user_id or not niche:
        return set()

    niche_match = _niche_regex(niche)
    query = {
        "_id": {"$ne": ObjectId(current_job_id)},
        "userId": user_id,
        "$or": [
            {"niche": niche_match},
            {"keyword": niche_match},
            {"category": niche_match},
        ],
    }
    projection = {
        "gigQueue": 1,
        "manualGigUrls": 1,
        "resumeIndex": 1,
        "status": 1,
    }
    seen: set[str] = set()
    for doc in jobs_col().find(query, projection):
        queue = list(doc.get("gigQueue") or doc.get("manualGigUrls") or [])
        if not queue:
            continue
        resume_idx = int(doc.get("resumeIndex") or 0)
        status = doc.get("status") or ""
        # Only exclude gigs actually processed — not the full saved queue on partial jobs.
        if status == "completed" and resume_idx >= len(queue):
            processed = queue
        else:
            processed = queue[: max(0, min(resume_idx, len(queue)))]
        for url in processed:
            norm = normalize_fiverr_url(url) or url
            if norm:
                seen.add(norm)

    # Do NOT exclude gigs just because some leads already exist for them.
    # A gig may still have more US/CA reviews after a lead-limit pause.
    # Review-level dedupe (userId + dedupeKey) prevents duplicate leads.

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

    existing = leads_col().find_one(
        {"userId": job["userId"], "dedupeKey": dedupe_key},
    )
    if existing:
        # Paste-links "scrape fresh / ignore already-reviewed": always attach to
        # this job and count as saved (even if the row already belonged here).
        if job.get("reextractFromStart"):
            leads_col().update_one(
                {"_id": existing["_id"]},
                {
                    "$set": {
                        "jobId": job["_id"],
                        "sellerName": doc["sellerName"],
                        "sellerUsername": doc["sellerUsername"],
                        "gigLink": doc["gigLink"],
                        "gigTitle": doc["gigTitle"],
                        "reviewerName": doc["reviewerName"],
                        "country": doc["country"],
                        "review": doc["review"],
                        "reviewRating": doc["reviewRating"],
                        "reviewDate": doc["reviewDate"],
                        "reviewedImageLink": doc["reviewedImageLink"],
                        "mainGigImage": doc["mainGigImage"],
                        "serviceNiche": doc["serviceNiche"],
                        "scrapedAt": doc["scrapedAt"],
                    }
                },
            )
            return True, country, "saved"
        # Cross-job dedupe — resume/continue must not create duplicate rows
        return False, country, "duplicate"

    try:
        leads_col().insert_one(doc)
        return True, country, "saved"
    except Exception as e:
        if getattr(e, "code", None) == 11000:
            return False, country, "duplicate"
        raise


def refresh_job_counters(
    job_id: str,
    state: dict,
    *,
    reviews_parsed: int | None = None,
) -> None:
    """
    Push lead / progress counters to Mongo for the Live Monitor.

    Do NOT overwrite totalReviewsParsed with a stale pre-gig reviews_checked —
    that was resetting the UI to 0 while extraction was actively scanning.
    """
    total = state["us_leads"] + state["canada_leads"]
    queue_len = max(len(state.get("gig_queue") or []), 1)
    idx = state.get("resume_index", 0)
    fields: dict = {
        "gigsScanned": state["gigs_scanned"],
        "usLeadsFound": state["us_leads"],
        "canadaLeadsFound": state["canada_leads"],
        "totalLeadsFound": total,
        "failedGigs": state["failed_gigs"],
        "resumeIndex": idx,
        "progressPercent": int((idx / queue_len) * 100),
    }
    if reviews_parsed is not None:
        parsed = max(0, int(reviews_parsed))
        fields["totalReviewsParsed"] = parsed
        fields["reviewsChecked"] = max(int(state.get("reviews_checked") or 0), parsed)
    # else: lead-only refresh — do NOT touch reviewsChecked / totalReviewsParsed
    # (extract_reviews owns those live fields mid-gig)
    update_job(job_id, fields)
