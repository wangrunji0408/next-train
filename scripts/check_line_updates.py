#!/usr/bin/env python3
"""
Check update dates for all Beijing Subway lines
"""

import requests
import re
from pathlib import Path
from urllib.parse import urljoin
from bs4 import BeautifulSoup
import logging
import json
from datetime import datetime
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def create_session():
    """Create a session with retry strategy"""
    session = requests.Session()
    retry_strategy = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["HEAD", "GET", "OPTIONS"],
    )
    adapter = HTTPAdapter(
        max_retries=retry_strategy,
        pool_connections=10,
        pool_maxsize=10,
        pool_block=True,
    )
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
    )
    return session


def extract_update_date(soup):
    """Extract update date from a station page"""
    try:
        text = soup.get_text()
        match = re.search(r"(\d{4})年(\d{1,2})月更新", text)
        if match:
            year = match.group(1)
            month = match.group(2).zfill(2)
            return f"{year}-{month}"
        return None
    except Exception as e:
        logger.debug(f"Failed to extract update date: {e}")
        return None


def get_line_update_date(session, line_code):
    """Get the update date for a line"""
    try:
        response = session.get("https://www.bjsubway.com/station/xltcx/", timeout=30)
        soup = BeautifulSoup(response.content, "html.parser")

        # Find all station links for this line
        # Note: Some lines use "lines" (plural) instead of "line" in URLs
        station_links = []
        for link in soup.find_all("a", href=True):
            href = link["href"]
            # Check both "line{code}" and "lines{code}" patterns
            if (f"/line{line_code}/" in href or f"/lines{line_code}/" in href) and ".html" in href:
                station_links.append(urljoin("https://www.bjsubway.com", href))

        if not station_links:
            logger.warning(f"No station links found for line {line_code}")
            return None

        # Try up to 3 stations
        for station_url in station_links[:3]:
            try:
                station_response = session.get(station_url, timeout=30)
                station_soup = BeautifulSoup(
                    station_response.content, "html.parser"
                )
                update_date = extract_update_date(station_soup)
                if update_date:
                    return update_date
            except Exception as e:
                logger.debug(f"Failed to get date from {station_url}: {e}")
                continue

        return None

    except Exception as e:
        logger.error(f"Failed to get update date for line {line_code}: {e}")
        return None


def main():
    # All Beijing Subway lines from bjsubway.com
    lines = {
        "1": "1号线",
        "2": "2号线",
        "5": "5号线",
        "6": "6号线",
        "7": "7号线",
        "8": "8号线",
        "9": "9号线",
        "10": "10号线",
        "13": "13号线",
        "15": "15号线",
        "s1": "S1线",
        "bt": "八通线",
        "cp": "昌平线",
        "yz": "亦庄线",
        "fs": "房山线",
        "xj": "西郊线",
        "jc": "首都机场线",
    }

    session = create_session()
    results = {}
    cutoff_date = datetime(2025, 7, 1)

    logger.info("Checking update dates for all lines...")
    print("\n" + "=" * 70)
    print("Beijing Subway Line Update Check")
    print("=" * 70 + "\n")

    for line_code, line_name in lines.items():
        logger.info(f"Checking {line_name} ({line_code})...")
        update_date = get_line_update_date(session, line_code)

        if update_date:
            results[f"bjsubway_line_{line_code}"] = update_date
            # Parse update date
            try:
                update_dt = datetime.strptime(update_date, "%Y-%m")
                status = "✓ OK" if update_dt < cutoff_date else "⚠ NEEDS UPDATE"
                print(f"{line_name:12} | {update_date:10} | {status}")
            except:
                print(f"{line_name:12} | {update_date:10} | ? UNKNOWN")
        else:
            results[f"bjsubway_line_{line_code}"] = None
            print(f"{line_name:12} | {'N/A':10} | ✗ NO DATE FOUND")

    # Save to cache file
    output_dir = Path("timetables")
    output_dir.mkdir(exist_ok=True)
    cache_file = output_dir / "line_updates.json"

    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    logger.info(f"\nResults saved to {cache_file}")

    # Summary
    print("\n" + "=" * 70)
    print("Summary")
    print("=" * 70 + "\n")

    needs_update = []
    ok_lines = []
    no_date = []

    for line_code, line_name in lines.items():
        cache_key = f"bjsubway_line_{line_code}"
        update_date = results.get(cache_key)

        if update_date:
            try:
                update_dt = datetime.strptime(update_date, "%Y-%m")
                if update_dt >= cutoff_date:
                    needs_update.append(f"{line_name} ({line_code})")
                else:
                    ok_lines.append(f"{line_name} ({line_code})")
            except:
                no_date.append(f"{line_name} ({line_code})")
        else:
            no_date.append(f"{line_name} ({line_code})")

    print(f"✓ Lines up-to-date (< 2025-07): {len(ok_lines)}")
    for line in ok_lines:
        print(f"  - {line}")

    print(f"\n⚠ Lines needing update (>= 2025-07): {len(needs_update)}")
    for line in needs_update:
        print(f"  - {line}")

    if no_date:
        print(f"\n✗ Lines with no date found: {len(no_date)}")
        for line in no_date:
            print(f"  - {line}")

    print("\n" + "=" * 70)
    print("Commands to update lines:")
    print("=" * 70 + "\n")

    if needs_update:
        for line in needs_update:
            # Extract line code from "线路名 (code)" format
            match = re.search(r"\(([^)]+)\)", line)
            if match:
                code = match.group(1)
                print(f"python3 scripts/download_timetables.py -l {code}")


if __name__ == "__main__":
    main()
