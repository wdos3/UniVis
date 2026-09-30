"""Profile a public notice through the actual hosted text or browser-OCR API.

No credentials are required or logged. The output contains notice text, so use
only public/synthetic fixtures and keep artifacts in a suitable local directory.
"""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

import httpx


def browser_ocr_payload(path: Path) -> dict:
    fixture = json.loads(path.read_text(encoding="utf-8"))
    width, height = fixture["image"]["width"], fixture["image"]["height"]
    spans = []
    for item in fixture["items"]:
        left, top, right, bottom = item["box"]
        spans.append({
            "text": item["text"],
            "box": {"x": left / width, "y": top / height,
                    "width": (right - left) / width, "height": (bottom - top) / height},
        })
    return {
        "pages": [{"text": "\n".join(item["text"] for item in fixture["items"]), "spans": spans}],
        "ocr_latency_ms": round(fixture["metrics"]["totalMs"]),
        "provider": "openai", "target_language": "en", "input_type": "uploaded_image",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--text", type=Path)
    inputs.add_argument("--browser-ocr", type=Path)
    parser.add_argument("--base-url", default="https://univis-v2-prototype.vercel.app")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.browser_ocr:
        endpoint = "/api/analyze-client-ocr"
        payload = browser_ocr_payload(args.browser_ocr)
    else:
        endpoint = "/api/analyze"
        payload = {"text": args.text.read_text(encoding="utf-8"), "provider": "openai", "target_language": "en"}
    started = perf_counter()
    with httpx.Client(timeout=180) as client:
        response = client.post(args.base_url.rstrip("/") + endpoint, json=payload)
    wall_ms = round((perf_counter() - started) * 1000)
    body = response.json()
    report = {"measured_at": datetime.now(UTC).isoformat(), "base_url": args.base_url,
              "endpoint": endpoint, "status": response.status_code, "request_wall_ms": wall_ms,
              "ocr_timing": "fixture replay; no new image inference" if args.browser_ocr else "not applicable",
              "result": body}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "result"}))
    print(json.dumps(body.get("acquisition", body)))


if __name__ == "__main__":
    main()
