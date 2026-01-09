#!/usr/bin/env python3
"""
Beijing Subway Timetable Downloader
Downloads timetable images from all Beijing subway operators
"""

import requests
import re
import argparse
from pathlib import Path
from urllib.parse import urljoin
from bs4 import BeautifulSoup
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import json

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class SubwayTimetableDownloader:
    def __init__(self, output_dir="timetables"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.session = self._create_session()
        self.url_log_file = self.output_dir / "downloaded_urls.txt"
        self.url_log = open(self.url_log_file, "a", encoding="utf-8")
        self.update_cache_file = self.output_dir / "line_updates.json"
        self.update_cache = self._load_update_cache()

    def _create_session(self):
        """Create a session with retry strategy and connection pooling"""
        session = requests.Session()

        # Configure retry strategy
        retry_strategy = Retry(
            total=3,  # Total number of retries
            backoff_factor=1,  # Wait 1, 2, 4 seconds between retries
            status_forcelist=[429, 500, 502, 503, 504],  # Retry on these status codes
            allowed_methods=["HEAD", "GET", "OPTIONS"],  # Methods to retry
        )

        # Mount adapters with retry strategy and connection pooling
        adapter = HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=10,  # Limit connection pool size
            pool_maxsize=10,
            pool_block=True,  # Block when pool is full instead of creating new connections
        )
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        # Set headers
        session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            }
        )

        return session

    def _load_update_cache(self):
        """Load the cache of line update dates"""
        if self.update_cache_file.exists():
            try:
                with open(self.update_cache_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load update cache: {e}")
                return {}
        return {}

    def _save_update_cache(self):
        """Save the cache of line update dates"""
        try:
            with open(self.update_cache_file, "w", encoding="utf-8") as f:
                json.dump(self.update_cache, f, ensure_ascii=False, indent=2)
            logger.info(f"Update cache saved to {self.update_cache_file}")
        except Exception as e:
            logger.error(f"Failed to save update cache: {e}")

    def _extract_update_date(self, soup):
        """Extract update date from a station page (format: YYYY年MM月更新)"""
        try:
            # Look for text matching pattern "YYYY年MM月更新"
            text = soup.get_text()
            match = re.search(r'(\d{4})年(\d{1,2})月更新', text)
            if match:
                year = match.group(1)
                month = match.group(2).zfill(2)  # Pad month with zero
                return f"{year}-{month}"
            return None
        except Exception as e:
            logger.debug(f"Failed to extract update date: {e}")
            return None

    def _get_line_update_date(self, line_code):
        """Get the update date for a line by checking station pages"""
        try:
            # Construct URL for the line's station list
            response = self.session.get(
                "https://www.bjsubway.com/station/xltcx/", timeout=30
            )
            soup = BeautifulSoup(response.content, "html.parser")

            # Find all station links for this line and try each one
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

            # Try up to 3 stations to find update date
            for station_url in station_links[:3]:
                try:
                    # Get station page
                    station_response = self.session.get(station_url, timeout=30)
                    station_soup = BeautifulSoup(station_response.content, "html.parser")

                    # Extract update date
                    update_date = self._extract_update_date(station_soup)
                    if update_date:
                        logger.info(f"Line {line_code} update date: {update_date}")
                        return update_date
                except Exception as e:
                    logger.debug(f"Failed to get update date from {station_url}: {e}")
                    continue

            logger.warning(f"Could not find update date for line {line_code}")
            return None

        except Exception as e:
            logger.error(f"Failed to get update date for line {line_code}: {e}")
            return None

    def _should_update_line(self, line_code):
        """Check if a line needs to be updated based on the update date"""
        current_update = self._get_line_update_date(line_code)

        if current_update is None:
            # If we can't get the update date, download anyway
            logger.info(f"Line {line_code}: No update date found, downloading...")
            return True

        cached_update = self.update_cache.get(f"bjsubway_line_{line_code}")

        if cached_update is None:
            # First time downloading this line
            logger.info(f"Line {line_code}: First download, update date {current_update}")
            self.update_cache[f"bjsubway_line_{line_code}"] = current_update
            return True

        if current_update != cached_update:
            # Update date changed
            logger.info(
                f"Line {line_code}: Update date changed from {cached_update} to {current_update}, downloading..."
            )
            self.update_cache[f"bjsubway_line_{line_code}"] = current_update
            return True

        # Update date unchanged
        logger.info(
            f"Line {line_code}: Update date unchanged ({current_update}), skipping download"
        )
        return False

    def download_image(self, url, filename, max_retries=3):
        """Download an image from URL and save with given filename with retry logic"""
        filepath = self.output_dir / filename
        filepath.parent.mkdir(parents=True, exist_ok=True)

        for attempt in range(max_retries):
            try:
                # Add timeout to prevent hanging
                response = self.session.get(url, stream=True, timeout=30)
                response.raise_for_status()

                # Write to temporary file first
                temp_filepath = filepath.with_suffix(filepath.suffix + ".tmp")

                with open(temp_filepath, "wb") as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:  # Filter out keep-alive chunks
                            f.write(chunk)

                # Verify file size matches Content-Length if available
                if "content-length" in response.headers:
                    expected_size = int(response.headers["content-length"])
                    actual_size = temp_filepath.stat().st_size
                    if actual_size != expected_size:
                        temp_filepath.unlink()
                        raise Exception(
                            f"Incomplete download: expected {expected_size} bytes, got {actual_size} bytes"
                        )

                # Move temp file to final location
                temp_filepath.rename(filepath)

                # Log URL and filename (thread-safe)
                self.url_log.write(f"{filename}\t{url}\n")
                self.url_log.flush()

                logger.info(f"Downloaded: {filename}")
                return True

            except Exception as e:
                if attempt < max_retries - 1:
                    wait_time = 2**attempt  # Exponential backoff: 1, 2, 4 seconds
                    logger.warning(
                        f"Attempt {attempt + 1}/{max_retries} failed for {url}: {e}. Retrying in {wait_time}s..."
                    )
                    time.sleep(wait_time)
                    # Clean up temp file if it exists
                    temp_filepath = filepath.with_suffix(filepath.suffix + ".tmp")
                    if temp_filepath.exists():
                        temp_filepath.unlink()
                else:
                    logger.error(
                        f"Failed to download {url} after {max_retries} attempts: {e}"
                    )
                    # Clean up temp file if it exists
                    temp_filepath = filepath.with_suffix(filepath.suffix + ".tmp")
                    if temp_filepath.exists():
                        temp_filepath.unlink()
                    # Clean up partial file if it exists
                    if filepath.exists():
                        filepath.unlink()
                    return False

        return False

    def process_bjsubway_station(self, station_url):
        """Process a single Beijing Subway station page"""
        try:
            # Create a new session for this thread with proper configuration
            session = self._create_session()

            # Get station page with timeout
            response = session.get(station_url, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, "html.parser")

            images_downloaded = 0
            # Find timetable images
            img_count = 0
            for img in soup.find_all("img"):
                src = img.get("src", "")
                if "/d/file/station/" in src and (".jpg" in src or ".png" in src):
                    img_url = urljoin("https://www.bjsubway.com", src)

                    # Extract station name from image filename
                    filename_parts = src.split("/")[-1].split("-")
                    if len(filename_parts) >= 2:
                        line_name = (
                            filename_parts[0].replace("号线", "").replace("线", "")
                        )
                        station_name = filename_parts[1]
                        if station_name.endswith("站") and station_name not in [
                            "朝阳站",
                            "清河站",
                            "丰台站",
                            "北京站",
                            "北京西站",
                            "北京南站",
                            "亦庄火车站",
                        ]:
                            station_name = station_name[:-1]
                        img_count += 1

                        filename = f"{line_name}-{station_name}-{img_count}.jpg"
                        if self.download_image(img_url, filename):
                            images_downloaded += 1

            # Close the session to free up connections
            session.close()
            return f"Processed {station_url}: {images_downloaded} images downloaded"

        except Exception as e:
            return f"Error processing {station_url}: {e}"

    def download_bjsubway(self, line_filter=None, force=False):
        """Download timetables from bjsubway.com with concurrent processing

        Args:
            line_filter: Specific line to download (e.g., "1", "6", "昌平")
            force: If True, skip update date check and download anyway
        """
        if line_filter:
            logger.info(
                f"Starting Beijing Subway (bjsubway.com) download for line {line_filter}..."
            )
        else:
            logger.info("Starting Beijing Subway (bjsubway.com) download...")

        # Line code mapping for special lines
        line_code_map = {
            "昌平": "cp",
            "房山": "fs",
            "八通": "bt",
            "亦庄": "yz",
            "首都机场": "jc",
        }

        # Check if we need to update this line (unless forced or downloading all lines)
        if line_filter and not force:
            # Determine the line code for update check
            line_code_for_check = line_filter
            if line_filter in line_code_map:
                line_code_for_check = line_code_map[line_filter]

            if not self._should_update_line(line_code_for_check):
                logger.info(f"Skipping line {line_filter} (no update needed)")
                return

        # Get main station list page
        response = self.session.get("https://www.bjsubway.com/station/xltcx/")
        soup = BeautifulSoup(response.content, "html.parser")

        # Find all station links
        station_links = []
        for link in soup.find_all("a", href=True):
            href = link["href"]
            if "/station/xltcx/" in href and ".html" in href:
                # If line filter is specified, check if URL matches
                if line_filter:
                    # Extract line code from URL path like /line1/, /linecp/, or /lines7/
                    line_match = re.search(r"/lines?([^/]+)/", href)
                    if line_match:
                        url_line_code = line_match.group(1)

                        # Check if it matches the filter
                        # For numeric lines, compare directly
                        if url_line_code == line_filter:
                            station_links.append(
                                urljoin("https://www.bjsubway.com", href)
                            )
                        # For named lines, check if filter matches the code or the name
                        elif (
                            line_filter in line_code_map
                            and line_code_map[line_filter] == url_line_code
                        ):
                            station_links.append(
                                urljoin("https://www.bjsubway.com", href)
                            )
                        # Also support reverse lookup (e.g., user inputs "cp" for 昌平线)
                        elif line_filter == url_line_code:
                            station_links.append(
                                urljoin("https://www.bjsubway.com", href)
                            )
                else:
                    station_links.append(urljoin("https://www.bjsubway.com", href))

        logger.info(f"Found {len(station_links)} station links")

        if line_filter and len(station_links) == 0:
            logger.warning(f"No stations found for line {line_filter} on bjsubway.com")
            return

        # Process stations concurrently with reduced workers to avoid connection pool issues
        with ThreadPoolExecutor(max_workers=8) as executor:
            # Submit all tasks
            future_to_url = {
                executor.submit(self.process_bjsubway_station, url): url
                for url in station_links
            }

            # Process completed tasks
            completed = 0
            for future in as_completed(future_to_url):
                url = future_to_url[future]
                try:
                    result = future.result()
                    completed += 1
                    logger.info(f"[{completed}/{len(station_links)}] {result}")
                except Exception as exc:
                    logger.error(f"Station {url} generated an exception: {exc}")

        # Save update cache after successful download
        self._save_update_cache()
        logger.info("Beijing Subway download completed")

    def process_mtr_station(self, station_data):
        """Process a single MTR Beijing station page"""
        station_url, line_num = station_data
        try:
            # Create a new session for this thread with proper configuration
            session = self._create_session()

            # Add #schedule fragment to URL
            schedule_url = station_url + "#schedule"

            # Get station schedule page with timeout
            response = session.get(schedule_url, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, "html.parser")

            # Extract station name from page title or content
            station_name = "unknown"
            title = soup.find("title")
            if title:
                title_text = title.get_text()
                # Try to extract station name from title
                match = re.search(r"([^-\s]+) - ", title_text)
                if match:
                    station_name = match.group(1)

            images_downloaded = 0
            # Find timetable images
            img_count = 0
            for img in soup.find_all("img"):
                src = img.get("src", "")
                if "cdnwww.mtr.bj.cn/bjmtr/station/" in src:
                    if src.startswith("//"):
                        img_url = "https:" + src
                    else:
                        img_url = src

                    img_count += 1
                    filename = f"{line_num}-{station_name}-{img_count}.jpg"
                    if self.download_image(img_url, filename):
                        images_downloaded += 1

            # Close the session to free up connections
            session.close()
            return f"Processed {station_url}: {images_downloaded} images downloaded"

        except Exception as e:
            return f"Error processing {station_url}: {e}"

    def download_mtr_beijing(self, line_filter=None):
        """Download timetables from mtr.bj.cn with concurrent processing"""
        if line_filter:
            logger.info(f"Starting MTR Beijing download for line {line_filter}...")
        else:
            logger.info("Starting MTR Beijing download...")

        lines = [4, 14, 16, 17]

        # Filter lines if specified
        if line_filter:
            try:
                line_num = int(line_filter)
                if line_num in lines:
                    lines = [line_num]
                else:
                    logger.warning(
                        f"Line {line_filter} is not operated by MTR Beijing. Skipping MTR Beijing download."
                    )
                    return
            except ValueError:
                logger.warning(
                    f"Line {line_filter} is not operated by MTR Beijing. Skipping MTR Beijing download."
                )
                return

        all_station_data = []

        # Collect all station data first
        for line_num in lines:
            logger.info(f"Collecting stations for MTR Line {line_num}")

            # Get line page
            response = self.session.get(
                f"https://www.mtr.bj.cn/service/line/line-{line_num}.html"
            )
            soup = BeautifulSoup(response.content, "html.parser")

            # Find station links
            for link in soup.find_all("a", href=True):
                href = link["href"]
                if "/service/line/station/" in href:
                    station_url = urljoin("https://www.mtr.bj.cn", href)
                    all_station_data.append((station_url, line_num))

        logger.info(f"Found {len(all_station_data)} total MTR stations")

        # Process all stations concurrently with reduced workers to avoid connection pool issues
        with ThreadPoolExecutor(max_workers=8) as executor:
            # Submit all tasks
            future_to_data = {
                executor.submit(self.process_mtr_station, data): data
                for data in all_station_data
            }

            # Process completed tasks
            completed = 0
            for future in as_completed(future_to_data):
                data = future_to_data[future]
                try:
                    result = future.result()
                    completed += 1
                    logger.info(f"[{completed}/{len(all_station_data)}] {result}")
                except Exception as exc:
                    logger.error(f"Station {data[0]} generated an exception: {exc}")

        logger.info("MTR Beijing download completed")

    def process_bjmoa_image(self, image_data):
        """Process a single BJMOA timetable image"""
        img_url, filename = image_data
        try:
            if self.download_image(img_url, filename):
                return f"Downloaded: {filename}"
            else:
                return f"Failed to download: {filename}"
        except Exception as e:
            return f"Error downloading {filename}: {e}"

    def download_bjmoa(self, line_filter=None):
        """Download timetables from bjmoa.cn with concurrent processing"""
        if line_filter:
            logger.info(
                f"Starting Beijing Rail Operations download for line {line_filter}..."
            )
        else:
            logger.info("Starting Beijing Rail Operations download...")

        # Line mapping
        lines = {24: "燕房", 26: "大兴机场", 16: "19"}

        # Filter lines if specified
        if line_filter:
            # Check if line_filter matches any line_name
            matching_lines = {
                line_id: line_name
                for line_id, line_name in lines.items()
                if line_name == line_filter or str(line_id) == line_filter
            }
            if matching_lines:
                lines = matching_lines
            else:
                logger.warning(
                    f"Line {line_filter} is not operated by BJMOA. Skipping BJMOA download."
                )
                return

        all_image_data = []

        # Collect all image data first
        for line_id, line_name in lines.items():
            logger.info(f"Collecting images for {line_name} (ID: {line_id})")

            try:
                # Get line page
                response = self.session.get(
                    f"https://www.bjmoa.cn/trainTimeList_363.html?sline={line_id}"
                )
                soup = BeautifulSoup(response.content, "html.parser")

                # Find the mod-roads div and search for images within it
                mod_roads_div = soup.find("div", class_="mod-roads")
                if mod_roads_div:
                    station_img_counts = {}  # Track image count per station

                    for img in mod_roads_div.find_all("img"):
                        src = img.get("src", "")
                        if "bii.com.cn/file/" in src and (
                            ".jpg" in src or ".png" in src
                        ):
                            if not src.startswith("http"):
                                img_url = urljoin("https://www.bii.com.cn", src)
                            else:
                                img_url = src

                            # Try to extract station name from surrounding text or alt text
                            station_name = "unknown"
                            alt_text = img.get("alt", "")
                            if alt_text:
                                station_name = alt_text

                            # Get or initialize count for this station
                            if station_name not in station_img_counts:
                                station_img_counts[station_name] = 0
                            station_img_counts[station_name] += 1

                            filename = f"{line_name}-{station_name}-{station_img_counts[station_name]}.png"
                            all_image_data.append((img_url, filename))
                else:
                    logger.warning(
                        f"No mod-roads div found for {line_name} (ID: {line_id})"
                    )

            except Exception as e:
                logger.error(f"Error processing line {line_id}: {e}")
                continue

        logger.info(f"Found {len(all_image_data)} total BJMOA images")

        # Process all images concurrently with reduced workers to avoid connection pool issues
        with ThreadPoolExecutor(max_workers=8) as executor:
            # Submit all tasks
            future_to_data = {
                executor.submit(self.process_bjmoa_image, data): data
                for data in all_image_data
            }

            # Process completed tasks
            completed = 0
            for future in as_completed(future_to_data):
                data = future_to_data[future]
                try:
                    result = future.result()
                    completed += 1
                    logger.info(f"[{completed}/{len(all_image_data)}] {result}")
                except Exception as exc:
                    logger.error(f"Image {data[1]} generated an exception: {exc}")

        logger.info("BJMOA download completed")

    def download_all(self, line_filter=None, force=False):
        """Download timetables from all sources

        Args:
            line_filter: Specific line to download
            force: If True, skip update date check and download anyway
        """
        if line_filter:
            logger.info(f"Starting timetable download for line {line_filter}...")
        else:
            logger.info("Starting complete timetable download...")

        try:
            self.download_bjsubway(line_filter, force=force)
        except Exception as e:
            logger.error(f"BJSubway download failed: {e}")

        try:
            self.download_mtr_beijing(line_filter)
        except Exception as e:
            logger.error(f"MTR Beijing download failed: {e}")

        try:
            self.download_bjmoa(line_filter)
        except Exception as e:
            logger.error(f"BJMOA download failed: {e}")

        # Close URL log file
        self.url_log.close()
        logger.info(f"Download complete! URLs logged to {self.url_log_file}")

    def __del__(self):
        """Cleanup: ensure URL log file is closed"""
        if hasattr(self, "url_log") and not self.url_log.closed:
            self.url_log.close()


def main():
    parser = argparse.ArgumentParser(
        description="Download Beijing subway timetable images from official sources",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Download all lines
  python download_timetables.py

  # Download a specific line by number
  python download_timetables.py --line 1
  python download_timetables.py -l 4

Sources:
  - Beijing Subway: https://www.bjsubway.com (Lines 1, 2, 5, 6, 7, 8, 9, 10, 13, 15, S1, 八通, 昌平, 亦庄, 房山, 西郊, 首都机场)
  - MTR Beijing: https://www.mtr.bj.cn (Lines 4, 14, 16, 17)
  - BJMOA: https://www.bjmoa.cn (Lines 燕房, 大兴机场, 19)
        """,
    )
    parser.add_argument(
        "-l",
        "--line",
        type=str,
        help="Specify a single line to download (e.g., 1, 4, 燕房, 大兴机场)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        default="timetables",
        help="Output directory for downloaded timetables (default: timetables)",
    )
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Force download even if update date hasn't changed (for Beijing Subway only)",
    )

    args = parser.parse_args()

    downloader = SubwayTimetableDownloader(output_dir=args.output)
    downloader.download_all(line_filter=args.line, force=args.force)


if __name__ == "__main__":
    main()
