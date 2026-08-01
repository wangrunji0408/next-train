#!/usr/bin/env python3
"""OCR一张图片，输出文本行布局，帮助理解各线路格式"""
import sys
import os
sys.path.insert(0, os.path.expanduser("~/Codes/next-train/scripts"))
from ocrmac import ocrmac
from PIL import Image
from parse_timetables import group_text_by_lines, convert_and_binarize_image

def analyze(path, binary=True):
    print(f"\n{'='*70}\n分析: {os.path.basename(path)}")
    pairs = convert_and_binarize_image(path)
    for i, (gray, binimg) in enumerate(pairs):
        img = binimg if binary else gray
        ocr = ocrmac.OCR(img, framework="livetext")
        anns = ocr.recognize()
        lines = group_text_by_lines(anns)
        print(f"\n--- 分割块{i+1}: {len(lines)}行 ---")
        for j, line in enumerate(lines):
            parts = []
            for item in line:
                if isinstance(item, (tuple, list)) and len(item) >= 2:
                    parts.append(item[0])
                else:
                    parts.append(str(item))
            joined = " | ".join(parts)
            print(f"{j:3d}: {joined}")

if __name__ == "__main__":
    analyze(sys.argv[1], binary=(len(sys.argv) < 3 or sys.argv[2] != "gray"))
