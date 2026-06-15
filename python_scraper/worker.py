import asyncio
import re
from pathlib import Path

import config
from browser import (
    get_work_page,
    is_browser_closed_error,
    release_work_page_after_job,
    reset_browser,
)
from db import (
    append_activity,
    clear_failed_url,
    get_job,
    mark_failed_url_retry,
    previous_gig_urls_for_niche,
    push_error,
    record_failed_url,
    refresh_job_counters,
    save_lead_if_qualified,
    set_heartbeat,
    update_job,
)
from discovery import discover_gig_urls
from gig_parser import extract_gig_metadata, open_gig_page
from page_data import enrich_gig_from_page_json
from review_parser import extract_reviews
from utils import (
    count_lead_bucket,
    normalize_fiverr_url,
    parse_rating_after_country,
    reviewer_name_before_country,
)
from verification import BlockedError, VerificationRequiredError, wait_until_verification_clears


def _initial_state(job: dict) -> dict:
    return {
        "gigs_scanned": job.get("gigsScanned") or 0,
        "reviews_checked": job.get("reviewsChecked") or 0,
        "us_leads": job.get("usLeadsFound") or 0,
        "canada_leads": job.get("canadaLeadsFound") or 0,
        "failed_gigs": job.get("failedGigs") or 0,
        "gig_queue": list(job.get("gigQueue") or []),
        "resume_index": job.get("resumeIndex") or 0,
        "failed_urls": [],
    }


def _review_image_mode(job: dict) -> str:
    mode = job.get("reviewImageMode") or "with_image"
    return "without_image" if mode == "without_image" else "with_image"


def _review_image_mode_label(job: dict) -> str:
    return (
        "without review image links"
        if _review_image_mode(job) == "without_image"
        else "with review image links"
    )


def _sync_counters_from_db(job_id: str, state: dict) -> dict:
    """Reload lead totals and limits so Continue works after maxTotalLeads is raised."""
    current = get_job(job_id) or {}
    state["us_leads"] = int(current.get("usLeadsFound") or state.get("us_leads") or 0)
    state["canada_leads"] = int(current.get("canadaLeadsFound") or state.get("canada_leads") or 0)
    state["gigs_scanned"] = int(current.get("gigsScanned") or state.get("gigs_scanned") or 0)
    state["reviews_checked"] = int(current.get("reviewsChecked") or state.get("reviews_checked") or 0)
    state["failed_gigs"] = int(current.get("failedGigs") or state.get("failed_gigs") or 0)
    state["resume_index"] = int(current.get("resumeIndex") or state.get("resume_index") or 0)
    queue = list(current.get("gigQueue") or state.get("gig_queue") or [])
    if queue:
        state["gig_queue"] = queue
    return current


async def _save_failure_artifacts(page, job_id: str, gig_url: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "-", gig_url.strip())[:80] or "gig"
    out_dir = Path("test-results")
    out_dir.mkdir(parents=True, exist_ok=True)
    base = out_dir / f"failed-{job_id}-{safe}"
    screenshot = base.with_suffix(".png")
    html = base.with_suffix(".html")
    try:
        await page.screenshot(path=str(screenshot), full_page=True)
    except Exception:
        screenshot = None
    try:
        content = await page.content()
        html.write_text(content, encoding="utf-8", errors="ignore")
    except Exception:
        html = None
    parts = []
    if screenshot:
        parts.append(f"screenshot={screenshot}")
    if html:
        parts.append(f"html={html}")
    return " ".join(parts)


