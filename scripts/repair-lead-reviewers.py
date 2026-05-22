"""Fix leads where reviewerName is a star rating — infer name from review text."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "python_scraper"))

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(ROOT / ".env")

from utils import (  # noqa: E402
    looks_like_rating,
    resolve_reviewer_name,
    reviewer_name_before_country,
    seller_name_from_gig,
    username_from_gig_url,
)


def main() -> None:
    uri = os.getenv("MONGODB_URI", "mongodb://127.0.0.1:27017/fiverr-lead-extractor-crm")
    db_name = uri.rsplit("/", 1)[-1] or "fiverr-lead-extractor-crm"
    client = MongoClient(uri)
    leads = client[db_name]["leads"]

    fixed_reviewer = 0
    fixed_seller = 0
    skipped = 0
    for doc in leads.find({}):
        updates = {}
        gig_url = doc.get("gigLink", "")
        gig_stub = {"gigUrl": gig_url, "sellerUsername": "", "sellerName": ""}
        seller_slug = seller_name_from_gig(gig_stub) or username_from_gig_url(gig_url)
        if seller_slug and (
            (doc.get("sellerName") or "").strip().lower() == "fiverr"
            or looks_like_rating(doc.get("sellerName", ""))
        ):
            updates["sellerName"] = seller_slug

        name = (doc.get("reviewerName") or "").strip()
        review_text = doc.get("review", "")
        if looks_like_rating(name):
            gig = {
                "gigUrl": gig_url,
                "sellerUsername": seller_slug or "",
                "sellerName": seller_slug or "",
            }
            resolved = reviewer_name_before_country(
                f"{name} {doc.get('country', '')} {review_text}"
            )
            if not resolved or looks_like_rating(resolved):
                review = {
                    "reviewerName": name,
                    "reviewText": review_text,
                    "cardText": f"{name} {doc.get('country', '')} {review_text}",
                }
                resolved = resolve_reviewer_name(review, gig)
            if resolved:
                updates["reviewerName"] = resolved
            else:
                skipped += 1

        if updates:
            leads.update_one({"_id": doc["_id"]}, {"$set": updates})
            if "reviewerName" in updates:
                fixed_reviewer += 1
                print(f"Reviewer: {name!r} -> {updates['reviewerName']!r}")
            if "sellerName" in updates:
                fixed_seller += 1
                print(f"Seller: -> {updates['sellerName']!r}")

    print(f"Done. Reviewers fixed: {fixed_reviewer}, sellers fixed: {fixed_seller}, skipped: {skipped}.")


if __name__ == "__main__":
    main()
