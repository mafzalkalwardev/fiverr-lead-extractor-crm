"""
Fiverr Lead Extractor — Python scraper service.
Polls MongoDB for pending jobs and processes them with Playwright.
"""
import asyncio
import sys
from pathlib import Path

# Allow imports when run as script
sys.path.insert(0, str(Path(__file__).resolve().parent))

import config
from browser import warm_browser
from db import claim_next_job, get_client, reset_stale_running_jobs, set_heartbeat
from worker import process_job


async def setup_browser() -> None:
    from browser import launch_browser, new_page

    print("[setup] Opening Fiverr — complete verification manually, then close this script.")
    ctx = await launch_browser()
    page = await ctx.new_page()
    await page.goto(f"{config.FIVERR_ORIGIN}/search/gigs?query=web%20development", wait_until="domcontentloaded")
    print("[setup] Press Enter here after you finish verification in Chrome…")
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, sys.stdin.readline)
    await page.close()
    print("[setup] Profile saved in browser-profile/")


async def poll_loop() -> None:
    get_client().admin.command("ping")
    print(f"[main] MongoDB OK — polling every {config.POLL_INTERVAL_SEC}s")
    reset_stale_running_jobs()
    await warm_browser()

    while True:
        try:
            set_heartbeat()
            job = claim_next_job()
            if job:
                job_id = str(job["_id"])
                print(f"[main] Processing job {job_id}")
                try:
                    await process_job(job)
                except Exception as err:
                    print(f"[main] Job {job_id} error: {err}")
            await asyncio.sleep(config.POLL_INTERVAL_SEC)
        except KeyboardInterrupt:
            print("[main] Stopping…")
            break
        except Exception as err:
            print(f"[main] Poll error: {err}")
            await asyncio.sleep(config.POLL_INTERVAL_SEC)


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--setup":
        asyncio.run(setup_browser())
        return
    print("[main] Fiverr Lead Extractor Python scraper")
    print("[main] Profile:", config.BROWSER_PROFILE_DIR)
    asyncio.run(poll_loop())


if __name__ == "__main__":
    main()
