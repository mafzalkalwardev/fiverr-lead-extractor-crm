import asyncio
import re
from pathlib import Path

import config
from browser import is_browser_closed_error, new_page, reset_browser
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
from review_parser import extract_reviews
from utils import count_lead_bucket, normalize_fiverr_url
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
                reviews.append(
                    {
                        "reviewerName": "Imported",
                        "reviewerCountry": country,
                        "reviewText": text[:500],
                        "reviewRating": 5.0,
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
        {"status": "completed", "progressPercent": 100, "currentGigLink": "", "currentSeller": ""},
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
            append_activity(job_id, f"Lead saved: {review['reviewerName']} ({country})")


async def process_gig_list(job: dict, job_id: str, state: dict) -> str:
    queue = state["gig_queue"]
    start = state["resume_index"]
    max_leads = job.get("maxTotalLeads") or 100
    delay = job.get("delaySeconds") or 3
    max_reviews = job.get("maxReviewsPerGig") or 100

    page = await new_page()
    try:
        for i in range(start, len(queue)):
            current = get_job(job_id)
            if current and current.get("status") == "stopped":
                return "stopped"
            if state["us_leads"] + state["canada_leads"] >= max_leads:
                break

            gig_url = queue[i]
            append_activity(job_id, f"Opening gig {i + 1}/{len(queue)}")
            update_job(
                job_id,
                {
                    "status": "extracting_reviews",
                    "currentGigLink": gig_url,
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
                reviews, checked = await extract_reviews(page, max_reviews, job_id)

                update_job(job_id, {"currentSeller": gig.get("sellerName") or gig.get("sellerUsername") or ""})
                append_activity(
                    job_id,
                    f"Seller: {gig.get('sellerName')} · {len(reviews)} US/CA reviews",
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
                    try:
                        await page.close()
                    except Exception:
                        pass
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
                push_error(job_id, f"{gig_url}: {err}")
                refresh_job_counters(job_id, state)
    finally:
        try:
            if not page.is_closed():
                await page.close()
        except Exception:
            pass

    update_job(
        job_id,
        {"status": "completed", "progressPercent": 100, "currentGigLink": "", "currentSeller": ""},
    )
    append_activity(job_id, f"Completed · {state['us_leads'] + state['canada_leads']} leads")
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

    append_activity(job_id, f'Started · mode={mode} · niche="{niche}"')
    update_job(job_id, {"status": "running", "verificationMessage": ""})

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
            max_gigs = job.get("maxGigs") or 50
            max_pages = config.MAX_SEARCH_PAGES
            append_activity(
                job_id,
                f"Discovering gigs — search pages 1–{max_pages} (up to {max_gigs} gigs)",
            )
            urls, source = await discover_gig_urls(niche, max_gigs, job_id, max_pages=max_pages)
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