async def process_html_import(job: dict, job_id: str, state: dict) -> str:
    files = job.get("htmlFiles") or []
    if not files:
        push_error(job_id, "No HTML files uploaded")
        update_job(job_id, {"status": "failed"})
        return "failed"

    from bs4 import BeautifulSoup

    update_job(job_id, {"status": "extracting_reviews"})
    start = state["resume_index"]

    for i in range(start, len(files)):
        current = get_job(job_id)
        if current and current.get("status") == "stopped":
            return "stopped"

        f = files[i]
        path = Path(f.get("storedPath", ""))
        if not path.exists():
            state["failed_gigs"] += 1
            push_error(job_id, f"{f.get('filename')}: file not found")
            continue

        html = path.read_text(encoding="utf-8", errors="ignore")
        source_url = f.get("gigUrl") or f"https://www.fiverr.com/imported/{i + 1}"
        append_activity(job_id, f"Parsing HTML: {f.get('filename')}")
        update_job(
            job_id,
            {
                "currentGigLink": source_url,
                "currentGigNumber": i + 1,
                "totalGigs": len(files),
                "resumeIndex": i,
                "progressPercent": int((i / max(len(files), 1)) * 100),
            },
        )

        try:
            soup = BeautifulSoup(html, "html.parser")
            title = ""
            h1 = soup.find("h1")
            if h1:
                title = h1.get_text(" ", strip=True)
            og = soup.find("meta", property="og:title")
            if og and og.get("content"):
                title = title or og["content"]

            seller = ""
            for a in soup.select('a[href*="/"]')[:50]:
                href = a.get("href", "")
                user = href.strip("/").split("/")[0] if href else ""
                text = a.get_text(" ", strip=True)
                if user and text and len(text) < 80:
                    seller = text
                    break

            gig = {
                "gigUrl": normalize_fiverr_url(source_url) or source_url,
                "gigTitle": title,
                "sellerName": seller,
                "sellerUsername": seller,
                "mainGigImage": "",
            }
            state["gigs_scanned"] += 1
            # HTML import: minimal review extraction from page text blocks
            reviews = []
            for block in soup.select('[class*="review" i], article, li')[:40]:
                text = block.get_text(" ", strip=True)
                if len(text) < 40:
                    continue
                country = ""
                if re.search(r"united states|usa", text, re.I):
                    country = "United States"
                elif re.search(r"\bcanada\b", text, re.I):
                    country = "Canada"
                if not country:
                    continue
                reviewer = reviewer_name_before_country(text)
                if not reviewer:
                    continue
                reviews.append(
                    {
                        "reviewerName": reviewer,
                        "reviewerCountry": country,
                        "reviewText": text[:500],
                        "reviewRating": parse_rating_after_country(text),
                        "reviewDate": None,
                        "reviewedImageLink": "",
                    }
                )

            state["reviews_checked"] += len(reviews)
            await _save_reviews(job, job_id, gig, reviews, state)
            state["resume_index"] = i + 1
            refresh_job_counters(job_id, state)
        except Exception as err:
            state["failed_gigs"] += 1
            push_error(job_id, f"{f.get('filename')}: {err}")

    update_job(
        job_id,
        {
            "status": "completed",
            "progressPercent": 100,
            "currentGigLink": "",
            "currentSeller": "",
            "currentSellerUsername": "",
        },
    )
    append_activity(job_id, f"Completed · {state['us_leads'] + state['canada_leads']} leads")
    return "completed"


async def _save_reviews(job: dict, job_id: str, gig: dict, reviews: list[dict], state: dict) -> None:
    max_leads = job.get("maxTotalLeads") or 100
    total = state["us_leads"] + state["canada_leads"]
    image_mode = _review_image_mode(job)

    for review in reviews:
        if total >= max_leads:
            break
        if image_mode == "without_image":
            review = {**review, "reviewedImageLink": ""}
        saved, country, reason = save_lead_if_qualified(job, gig, review)
        if saved:
            bucket = count_lead_bucket(country)
            if bucket == "us":
                state["us_leads"] += 1
            elif bucket == "canada":
                state["canada_leads"] += 1
            total += 1
            rn = review.get("reviewerName", "")
            append_activity(job_id, f"Lead saved: {rn} ({country})")
        elif reason == "duplicate":
            append_activity(
                job_id,
                f"Duplicate skipped: {review.get('reviewerName', '')} ({country})",
            )
        else:
            append_activity(
                job_id,
                f"Review skipped: {review.get('reviewerName', '') or 'missing reviewer'} "
                f"({country or 'missing country'}) reason={reason}",
            )


