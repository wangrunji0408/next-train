#!/usr/bin/env python3
"""Batch-run the dedicated parser for a line, with retry. Moderate parallelism."""
import json, os, sys, time
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from parse_lines_standard import parse_image

def process(path, minute_img="gray"):
    for attempt in range(3):
        try:
            rec, info = parse_image(path, minute_img=minute_img)
            if rec is not None:
                return path, rec, None
            if info and info.get("error") == "summary_card":
                return path, None, info  # summary card: don't retry
            if attempt < 2:
                time.sleep(1.0 * (attempt + 1))
        except Exception as e:
            if attempt < 2:
                time.sleep(1.0 * (attempt + 1))
            else:
                return path, None, {"exception": str(e)}
    return path, None, info

def main():
    line = sys.argv[1]
    minute_img = sys.argv[2] if len(sys.argv) > 2 else "gray"
    project_root = Path(__file__).resolve().parent.parent.parent
    out = sys.argv[3] if len(sys.argv) > 3 else str(project_root / f"data/lines/{line}.jsonl")
    workers = int(sys.argv[4]) if len(sys.argv) > 4 else 3
    timetables_dir = project_root / "timetables"
    images = sorted(timetables_dir.glob(f"{line}-*.jpg"))
    if not images:
        images = sorted([p for p in timetables_dir.glob("*.jpg") if p.stem.split("-")[0] == line])
    print(f"Line {line}: {len(images)} images, minute_img={minute_img}, workers={workers}", flush=True)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    results = {}
    fails = {}
    skips = {}
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(process, str(p), minute_img): p for p in images}
        done = 0
        for fut in as_completed(futs):
            p, rec, err = fut.result()
            done += 1
            name = Path(p).name
            if rec is None:
                if err and err.get("error") == "summary_card":
                    skips[name] = err
                else:
                    fails[name] = err
            else:
                results[name] = rec
            if done % 15 == 0:
                print(f"  {done}/{len(images)} done, {len(fails)} fails, {len(skips)} skips", flush=True)
    with open(out, "w", encoding="utf-8") as f:
        for name in sorted(results):
            f.write(json.dumps(results[name], ensure_ascii=False) + "\n")
    print(f"Done: {len(results)} ok, {len(fails)} fail, {len(skips)} summary-card skips -> {out}")
    for name, info in list(fails.items())[:30]:
        print(f"  FAIL {name}: {info}")
    for name in sorted(skips):
        print(f"  SKIP {name}: summary card")

if __name__ == "__main__":
    main()
