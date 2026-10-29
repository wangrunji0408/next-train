#!/usr/bin/env python3
"""
Check update dates for all Beijing Subway lines
Uses curl for HTTP requests to avoid SSL compatibility issues
"""

import subprocess
import re
import json
from pathlib import Path
from urllib.parse import urljoin
from bs4 import BeautifulSoup
import logging
from datetime import datetime

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def fetch_url(url):
    """Fetch URL using curl (handles SSL better than Python's requests on macOS).
    Returns decoded HTML string, handling gb2312/gbk encoding."""
    try:
        result = subprocess.run(
            ["curl", "-sS", "--connect-timeout", "15", "--max-time", "30",
             "-H", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
             url],
            capture_output=True, timeout=35
        )
        if result.returncode != 0:
            logger.error(f"curl failed for {url}: {result.stderr.decode('utf-8', errors='replace').strip()}")
            return None

        raw = result.stdout
        # Try to detect charset from meta tag
        head = raw[:2048]
        charset_match = re.search(rb'charset\s*=\s*([a-zA-Z0-9_-]+)', head)
        if charset_match:
            encoding = charset_match.group(1).decode('ascii').lower()
            if encoding in ('gb2312', 'gbk', 'gb18030'):
                return raw.decode('gb18030')
            try:
                return raw.decode(encoding)
            except Exception:
                pass
        # Fallback: try common Chinese encodings then utf-8
        for enc in ['gb18030', 'utf-8']:
            try:
                return raw.decode(enc)
            except (UnicodeDecodeError, LookupError):
                continue
        return raw.decode('utf-8', errors='replace')
    except Exception as e:
        logger.error(f"Failed to fetch {url}: {e}")
        return None


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


def get_line_update_date(line_code):
    """Get the update date for a line"""
    try:
        html = fetch_url("https://www.bjsubway.com/station/xltcx/")
        if not html:
            return None
        soup = BeautifulSoup(html, "html.parser")

        # Find all station links for this line
        station_links = []
        for link in soup.find_all("a", href=True):
            href = link["href"]
            if (f"/line{line_code}/" in href or f"/lines{line_code}/" in href) and ".html" in href:
                station_links.append(urljoin("https://www.bjsubway.com", href))

        if not station_links:
            logger.warning(f"No station links found for line {line_code}")
            return None

        # Try up to 3 stations
        for station_url in station_links[:3]:
            try:
                station_html = fetch_url(station_url)
                if not station_html:
                    continue
                station_soup = BeautifulSoup(station_html, "html.parser")
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

    # Load existing cache
    output_dir = Path("timetables")
    output_dir.mkdir(exist_ok=True)
    cache_file = output_dir / "line_updates.json"

    old_cache = {}
    if cache_file.exists():
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                old_cache = json.load(f)
        except Exception:
            pass

    results = {}

    logger.info("Checking update dates for all lines...")
    print("\n" + "=" * 80)
    print(f"Beijing Subway Line Update Check ({datetime.now():%Y-%m-%d})")
    print("=" * 80 + "\n")
    print(f"{'Line':12} | {'Website':10} | {'Cached':10} | {'Status'}")
    print("-" * 80)

    changed_lines = []
    ok_lines = []
    no_date_lines = []

    for line_code, line_name in lines.items():
        logger.info(f"Checking {line_name} ({line_code})...")
        update_date = get_line_update_date(line_code)

        cache_key = f"bjsubway_line_{line_code}"
        cached_date = old_cache.get(cache_key)

        if update_date:
            results[cache_key] = update_date
            if cached_date is None:
                status = "🆕 NEW (首次发现)"
                changed_lines.append((line_name, line_code, cached_date, update_date))
            elif update_date != cached_date:
                status = f"⚠ CHANGED"
                changed_lines.append((line_name, line_code, cached_date, update_date))
            else:
                status = "✓ UNCHANGED"
                ok_lines.append((line_name, line_code, update_date))
            print(f"{line_name:12} | {update_date:10} | {str(cached_date):10} | {status}")
        else:
            results[cache_key] = None
            no_date_lines.append((line_name, line_code))
            status = f"✗ NO DATE (cached: {cached_date})" if cached_date else "✗ NO DATE"
            print(f"{line_name:12} | {'N/A':10} | {str(cached_date):10} | {status}")

    # Save results
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    # Summary
    print("\n" + "=" * 80)
    print("Summary")
    print("=" * 80 + "\n")

    if changed_lines:
        print(f"⚠ Lines with changes ({len(changed_lines)}):")
        for line_name, line_code, old, new in changed_lines:
            print(f"  - {line_name} ({line_code}): {old} -> {new}")
        print()

    print(f"✓ Lines unchanged: {len(ok_lines)}")
    for line_name, line_code, date in ok_lines:
        print(f"  - {line_name} ({line_code}): {date}")

    if no_date_lines:
        print(f"\n✗ Lines with no date found: {len(no_date_lines)}")
        for line_name, line_code in no_date_lines:
            print(f"  - {line_name} ({line_code})")

    if changed_lines:
        print(f"\n{'=' * 80}")
        print("Commands to update changed lines:")
        print("=" * 80 + "\n")
        for line_name, line_code, old, new in changed_lines:
            # Use the line number/name for download
            arg = line_code if line_code.isdigit() else line_name.replace("线", "")
            print(f"  .venv/bin/python scripts/download_timetables.py -l {arg} -f")

    print()


if __name__ == "__main__":
    main()