async def process_gig_list(job: dict, job_id: str, state: dict, retry_pass: int = 0) -> str:
    queue = state["gig_queue"]
    start = state["resume_index"]
    delay = job.get("delaySeconds") or 1
    max_reviews = job.get("maxReviewsPerGig")
    if max_reviews is None:
        max_reviews = 0
    image_mode = _review_image_mode(job)
    image_label = _review_image_mode_label(job)
    stopped_reason = None

    page = await get_work_page()
    for i in range(start, len(queue)):
            try:
                set_heartbeat()
            except Exception:
                pass
            current = _sync_counters_from_db(job_id, state)
            queue = state["gig_queue"]
            max_leads = int(current.get("maxTotalLeads") or job.get("maxTotalLeads") or 100)
            if current.get("status") == "stopped":
                return "stopped"
            if state["us_leads"] + state["canada_leads"] >= max_leads:
                stopped_reason = "lead_limit"
                append_activity(
                    job_id,
                    f"Lead limit reached ({max_leads}). Pausing at gig {i + 1}/{len(queue)} "
                    f"with {len(queue) - i} gig(s) remaining.",
                )
                break

            gig_url = queue[i]
            attempt_note = "retry " if retry_pass > 0 else ""
            append_activity(
                job_id,
                f"Gig {i + 1}/{len(queue)} {attempt_note}— extracting US/CA reviews {image_label}",
            )
            update_job(
                job_id,
                {
                    "status": "extracting_reviews",
                    "currentGigLink": gig_url,
                    "currentGigNumber": i + 1,
                    "totalGigs": len(queue),
                    "currentReviewPage": 0,
                    "resumeIndex": i,
                    "gigQueue": queue,
                    "progressPercent": int((i / max(len(queue), 1)) * 100),
                },
            )

            try:
                if delay > 0:
                    await asyncio.sleep(delay)
                final_url = await open_gig_page(page, gig_url, job_id)
                gig = await extract_gig_metadata(page, final_url, job_id)
                gig = await enrich_gig_from_page_json(page, gig)
                seller_label = (
                    gig.get("sellerDisplayName")
                    or gig.get("sellerName")
                    or gig.get("sellerUsername")
                    or ""
                )
                seller_username = gig.get("sellerUsername") or ""
                update_job(
                    job_id,
                    {
                        "currentSeller": seller_label,
                        "currentSellerUsername": seller_username,
                        "currentGigLink": gig.get("gigUrl") or final_url,
                    },
                )
                append_activity(
                    job_id,
                    f"Seller extracted: name={seller_label} username={seller_username}",
                )
                reviews, checked = await extract_reviews(
                    page,
                    max_reviews,
                    job_id,
                    seller_username,
                    progress_base=state["reviews_checked"],
                    review_image_mode=image_mode,
                    main_gig_image=gig.get("mainGigImage") or "",
                )

                state["gigs_scanned"] += 1
                state["reviews_checked"] += checked
                leads_before = state["us_leads"] + state["canada_leads"]
                await _save_reviews(job, job_id, gig, reviews, state)
                leads_after = state["us_leads"] + state["canada_leads"]
                append_activity(
                    job_id,
                    f"Gig {i + 1}/{len(queue)} done: seller={seller_label}; "
                    f"{len(reviews)} qualified reviews; {checked} reviews scanned",
                )
                append_activity(job_id, f"Leads saved for gig: {leads_after - leads_before}")
                clear_failed_url(job_id, gig_url)
                state["resume_index"] = i + 1
                refresh_job_counters(job_id, state)

            except VerificationRequiredError as err:
                if getattr(err, "timed_out", False):
                    state["failed_gigs"] += 1
                    err_msg = str(err).encode("ascii", errors="replace").decode("ascii")
                    artifacts = await _save_failure_artifacts(page, job_id, gig_url)
                    artifact_msg = f" {artifacts}" if artifacts else ""
                    reason = f"{err_msg}{artifact_msg}"
                    push_error(job_id, f"{gig_url}: {reason}")
                    record_failed_url(job_id, gig_url, reason)
                    state.setdefault("failed_urls", []).append(gig_url)
                    append_activity(
                        job_id,
                        f"Verification timed out for gig; saved artifacts and continuing: {gig_url}",
                    )
                    update_job(
                        job_id,
                        {
                            "status": "extracting_reviews",
                            "verificationMessage": "",
                            "resumeIndex": i + 1,
                            "gigQueue": queue,
                        },
                    )
                    state["resume_index"] = i + 1
                    refresh_job_counters(job_id, state)
                    continue

                update_job(
                    job_id,
                    {
                        "status": "verification_required",
                        "verificationMessage": config.VERIFICATION_MESSAGE,
                        "resumeIndex": i,
                        "gigQueue": queue,
                    },
                )
                cleared = await wait_until_verification_clears(page, job_id, gig_url)
                if cleared:
                    state["resume_index"] = i
                    return await process_gig_list(job, job_id, state, retry_pass)
                return "verification_required"

            except BlockedError as err:
                push_error(job_id, str(err))
                update_job(job_id, {"status": "blocked", "currentGigLink": gig_url})
                return "blocked"

            except Exception as err:
                if is_browser_closed_error(err):
                    await reset_browser()
                    update_job(
                        job_id,
                        {
                            "status": "verification_required",
                            "verificationMessage": config.VERIFICATION_MESSAGE,
                            "resumeIndex": i,
                        },
                    )
                    append_activity(job_id, "Browser closed — reopening on next poll. Keep Chrome open.")
                    return "verification_required"
                state["failed_gigs"] += 1
                err_str = str(err)
                if "timeout" in err_str.lower() and ("60s" in err_str or "page.goto" in err_str or "TimeoutError" in type(err).__name__):
                    err_msg = f"Gig page load timed out (network too slow); saved for retry"
                else:
                    err_msg = err_str.encode("ascii", errors="replace").decode("ascii")
                artifacts = await _save_failure_artifacts(page, job_id, gig_url)
                artifact_msg = f" {artifacts}" if artifacts else ""
                push_error(job_id, f"{gig_url}: {err_msg}{artifact_msg}")
                record_failed_url(job_id, gig_url, f"{err_msg}{artifact_msg}")
                state.setdefault("failed_urls", []).append(gig_url)
                append_activity(
                    job_id,
                    f"Failed gig saved for retry: {gig_url} reason={err_msg}",
                )
                append_activity(job_id, f"Selector failure artifacts saved:{artifact_msg}" if artifact_msg else "Selector failure artifact save skipped")
                refresh_job_counters(job_id, state)

    failed_urls = list(dict.fromkeys(state.get("failed_urls") or []))
    if (
        stopped_reason != "lead_limit"
        and failed_urls
        and retry_pass < config.MAX_FAILED_URL_RETRY_PASSES
    ):
        append_activity(
            job_id,
            f"Retrying {len(failed_urls)} failed gig(s) once before completing",
        )
        for failed_url in failed_urls:
            mark_failed_url_retry(job_id, failed_url)
        original_queue = list(queue)
        original_resume = max(state.get("resume_index") or 0, len(original_queue))
        state["gig_queue"] = failed_urls
        state["resume_index"] = 0
        state["failed_urls"] = []
        update_job(
            job_id,
            {
                "gigQueue": failed_urls,
                "resumeIndex": 0,
                "totalGigs": len(failed_urls),
            },
        )
        outcome = await process_gig_list(job, job_id, state, retry_pass + 1)
        if outcome in ("completed", "lead_limit_reached"):
            state["gig_queue"] = original_queue
            state["resume_index"] = original_resume
            update_job(
                job_id,
                {
                    "gigQueue": original_queue,
                    "resumeIndex": original_resume,
                    "totalGigs": len(original_queue),
                },
            )
        return outcome

    queue = state["gig_queue"]
    resume_idx = state.get("resume_index", 0)
    remaining = max(0, len(queue) - resume_idx)
    total_leads = state["us_leads"] + state["canada_leads"]
    current = get_job(job_id) or job
    max_leads = int(current.get("maxTotalLeads") or job.get("maxTotalLeads") or 100)

    if stopped_reason == "lead_limit" and remaining > 0:
        update_job(
            job_id,
            {
                "status": "lead_limit_reached",
                "progressPercent": int((resume_idx / max(len(queue), 1)) * 100),
                "currentGigLink": "",
                "currentSeller": "",
                "currentSellerUsername": "",
                "gigQueue": queue,
                "resumeIndex": resume_idx,
                "totalGigs": len(queue),
                "totalLeadsFound": total_leads,
            },
        )
        append_activity(
            job_id,
            f"Paused at lead limit ({total_leads}/{max_leads}). "
            f"{remaining} gig(s) left — raise max leads and click Continue.",
        )
        await release_work_page_after_job()
        return "lead_limit_reached"

    update_job(
        job_id,
        {
            "status": "completed",
            "progressPercent": 100,
            "currentGigLink": "",
            "currentSeller": "",
            "currentSellerUsername": "",
            "gigQueue": queue,
            "resumeIndex": resume_idx,
            "totalGigs": len(queue),
        },
    )
    append_activity(job_id, f"Completed · {total_leads} leads")
    await release_work_page_after_job()
    return "completed"


