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
from ocrmac import ocrmac
from PIL import Image


def group_text_by_lines(annotations: List[Tuple], eps: float = 1e-3) -> List[List[str]]:
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
    sorted_annotations = sorted(annotations, key=lambda x: x[2][1])

    lines = []
    current_line = [sorted_annotations[0][0]]
    current_y = sorted_annotations[0][2][1]

    for annotation in sorted_annotations[1:]:
        y_coord = annotation[2][1]

        if abs(y_coord - current_y) <= eps:
            # Same line
            current_line.append(annotation[0])
        else:
            # New line
            lines.append(current_line)
            current_line = [annotation[0]]
            current_y = y_coord

    # Add the last line
    if current_line:
        lines.append(current_line)

    return lines


def extract_destination(lines: List[List[str]]) -> Optional[str]:
    """
    Extract destination by finding pattern "开往XXX方向"
    """
    for line in lines:
        line_text = " ".join(line)
        match = re.search(r"开往(.+?)方向", line_text)
        if match:
            return match.group(1).strip()
    return None


def extract_operating_time(lines: List[List[str]]) -> Optional[str]:
    """
    Extract operating time by finding "工作日" or "双休日"
    """
    for line in lines:
        line_text = " ".join(line)
        if "工作日" in line_text:
            return "工作日"
        elif "双休日" in line_text:
            return "双休日"
    return None


def extract_schedule_times(lines: List[List[str]]) -> List[str]:
    """
    Extract schedule times from lines starting with hours 4-23
    """
    schedule_times = []

    for line in lines:
        line_text = " ".join(line)

        # Find all numbers in the line
        numbers = re.findall(r"\d+", line_text)

        if not numbers:
            continue

        # Check if first number is an hour (4-23)
        try:
            first_num = int(numbers[0])
            if 4 <= first_num <= 23:
                # This is a schedule line
                hour = first_num

                # Process remaining numbers as minutes
                for minute_str in numbers[1:]:
                    try:
                        minute = int(minute_str)
                        if 0 <= minute <= 59:  # Valid minute
                            schedule_times.append(f"{hour:02d}:{minute:02d}")
                    except ValueError:
                        continue

        except ValueError:
            continue

    return schedule_times


def convert_jpg_to_png(jpg_path: str) -> str:
    """
    Convert JPG image to PNG format and save in png folder

    Args:
        jpg_path: Path to JPG file

    Returns:
        Path to converted PNG file
    """
    if not Image:
        raise ImportError("PIL module is required for image conversion")

    # Create png directory if it doesn't exist
    png_dir = Path("timetables/png")
    png_dir.mkdir(exist_ok=True)

    # Get filename without extension and create PNG path
    filename = Path(jpg_path).stem
    png_path = png_dir / f"{filename}.png"

    if png_path.exists():
        return str(png_path)

    with Image.open(jpg_path) as img:
        # Convert CMYK to RGB if necessary
        if img.mode == "CMYK":
            img = img.convert("RGB")
        # Convert other modes to RGB for PNG compatibility
        elif img.mode not in ("RGB", "RGBA", "L", "LA"):
            img = img.convert("RGB")

        img.save(png_path, "PNG")

    return str(png_path)


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


def parse_timetable_image(image_path: str) -> Dict:
    """
    Parse a single timetable image and extract all information
    """
    try:
        # Convert JPG to PNG if needed
        if image_path.lower().endswith((".jpg", ".jpeg")):
            image_path = convert_jpg_to_png(image_path)

        # Perform OCR
        annotations = ocrmac.OCR(image_path, framework="livetext").recognize()

        # Group text by lines
        lines = group_text_by_lines(annotations)

        # Extract information
        destination = extract_destination(lines)
        operating_time = extract_operating_time(lines)
        schedule_times = extract_schedule_times(lines)
        route, station = extract_route_and_station(image_path)

        return {
            "filename": os.path.basename(image_path),
            "route": route,
            "station": station,
            "destination": destination,
            "operating_time": operating_time,
            "schedule_times": schedule_times,
            "total_schedules": len(schedule_times),
            "status": "success",
        }
    except Exception as e:
        return {
            "filename": os.path.basename(image_path),
            "route": None,
            "station": None,
            "destination": None,
            "operating_time": None,
            "schedule_times": [],
            "total_schedules": 0,
            "status": "error",
            "error": str(e),
        }


def main():
    """
    Process all timetable images in parallel and output to JSONL
    """
    timetables_dir = Path("timetables")
    output_file = "timetable_schedules.jsonl"
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
    print(f"Using {max_workers} parallel workers")

    # Process images in parallel
    results = []
    successful = 0
    failed = 0

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks
        future_to_path = {
            executor.submit(parse_timetable_image, str(image_path)): image_path
            for image_path in sorted(image_files)
        }

        # Process completed tasks
        for future in as_completed(future_to_path):
            image_path = future_to_path[future]
            result = future.result()
            results.append(result)

            if result["status"] == "success":
                successful += 1
                print(
                    f"✓ {result['filename']}: {result['route']}-{result['station']} "
                    f"({result['total_schedules']} schedules)"
                )
            else:
                failed += 1
                print(f"✗ {result['filename']}: {result.get('error', 'Unknown error')}")

    # Sort results by filename for consistent output
    results.sort(key=lambda x: x["filename"])

    # Write results to JSONL
    with open(output_file, "w", encoding="utf-8") as f:
        for result in results:
            f.write(json.dumps(result, ensure_ascii=False) + "\n")

    print(f"\nResults written to {output_file}")
    print(f"Successfully processed: {successful}")
    print(f"Failed: {failed}")
    print(f"Total: {len(results)}")


if __name__ == "__main__":
    main()
