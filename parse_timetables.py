#!/usr/bin/env python3
"""
Parse train timetable images using OCR to extract schedules.
"""

import os
import re
import json
from pathlib import Path
from typing import List, Tuple, Dict, Optional
from concurrent.futures import ProcessPoolExecutor, as_completed
import numpy as np
from ocrmac import ocrmac
from PIL import Image
from thefuzz import fuzz
from functools import partial


def group_text_by_lines(annotations: List[Tuple], eps: float = 2e-2) -> List[List[str]]:
    """
    Group OCR annotations by lines based on y-coordinate proximity.

    Args:
        annotations: List of (text, confidence, bbox) tuples
        eps: Maximum y-coordinate difference to consider same line

    Returns:
        List of lines, each containing annotations for that line
    """
    if not annotations:
        return []

    # Sort by y-coordinate (second element of bbox)
    sorted_annotations = sorted(annotations, key=lambda x: -x[2][1])

    lines = []
    current_line = [sorted_annotations[0]]
    current_y = sorted_annotations[0][2][1]

    for annotation in sorted_annotations[1:]:
        y_coord = annotation[2][1]

        if abs(y_coord - current_y) <= eps:
            # Same line
            current_line.append(annotation)
        else:
            # New line
            # Sort current line by x-coordinate (first element of bbox)
            current_line = [
                s for s, _, _ in sorted(current_line, key=lambda x: x[2][0])
            ]
            lines.append(current_line)
            current_line = [annotation]
            current_y = y_coord

    # Add the last line
    if current_line:
        current_line = [s for s, _, _ in sorted(current_line, key=lambda x: x[2][0])]
        lines.append(current_line)

    return lines


def extract_destination(lines: List[List[str]]) -> Optional[str]:
    """
    Extract destination by finding pattern "开往XXX方向"
    """
    for line in lines:
        line_text = "".join(line)
        match = re.search(r"[开牙去][往住注]?(.+?)站?(方向|To)", line_text)
        if match:
            return match.group(1).strip()
    return None


def extract_operating_time(lines: List[List[str]]) -> Optional[str]:
    """
    Extract operating time by finding "工作日" or "双休日"
    """
    for line in lines:
        line_text = "".join(line)
        if "作日" in line_text or "Weekdays" in line_text:
            return "工作日"
        elif "双休日" in line_text or "Weekends" in line_text:
            return "双休日"
        elif "平日" in line_text or "Ordinary" in line_text:
            return "平日"
        elif "星期五" in line_text or "周五" in line_text or "Friday" in line_text:
            return "星期五"
    return None


def replace_circle_number(s: str) -> str:
    s = s.replace("①", "1")
    s = s.replace("②", "2")
    s = s.replace("③", "3")
    s = s.replace("④", "4")
    s = s.replace("⑤", "5")
    s = s.replace("⑥", "6")
    s = s.replace("⑦", "7")
    s = s.replace("⑧", "8")
    s = s.replace("⑨", "9")
    return s


def extract_schedule_times(lines: List[List[str]]) -> List[str]:
    """
    Extract schedule times from lines starting with hours 4-23
    """
    schedule_times = []

    last_hour = None
    for line in lines:
        line_text = ""
        for c in line:
            c = replace_circle_number(c)
            if c.isnumeric():
                line_text += c

        if not line_text:
            continue

        # Check if first number is an hour (4-23)
        try:
            if not line[0].isnumeric() or "表" in line or line_text == "520":
                continue  # skip footer
            if last_hour is None and not (
                line_text[0] in "567" or line_text[0:2] in ["05", "06", "07"]
            ):
                continue
            if line_text[0] in "456789":
                hour = int(line_text[0])
                line_text = line_text[1:]  # Remove hour from text
            elif line_text[0:2] in [f"{x:02d}" for x in range(5, 24)] + ["00"]:
                hour = int(line_text[0:2])
                line_text = line_text[2:]  # Remove hour from text
            else:
                continue
            last_hour = hour

            # Process remaining numbers as minutes
            while len(line_text) >= 2:
                try:
                    minute = int(line_text[0:2])
                    if 0 <= minute <= 59:  # Valid minute
                        schedule_times.append(f"{hour:02d}:{minute:02d}")
                except ValueError:
                    continue
                finally:
                    line_text = line_text[2:]  # Remove processed minute

        except ValueError:
            continue

    schedule_times.sort(key=lambda x: x.replace("00:", "24:"))
    return schedule_times


