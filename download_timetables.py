#!/usr/bin/env python3
"""
Beijing Subway Timetable Downloader
Downloads timetable images from all Beijing subway operators
"""

import requests
import os
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class SubwayTimetableDownloader:
    def __init__(self, output_dir="timetables"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            }
        )
        self.url_log_file = self.output_dir / "downloaded_urls.txt"
        self.url_log = open(self.url_log_file, "w", encoding="utf-8")
        self.url_log_lock = threading.Lock()

    def download_image(self, url, filename):
        """Download an image from URL and save with given filename"""
        try:
            response = self.session.get(url, stream=True)
            response.raise_for_status()

            filepath = self.output_dir / filename
            filepath.parent.mkdir(parents=True, exist_ok=True)

            with open(filepath, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            # Log URL and filename (thread-safe)
            with self.url_log_lock:
                self.url_log.write(f"{filename}\t{url}\n")
                self.url_log.flush()

            logger.info(f"Downloaded: {filename}")
            return True
        except Exception as e:
            logger.error(f"Failed to download {url}: {e}")
            return False

    def process_bjsubway_station(self, station_url):
        """Process a single Beijing Subway station page"""
        try:
            # Create a new session for this thread
            session = requests.Session()
            session.headers.update(
                {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
                }
            )

            # Get station page
            response = session.get(station_url)
            soup = BeautifulSoup(response.content, "html.parser")

            # Extract line info from URL (for potential future use)
            url_parts = station_url.split("/")

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
                        line_name = filename_parts[0].replace("线", "")
                        station_name = filename_parts[1]
                        img_count += 1

                        filename = f"{line_name}-{station_name}-{img_count}.jpg"
                        if self.download_image(img_url, filename):
                            images_downloaded += 1

            return f"Processed {station_url}: {images_downloaded} images downloaded"

        except Exception as e:
            return f"Error processing {station_url}: {e}"

    def download_bjsubway(self):
        """Download timetables from bjsubway.com with concurrent processing"""
        logger.info("Starting Beijing Subway (bjsubway.com) download...")

        # Get main station list page
        response = self.session.get("https://www.bjsubway.com/station/xltcx/")
        soup = BeautifulSoup(response.content, "html.parser")

        # Find all station links
        station_links = []
        for link in soup.find_all("a", href=True):
            href = link["href"]
            if "/station/xltcx/" in href and ".html" in href:
                station_links.append(urljoin("https://www.bjsubway.com", href))

        logger.info(f"Found {len(station_links)} station links")

        # Process stations concurrently with max 32 workers
        with ThreadPoolExecutor(max_workers=32) as executor:
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

        logger.info("Beijing Subway download completed")

    def process_mtr_station(self, station_data):
        """Process a single MTR Beijing station page"""
        station_url, line_num = station_data
        try:
            # Create a new session for this thread
            session = requests.Session()
            session.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            })

            # Add #schedule fragment to URL
            schedule_url = station_url + "#schedule"

            # Get station schedule page
            response = session.get(schedule_url)
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

            return f"Processed {station_url}: {images_downloaded} images downloaded"

        except Exception as e:
            return f"Error processing {station_url}: {e}"

    def download_mtr_beijing(self):
        """Download timetables from mtr.bj.cn with concurrent processing"""
        logger.info("Starting MTR Beijing download...")

        lines = [4, 14, 16, 17]
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

        # Process all stations concurrently with max 32 workers
        with ThreadPoolExecutor(max_workers=32) as executor:
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

    def download_bjmoa(self):
        """Download timetables from bjmoa.cn with concurrent processing"""
        logger.info("Starting Beijing Rail Operations download...")

        # Line mapping
        lines = {24: "燕房线", 26: "房山线", 16: "机场线"}
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

                # Find all timetable images
                img_count = 0
                for img in soup.find_all("img"):
                    src = img.get("src", "")
                    if "bii.com.cn/file/" in src and (".jpg" in src or ".png" in src):
                        if not src.startswith("http"):
                            img_url = urljoin("https://www.bii.com.cn", src)
                        else:
                            img_url = src

                        # Try to extract station name from surrounding text or alt text
                        station_name = "unknown"
                        alt_text = img.get("alt", "")
                        if alt_text:
                            # Try to extract station name from alt text
                            match = re.search(r"([^-\s]+)站", alt_text)
                            if match:
                                station_name = match.group(1)

                        img_count += 1
                        filename = f"{line_name}-{station_name}-{img_count}.png"
                        all_image_data.append((img_url, filename))

            except Exception as e:
                logger.error(f"Error processing line {line_id}: {e}")
                continue

        logger.info(f"Found {len(all_image_data)} total BJMOA images")

        # Process all images concurrently with max 32 workers
        with ThreadPoolExecutor(max_workers=32) as executor:
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

    def download_all(self):
        """Download timetables from all sources"""
        logger.info("Starting complete timetable download...")

        try:
            self.download_bjsubway()
        except Exception as e:
            logger.error(f"BJSubway download failed: {e}")

        try:
            self.download_mtr_beijing()
        except Exception as e:
            logger.error(f"MTR Beijing download failed: {e}")

        try:
            self.download_bjmoa()
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
    downloader = SubwayTimetableDownloader()
    downloader.download_all()


if __name__ == "__main__":
    main()
