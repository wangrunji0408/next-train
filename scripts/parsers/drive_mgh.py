#!/usr/bin/env python3
"""Robust driver: parse each image in a separate subprocess so Vision crashes
only lose that one image. Appends to data/lines/{line}.jsonl (resumable)."""
import subprocess, sys, json, os
from pathlib import Path

lines = sys.argv[1:] or ['4', '14', '16', '17']
root = Path(os.path.dirname(os.path.abspath(__file__))).parent.parent
outdir = root / 'data' / 'lines'
python = root / '.venv' / 'bin' / 'python'
worker = Path(os.path.dirname(os.path.abspath(__file__))) / 'parse_one_mgh.py'
timetables = root / 'timetables'

for line in lines:
    images = sorted(timetables.glob(f'{line}-*.jpg'))
    outfile = outdir / f'{line}.jsonl'
    outfile.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if outfile.exists():
        for l in outfile.read_text(encoding='utf-8').splitlines():
            if l.strip():
                try:
                    done.add(json.loads(l)['filename'])
                except Exception:
                    pass
    ok = fail = 0
    with open(outfile, 'a', encoding='utf-8') as fo:
        for i, img in enumerate(images, 1):
            if img.name in done:
                ok += 1
                continue
            try:
                proc = subprocess.run(
                    [str(python), str(worker), line, str(img)],
                    capture_output=True, text=True, timeout=180,
                    cwd=str(root))
            except subprocess.TimeoutExpired:
                print(f'[{line} {i}/{len(images)}] TIMEOUT {img.name}', flush=True)
                fail += 1
                continue
            if proc.returncode == 0 and proc.stdout.strip():
                fo.write(proc.stdout.strip() + '\n')
                fo.flush()
                ok += 1
                if ok % 5 == 0:
                    print(f'[{line} {i}/{len(images)}] ok={ok} fail={fail}', flush=True)
            else:
                fail += 1
                print(f'[{line} {i}/{len(images)}] FAIL {img.name} rc={proc.returncode}', flush=True)
    print(f'=== DONE {line}: ok={ok} fail={fail} ===', flush=True)