THRESHOLDS = {
    "燕房": 192,
    "大兴机场": 128,
    "19": 128,
}


def convert_and_binarize_image(
    image_path: str,
) -> List[Tuple[Image.Image, Image.Image]]:
    """
    Convert image to PNG format, keep grayscale and binary versions, and split if tall vertical

    Args:
        image_path: Path to image file

    Returns:
        List of (grayscale_image, binary_image) tuples (1 for normal images, 2 for split tall images)
    """
    line = Path(image_path).stem.split("-")[0]
    threshold = THRESHOLDS.get(line, 80)

    with Image.open(image_path) as img:
        # Convert CMYK to RGB if necessary
        if img.mode == "CMYK":
            img = img.convert("RGB")
        # Convert other modes to RGB for compatibility
        elif img.mode not in ("RGB", "RGBA", "L", "LA"):
            img = img.convert("RGB")

        # Convert to grayscale for binarization
        if img.mode != "L":
            img = img.convert("L")

        width, height = img.size

        # Resize if longest side exceeds 8192 pixels
        max_side = max(width, height)
        if max_side > 8192:
            # Scale to keep longest side under 4000px
            scale_factor = 3999 / max_side
            new_width = int(width * scale_factor)
            new_height = int(height * scale_factor)
            img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            width, height = new_width, new_height

        # Check if image is tall vertical
        if height / width > 1.5 and Path(image_path).stem.startswith("10"):
            # Split into two equal height parts
            half_height = height // 2
            top_img = img.crop((0, 0, width, half_height))
            bottom_img = img.crop((0, half_height, width, height))
            images = [top_img, bottom_img]
        else:
            images = [img]

        processed_images = []
        for image in images:
            # Keep grayscale version
            grayscale_img = image.copy()

            # Create binary version
            img_array = np.array(image)
            binary_array = (img_array > threshold).astype(np.uint8) * 255
            binary_img = Image.fromarray(binary_array, mode="L")

            processed_images.append((grayscale_img, binary_img))

        return processed_images


