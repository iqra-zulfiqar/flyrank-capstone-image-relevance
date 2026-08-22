"""
seed_images.py

Downloads a small, licensed image corpus for the capstone from the
Unsplash and Pexels free APIs, and writes a manifest.json that records
the source, license, and photographer for every image (so the repo
stays reproducible without committing large binaries).

Setup
-----
1. Get free API keys (no credit card):
   - Unsplash: https://unsplash.com/developers  -> create an app -> "Access Key"
   - Pexels:   https://www.pexels.com/api/       -> "Your API Key"

2. Put them in a .env file (never commit this):
     UNSPLASH_ACCESS_KEY=xxxx
     PEXELS_API_KEY=xxxx

3. Install deps:
     pip install requests python-dotenv

4. Run:
     python seed_images.py

Output
------
data/images/<category>/<source>_<id>.jpg
data/images/manifest.json
"""

import os
import json
import time
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

UNSPLASH_ACCESS_KEY = os.getenv("UNSPLASH_ACCESS_KEY", "")
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")

OUTPUT_DIR = Path("data/images")
IMAGES_PER_CATEGORY_PER_SOURCE = 5  # 5 Unsplash + 5 Pexels = 10/category

# Chosen deliberately: fox/wolf are visually similar (tests the mismatch
# guard), dog/bear/deer round out the corpus for realistic ranking.
CATEGORIES = ["red fox", "wolf", "dog", "bear", "deer"]

REQUEST_TIMEOUT = 15
SLEEP_BETWEEN_CALLS = 1.0  # be polite to free-tier rate limits


def fetch_unsplash(query: str, count: int) -> list[dict]:
    if not UNSPLASH_ACCESS_KEY:
        print(f"  [unsplash] skipped (no UNSPLASH_ACCESS_KEY set)")
        return []
    url = "https://api.unsplash.com/search/photos"
    headers = {"Authorization": f"Client-ID {UNSPLASH_ACCESS_KEY}"}
    params = {"query": query, "per_page": count, "orientation": "landscape"}
    resp = requests.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    results = resp.json().get("results", [])
    items = []
    for r in results[:count]:
        items.append({
            "source": "unsplash",
            "id": r["id"],
            "download_url": r["urls"]["regular"],
            "page_url": r["links"]["html"],
            "photographer": r["user"]["name"],
            "photographer_url": r["user"]["links"]["html"],
            "license": "Unsplash License (https://unsplash.com/license)",
        })
    return items


def fetch_pexels(query: str, count: int) -> list[dict]:
    if not PEXELS_API_KEY:
        print(f"  [pexels] skipped (no PEXELS_API_KEY set)")
        return []
    url = "https://api.pexels.com/v1/search"
    headers = {"Authorization": PEXELS_API_KEY}
    params = {"query": query, "per_page": count, "orientation": "landscape"}
    resp = requests.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    results = resp.json().get("photos", [])
    items = []
    for r in results[:count]:
        items.append({
            "source": "pexels",
            "id": r["id"],
            "download_url": r["src"]["large"],
            "page_url": r["url"],
            "photographer": r["photographer"],
            "photographer_url": r["photographer_url"],
            "license": "Pexels License (https://www.pexels.com/license/)",
        })
    return items


def download_file(url: str, dest: Path) -> bool:
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        dest.write_bytes(resp.content)
        return True
    except requests.RequestException as e:
        print(f"    ! download failed: {e}")
        return False


def slugify(text: str) -> str:
    return text.strip().lower().replace(" ", "_")


def main():
    manifest = []
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for category in CATEGORIES:
        cat_slug = slugify(category)
        cat_dir = OUTPUT_DIR / cat_slug
        cat_dir.mkdir(parents=True, exist_ok=True)

        print(f"\n== {category} ==")

        items = []
        items += fetch_unsplash(category, IMAGES_PER_CATEGORY_PER_SOURCE)
        time.sleep(SLEEP_BETWEEN_CALLS)
        items += fetch_pexels(category, IMAGES_PER_CATEGORY_PER_SOURCE)
        time.sleep(SLEEP_BETWEEN_CALLS)

        if not items:
            print(f"  ! no images fetched for '{category}' — check API keys")
            continue

        for item in items:
            filename = f"{item['source']}_{item['id']}.jpg"
            dest_path = cat_dir / filename
            print(f"  downloading {filename} ...")

            ok = download_file(item["download_url"], dest_path)
            if not ok:
                continue

            manifest.append({
                "category": category,
                "filename": filename,
                "path": str(dest_path),
                "source": item["source"],
                "source_id": item["id"],
                "page_url": item["page_url"],
                "photographer": item["photographer"],
                "photographer_url": item["photographer_url"],
                "license": item["license"],
            })

    manifest_path = OUTPUT_DIR / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))

    print(f"\nDone. {len(manifest)} images saved to {OUTPUT_DIR}/")
    print(f"Manifest written to {manifest_path}")

    if len(manifest) < 40:
        print(
            "\nNote: fewer than 40 images downloaded. Check that both "
            "UNSPLASH_ACCESS_KEY and PEXELS_API_KEY are set in your .env, "
            "or raise IMAGES_PER_CATEGORY_PER_SOURCE."
        )


if __name__ == "__main__":
    main()