async def _maybe_append_discovery(
    job: dict, job_id: str, niche: str, state: dict, outcome: str
) -> str:
    """After a continued queue finishes, optionally discover and process new gigs."""
    if outcome != "completed":
        return outcome
    if not job.get("appendDiscoveryAfterQueue"):
        return outcome

    current = get_job(job_id) or job
    if not current.get("appendDiscoveryAfterQueue"):
        return outcome

    update_job(job_id, {"appendDiscoveryAfterQueue": False})
    existing_queue = list(state.get("gig_queue") or current.get("gigQueue") or [])
    processed_count = len(existing_queue)

    append_activity(
        job_id,
        f"Previous queue complete ({processed_count} gigs) — searching Fiverr for additional gigs",
    )
    update_job(job_id, {"status": "discovering_gigs"})

    max_gigs = current.get("maxGigs")
    if max_gigs is None:
        max_gigs = 0
    seen_before = previous_gig_urls_for_niche(current, niche, job_id)
    seen = set(seen_before)
    for url in existing_queue:
        norm = normalize_fiverr_url(url) or url
        if norm:
            seen.add(norm)

    urls, source = await discover_gig_urls(
        niche,
        max_gigs,
        job_id,
        exclude_urls=seen,
    )
    new_urls = [u for u in urls if (normalize_fiverr_url(u) or u) not in seen]

    if not new_urls:
        append_activity(job_id, "No additional gigs found on Fiverr search")
        return outcome

    merged = existing_queue + new_urls
    state["gig_queue"] = merged
    state["resume_index"] = processed_count
    update_job(
        job_id,
        {
            "discoverySource": source,
            "gigQueue": merged,
            "urlsDiscovered": len(merged),
            "totalGigs": len(merged),
            "resumeIndex": processed_count,
        },
    )
    append_activity(
        job_id,
        f"Appended {len(new_urls)} new gig(s) — continuing from gig {processed_count + 1}/{len(merged)}",
    )
    return await process_gig_list(current, job_id, state)