def extract_route_and_station(filename: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Extract route and station from filename pattern "线路-站名-*.<扩展名>"
    """
    # Remove file extension
    basename = os.path.splitext(os.path.basename(filename))[0]

    # Split by '-' and take first two parts
    parts = basename.split("-")

    if len(parts) >= 2:
        route = parts[0]
        station = parts[1]
        return route, station

    return None, None


def parse_station_names_from_files(image_files: List[Path]) -> Dict[str, List[str]]:
    """Parse station names from image files and group by route"""
    route_stations = {"首都机场": ["首都机场"], "1": ["环球度假区"], "八通": ["古城"]}

    for image_path in image_files:
        route, station = extract_route_and_station(str(image_path))
        if route and station:
            if route not in route_stations:
                route_stations[route] = []
            if station not in route_stations[route]:
                route_stations[route].append(station)

    return route_stations


def auto_correct_destination(
    destination: str,
    route: str,
    route_stations: Dict[str, List[str]],
) -> str:
    """Auto-correct destination name to the closest station in the same route"""
    if not destination or not route or route not in route_stations:
        return destination

    station_list = route_stations[route]
    if not station_list:
        return destination

    # Normal processing for other routes
    # Check for exact match first
    if destination in station_list:
        return destination

    # Find the best match (closest station)
    best_match = destination
    best_score = 0

    for station in station_list:
        score = fuzz.ratio(destination, station)
        if score > best_score:
            best_score = score
            best_match = station

    return best_match


def parse_timetable_image(
    image_path: str, route_stations: Dict[str, List[str]] = None
) -> List[Dict]:
    """
    Parse a single timetable image and extract all information
    Returns list of results (multiple if image was split)
    """
    try:
        # Convert and binarize image for better OCR (may return multiple images if split)
        image_pairs = convert_and_binarize_image(image_path)

        os.makedirs("annotations", exist_ok=True)
        results = []

        for i, (grayscale_img, binary_img) in enumerate(image_pairs):
            suffix = f"-{i+1}" if len(image_pairs) > 1 else ""
            annotation_path_gray = (
                f"annotations/{Path(image_path).stem}{suffix}_gray.png"
            )
            annotation_path_binary = (
                f"annotations/{Path(image_path).stem}{suffix}_binary.png"
            )

            # Perform OCR on grayscale for destination and operating_time
            ocr_gray = ocrmac.OCR(grayscale_img, framework="livetext")
            annotations_gray = ocr_gray.recognize()
            ocr_gray.annotate_PIL().save(annotation_path_gray)

            # Group text by lines for grayscale OCR
            lines_gray = group_text_by_lines(annotations_gray)

            # Extract destination and operating_time from grayscale
            destination = extract_destination(lines_gray)
            operating_time = extract_operating_time(lines_gray)

            # Auto-correct destination using route stations
            route, station = extract_route_and_station(image_path)
            if route_stations and route and destination:
                corrected_destination = auto_correct_destination(
                    destination, route, route_stations
                )
                if corrected_destination != destination:
                    print(f"Auto-correct: '{destination}' -> '{corrected_destination}'")
                destination = corrected_destination

            # Perform OCR on binary image for schedule_times
            ocr_binary = ocrmac.OCR(binary_img, framework="livetext")
            annotations_binary = ocr_binary.recognize()
            ocr_binary.annotate_PIL().save(annotation_path_binary)

            # Group text by lines for binary OCR
            lines_binary = group_text_by_lines(annotations_binary)

            # Extract schedule_times from binary
            schedule_times = extract_schedule_times(lines_binary)

            # Debug
            print(
                f"线路-{route}, 站名-{station}, 开往-{destination}, 时段-{operating_time}",
            )
            minutes = {}
            for time in schedule_times:
                hour, minute = map(int, time.split(":"))
                minutes[hour] = minutes.get(hour, []) + [minute]
            for hour, mins in sorted(
                minutes.items(), key=lambda x: 24 if x[0] == 0 else x[0]
            ):
                print(f"{hour:02}:", end="")
                for minute in mins:
                    print(f" {minute:02}", end="")
                print()

            result = {
                "filename": os.path.basename(image_path) + suffix,
                "route": route,
                "station": station,
                "destination": destination,
                "operating_time": operating_time,
                "schedule_times": schedule_times,
            }
            results.append(result)

        return results
    except Exception as e:
        return [
            {
                "filename": os.path.basename(image_path),
                "route": None,
                "station": None,
                "destination": None,
                "operating_time": None,
                "schedule_times": [],
                "error": str(e),
            }
        ]


def main():
    """
    Process all timetable images in parallel and output to JSONL
    """
    timetables_dir = Path("timetables")
    output_file = "timetable.jsonl"
    max_workers = 10

    if not timetables_dir.exists():
        print(f"Error: {timetables_dir} directory not found")
        return

    # Find all image files
    image_extensions = {".jpg", ".jpeg", ".png"}
    image_files = []

    for ext in image_extensions:
        image_files.extend(timetables_dir.glob(f"*{ext}"))

    if not image_files:
        print("No image files found in timetables directory")
        return

    print(f"Found {len(image_files)} image files to process")

    # Parse station names from filenames to build reference for auto-correction
    print("Building station reference from filenames...")
    route_stations = parse_station_names_from_files(image_files)
    print(f"Found stations for {len(route_stations)} routes")

    # # Filter to keep first 4 files per route for testing
    # route_images = {}
    # for image_path in sorted(image_files):
    #     route, station = extract_route_and_station(str(image_path))
    #     if route not in route_images:
    #         route_images[route] = []
    #     if len(route_images[route]) < 4:
    #         route_images[route].append(image_path)

    # image_files = [img for img_list in route_images.values() for img in img_list]
    # print(f"Filtered to {len(image_files)} images (max 5 per route) for testing")
    print(f"Using {max_workers} parallel workers")

    # Process images in parallel
    successful = 0
    failed = 0

    with ProcessPoolExecutor(max_workers=max_workers) as executor, open(
        output_file, "w", encoding="utf-8"
    ) as fout:
        # Create partial function with route_stations
        parse_func = partial(parse_timetable_image, route_stations=route_stations)

        # Submit all tasks
        future_to_path = {
            executor.submit(parse_func, str(image_path)): image_path
            for image_path in sorted(image_files)
        }

        # Process completed tasks
        n = len(future_to_path)
        for i, future in enumerate(as_completed(future_to_path)):
            results_list = future.result()
            for result in results_list:
                print(json.dumps(result, ensure_ascii=False), file=fout, flush=True)

                if "error" not in result:
                    successful += 1
                    print(f"✅ [{i}/{n}]: {result['filename']}")
                else:
                    failed += 1
                    print(
                        f"❌ [{i}/{n}]: {result['filename']}: {result.get('error', 'Unknown error')}"
                    )

    print(f"\nResults written to {output_file}")
    print(f"Successfully processed: {successful}")
    print(f"Failed: {failed}")


if __name__ == "__main__":
    main()
