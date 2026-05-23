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
    get_job,
    push_error,
    refresh_job_counters,
    save_lead_if_qualified,
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
    }


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

    for review in reviews:
        if total >= max_leads:
            break
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


async def process_gig_list(job: dict, job_id: str, state: dict) -> str:
    queue = state["gig_queue"]
    start = state["resume_index"]
    max_leads = job.get("maxTotalLeads") or 100
    delay = job.get("delaySeconds") or 1
    max_reviews = job.get("maxReviewsPerGig")
    if max_reviews is None:
        max_reviews = 0

    page = await get_work_page()
    for i in range(start, len(queue)):
            current = get_job(job_id)
            if current and current.get("status") == "stopped":
                return "stopped"
            if state["us_leads"] + state["canada_leads"] >= max_leads:
                break

            gig_url = queue[i]
            append_activity(
                job_id,
                f"Gig {i + 1}/{len(queue)} — extracting all US/CA reviews with images",
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
                )

                append_activity(
                    job_id,
                    f"Gig {i + 1}/{len(queue)} done · seller={seller_label} · {len(reviews)} leads "
                    f"({checked} reviews scanned)",
                )

                state["gigs_scanned"] += 1
                state["reviews_checked"] += checked
                await _save_reviews(job, job_id, gig, reviews, state)
                state["resume_index"] = i + 1
                refresh_job_counters(job_id, state)

            except VerificationRequiredError:
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
                    return await process_gig_list(job, job_id, state)
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
                err_msg = str(err).encode("ascii", errors="replace").decode("ascii")
                artifacts = await _save_failure_artifacts(page, job_id, gig_url)
                artifact_msg = f" {artifacts}" if artifacts else ""
                push_error(job_id, f"{gig_url}: {err_msg}{artifact_msg}")
                append_activity(job_id, f"Selector failure artifacts saved:{artifact_msg}" if artifact_msg else "Selector failure artifact save skipped")
                refresh_job_counters(job_id, state)

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
    await release_work_page_after_job()
    return "completed"


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
            update_job(job_id, {"currentSearchPage": 0, "discoveryPagesScanned": 0})
            urls, source = await discover_gig_urls(niche, max_gigs, job_id)
            queue = urls
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

        state["gig_queue"] = queue
        state["resume_index"] = job.get("resumeIndex") or 0
        append_activity(job_id, "Extracting reviews from gig pages")
        await process_gig_list(job, job_id, state)

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
