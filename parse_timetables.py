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


def group_text_by_lines(annotations: List[Tuple], eps: float = 1e-2) -> List[List[str]]:
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
        match = re.search(r"开往(.+?)方向", line_text)
        if match:
            return match.group(1).strip()
    return None


def extract_operating_time(lines: List[List[str]]) -> Optional[str]:
    """
    Extract operating time by finding "工作日" or "双休日"
    """
    for line in lines:
        line_text = "".join(line)
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
        line_text = "".join([c for c in line if c.isnumeric()])
        if not line_text:
            continue

        # Check if first number is an hour (4-23)
        try:
            if line_text[:6] == "521521":
                continue  # skip footer
            if line_text[0] in "456789":
                hour = int(line_text[0])
                line_text = line_text[1:]  # Remove hour from text
            elif (
                line_text[0:2] in [str(x) for x in range(10, 24)]
                or line_text[0:2] == "00"
            ):
                hour = int(line_text[0:2])
                line_text = line_text[2:]  # Remove hour from text

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

    schedule_times.sort()
    return schedule_times


def convert_and_binarize_image(image_path: str) -> List[Image.Image]:
    """
    Convert image to PNG format, apply binarization for better OCR, and split if tall vertical

    Args:
        image_path: Path to image file

    Returns:
        List of processed images (1 for normal images, 2 for split tall images)
    """

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

        # Check if image is tall vertical (height/width > 3/2, which is aspect ratio > 2:3)
        if height / width > 1.5:
            # Split into two equal height parts
            half_height = height // 2
            top_img = img.crop((0, 0, width, half_height))
            bottom_img = img.crop((0, half_height, width, height))
            images = [top_img, bottom_img]
        else:
            images = [img]

        processed_images = []
        for image in images:
            # Apply binarization
            img_array = np.array(image)
            threshold = 64

            # Apply threshold
            binary_array = (img_array > threshold).astype(np.uint8) * 255
            binary_img = Image.fromarray(binary_array, mode="L")
            processed_images.append(binary_img)

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


def parse_timetable_image(image_path: str) -> List[Dict]:
    """
    Parse a single timetable image and extract all information
    Returns list of results (multiple if image was split)
    """
    try:
        # Convert and binarize image for better OCR (may return multiple images if split)
        images = convert_and_binarize_image(image_path)

        os.makedirs("annotations", exist_ok=True)
        results = []

        for i, image in enumerate(images):
            suffix = f"_part{i+1}" if len(images) > 1 else ""
            annotation_path = f"annotations/{Path(image_path).stem}{suffix}.png"

            # Perform OCR
            ocr = ocrmac.OCR(image, framework="livetext")
            annotations = ocr.recognize()
            ocr.annotate_PIL().save(annotation_path)

            # Group text by lines
            lines = group_text_by_lines(annotations)

            # Extract information
            destination = extract_destination(lines)
            operating_time = extract_operating_time(lines)
            schedule_times = extract_schedule_times(lines)
            route, station = extract_route_and_station(image_path)

            # Debug
            # print(f"{route} {station} {destination} {operating_time}")
            # minutes = {}
            # for time in schedule_times:
            #     hour, minute = map(int, time.split(":"))
            #     minutes[hour] = minutes.get(hour, []) + [minute]
            # for hour, mins in sorted(minutes.items(), key=lambda x: x[0]):
            #     print(f"{hour:02}:", end="")
            #     for minute in mins:
            #         print(f" {minute:02}", end="")
            #     print()

            result = {
                "filename": os.path.basename(image_path) + suffix,
                "route": route,
                "station": station,
                "destination": destination,
                "operating_time": operating_time,
                "schedule_times": schedule_times,
                "status": "success",
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
                "status": "error",
                "error": str(e),
            }
        ]


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
    successful = 0
    failed = 0

    # image_files = [sorted(image_files)[0]]

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks
        future_to_path = {
            executor.submit(parse_timetable_image, str(image_path)): image_path
            for image_path in sorted(image_files)
        }

        # Process completed tasks
        with open(output_file, "w", encoding="utf-8") as f:
            for future in as_completed(future_to_path):
                results_list = future.result()
                for result in results_list:
                    print(json.dumps(result, ensure_ascii=False), file=f)

                    if result["status"] == "success":
                        successful += 1
                        print(
                            f"✓ {result['filename']}: {result['route']}-{result['station']} "
                        )
                    else:
                        failed += 1
                        print(
                            f"✗ {result['filename']}: {result.get('error', 'Unknown error')}"
                        )

    print(f"\nResults written to {output_file}")
    print(f"Successfully processed: {successful}")
    print(f"Failed: {failed}")


if __name__ == "__main__":
    main()
