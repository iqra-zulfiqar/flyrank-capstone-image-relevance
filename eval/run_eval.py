"""
Runs the labeled evaluation set against the live API and reports
top-1 precision — the headline quality number for the README (§14 of
the capstone brief: "Of all posts, the share whose first suggested
image was the labeled correct one").

Usage:
    python eval/run_eval.py
    python eval/run_eval.py --base-url http://localhost:8000

Requires the API to be running, images already classified (Phase 2)
and embedded (Phase 3) — i.e. run this after the corpus is fully set up.
"""
import argparse
import json
import sys
from pathlib import Path

import requests

LABELED_SET_PATH = Path(__file__).parent / "labeled_set.json"


def create_post(base_url: str, title: str, body: str) -> str:
    resp = requests.post(f"{base_url}/posts", json={"title": title, "body": body}, timeout=30)
    resp.raise_for_status()
    return resp.json()["id"]


def get_ranked_images(base_url: str, post_id: str) -> dict:
    resp = requests.get(f"{base_url}/posts/{post_id}/images", timeout=30)
    resp.raise_for_status()
    return resp.json()


def get_image_subject(base_url: str, image_id: str) -> str:
    resp = requests.get(f"{base_url}/images/{image_id}", timeout=30)
    resp.raise_for_status()
    return (resp.json().get("subject") or "").lower()


def evaluate(base_url: str) -> None:
    labeled_set = json.loads(LABELED_SET_PATH.read_text())

    correct = 0
    total = len(labeled_set)
    rows = []

    for item in labeled_set:
        title = item["title"]
        expected_category = item["expected_category"]
        expect_match = item["expect_match"]

        post_id = create_post(base_url, title, item["body"])
        result = get_ranked_images(base_url, post_id)

        matched = result["matched"]
        is_correct = False
        detail = ""

        if expect_match:
            if matched:
                subject = get_image_subject(base_url, result["suggested_image_id"])
                if expected_category in subject:
                    is_correct = True
                    detail = f"matched '{subject}' (similarity {result['similarity']:.2f})"
                else:
                    detail = f"WRONG match: expected '{expected_category}', got '{subject}'"
            else:
                detail = f"expected a match but got none: {result['reason']}"
        else:
            if not matched:
                is_correct = True
                detail = f"correctly found no match: {result['reason']}"
            else:
                detail = f"WRONG: expected no match, but got a suggestion"

        if is_correct:
            correct += 1

        rows.append({
            "title": title,
            "expected": expected_category or "(no match expected)",
            "correct": is_correct,
            "detail": detail,
        })

    precision = correct / total if total else 0.0

    print(f"\n{'='*70}")
    print(f"TOP-1 PRECISION: {precision:.2%} ({correct}/{total})")
    print(f"{'='*70}\n")

    for row in rows:
        status = "PASS" if row["correct"] else "FAIL"
        print(f"[{status}] {row['title']}")
        print(f"       expected: {row['expected']}")
        print(f"       {row['detail']}\n")

    # Non-zero exit if precision is suspiciously low, so this can be
    # wired into a CI-style check later if desired.
    sys.exit(0 if precision >= 0.5 else 1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    args = parser.parse_args()
    evaluate(args.base_url)