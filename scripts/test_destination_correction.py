#!/usr/bin/env python3
"""
Test script for destination auto-correction functionality.
Reads destinations from destinations.txt and shows before/after corrections.
"""

import csv
from pathlib import Path
from parse_timetables import parse_station_names_from_files, auto_correct_destination


def main():
    """Test destination auto-correction on destinations.txt"""

    # Parse station names from image files
    timetables_dir = Path("timetables")
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

    print(f"Building station reference from {len(image_files)} image files...")
    route_stations = parse_station_names_from_files(image_files)
    print(f"Found stations for {len(route_stations)} routes")

    # Print route stations for reference
    print("\n=== Station names by route ===")
    for route, stations in sorted(route_stations.items()):
        print(f"Route {route}: {', '.join(sorted(stations))}")

    # Read destinations.txt
    destinations_file = Path("destinations.txt")
    if not destinations_file.exists():
        print(f"Error: {destinations_file} not found")
        return

    print(f"\n=== Testing auto-correction on {destinations_file} ===")

    corrections_made = 0
    total_entries = 0
    failed_entries = 0

    # Store all results for sorting
    results = []

    with open(destinations_file, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader, None)  # Skip header

        if header:
            print(f"Header: {header}")

        for row in reader:
            if len(row) >= 2:
                route = row[0].strip()
                destination = row[1].strip()

                if not destination:  # Skip empty destinations
                    continue

                total_entries += 1

                # Apply auto-correction
                corrected = auto_correct_destination(destination, route, route_stations)

                # Check if corrected result is a valid station name
                is_valid_station = (
                    route in route_stations and corrected in route_stations[route]
                )

                if not is_valid_station:
                    status = "❌ FAILED"
                    status_priority = 3
                    failed_entries += 1
                elif corrected != destination:
                    status = "✓ CORRECTED"
                    status_priority = 1
                    corrections_made += 1
                else:
                    status = "✓ OK"
                    status_priority = 2

                results.append((status_priority, route, destination, corrected, status))

    # Sort results: first by status priority, then by route
    results.sort(key=lambda x: (x[0], x[1]))

    # Print sorted results
    print(f"{'Route':<8} {'Original':<20} {'Corrected':<20} {'Status'}")
    print("-" * 60)

    for _, route, destination, corrected, status in results:
        print(f"{route:<8} {destination:<20} {corrected:<20} {status}")

    print("-" * 60)
    print(f"Total entries: {total_entries}")
    print(f"Corrections made: {corrections_made}")
    print(f"Failed entries: {failed_entries}")
    print(
        f"Success rate: {(total_entries-failed_entries)/total_entries*100:.1f}%"
        if total_entries > 0
        else "No entries"
    )
    print(
        f"Correction rate: {corrections_made/total_entries*100:.1f}%"
        if total_entries > 0
        else "No entries"
    )


if __name__ == "__main__":
    main()