async def process_job(job: dict) -> None:
    job_id = str(job["_id"])
    niche = (job.get("niche") or "").strip()
    if not niche:
        update_job(job_id, {"status": "failed"})
        push_error(job_id, "Job missing niche")
        return

    mode = job.get("extractionMode") or "live"
    state = _initial_state(job)

    max_gigs_log = job.get("maxGigs")
    append_activity(
        job_id,
        f'Started · mode={mode} · niche="{niche}" · maxGigs={max_gigs_log} (0=all)',
    )
    append_activity(job_id, f"Review image option: {_review_image_mode_label(job)}")
    update_job(job_id, {"status": "running", "verificationMessage": ""})
    append_activity(job_id, "Opening Fiverr scraper browser (one window for this job)")

    try:
        if mode == "html_import":
            await process_html_import(job, job_id, state)
            return

        if mode == "manual_urls":
            urls = job.get("manualGigUrls") or job.get("gigQueue") or []
            queue = [normalize_fiverr_url(u) or u for u in urls if u]
            state["gig_queue"] = queue
            append_activity(job_id, f"Manual URLs: {len(queue)} gigs")
            update_job(
                job_id,
                {"discoverySource": "manual", "urlsDiscovered": len(queue), "gigQueue": queue},
            )
            await process_gig_list(job, job_id, state)
            return

        # Live mode
        queue = list(job.get("gigQueue") or [])
        if not queue:
            update_job(job_id, {"status": "discovering_gigs"})
            max_gigs = job.get("maxGigs")
            if max_gigs is None:
                max_gigs = 0
            if config.MAX_SEARCH_PAGES > 0:
                pages_note = f"up to {config.MAX_SEARCH_PAGES} search pages"
            else:
                pages_note = "all search pages until the last page"
            gigs_note = (
                "all gigs from search"
                if max_gigs <= 0
                else f"up to {max_gigs} gigs"
            )
            append_activity(
                job_id,
                f"Discovering gigs — {pages_note} ({gigs_note})",
            )
            seen_before = previous_gig_urls_for_niche(job, niche, job_id)
            if seen_before:
                append_activity(
                    job_id,
                    f"Keyword continuation: skipping {len(seen_before)} gig(s) already scraped or queued for this niche",
                )
            update_job(job_id, {"currentSearchPage": 0, "discoveryPagesScanned": 0})
            urls, source = await discover_gig_urls(
                niche,
                max_gigs,
                job_id,
                exclude_urls=seen_before,
            )
            queue = urls
            state["gig_queue"] = queue
            state["resume_index"] = 0
            update_job(
                job_id,
                {
                    "discoverySource": source,
                    "urlsDiscovered": len(queue),
                    "gigQueue": queue,
                    "resumeIndex": 0,
                },
            )
            append_activity(job_id, f"Discovery: {source} · {len(queue)} URLs")
            if not queue:
                update_job(
                    job_id,
                    {
                        "status": "verification_required",
                        "verificationMessage": config.VERIFICATION_MESSAGE,
                    },
                )
                push_error(job_id, "No gig URLs found — complete verification and Retry")
                return

            outcome = await process_gig_list(job, job_id, state)
            if job.get("appendDiscoveryAfterQueue"):
                await _maybe_append_discovery(job, job_id, niche, state, outcome)
            return

        state["gig_queue"] = queue
        state["resume_index"] = job.get("resumeIndex") or 0
        if job.get("continuedFromJobId"):
            append_activity(
                job_id,
                f"Loaded {len(queue)} unprocessed gig(s) continued from prior job",
            )
        if state["resume_index"] >= len(queue):
            update_job(job_id, {"status": "completed", "progressPercent": 100})
            append_activity(job_id, f"All {len(queue)} gigs already processed")
            return
        if state["resume_index"] > 0:
            append_activity(
                job_id,
                f"Resuming from gig {state['resume_index'] + 1}/{len(queue)} "
                f"({len(queue) - state['resume_index']} remaining)",
            )
        append_activity(job_id, "Extracting reviews from gig pages")
        outcome = await process_gig_list(job, job_id, state)
        if mode == "live" and job.get("appendDiscoveryAfterQueue"):
            outcome = await _maybe_append_discovery(job, job_id, niche, state, outcome)

    except Exception as err:
        if is_browser_closed_error(err):
            await reset_browser()
            update_job(
                job_id,
                {
                    "status": "verification_required",
                    "verificationMessage": config.VERIFICATION_MESSAGE,
                },
            )
            append_activity(job_id, "Browser closed — will retry when you click Retry")
            return
        msg = str(err)
        update_job(job_id, {"status": "failed"})
        push_error(job_id, msg)
        append_activity(job_id, f"Failed: {msg}")
        raise
