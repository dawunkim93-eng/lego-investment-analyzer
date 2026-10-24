import argparse
import csv
import io
import sys
from pathlib import Path

import requests

from config import CPI_RAW, CPI_URL


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=CPI_URL)
    parser.add_argument("--out", default=str(CPI_RAW))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    out = Path(args.out)
    if out.exists() and not args.force:
        print(f"이미 존재: {out} (갱신하려면 --force)")
        return 0

    response = requests.get(
        args.url,
        timeout=60,
        headers={"User-Agent": "lego-investment-analyzer/1.0"},
    )
    response.raise_for_status()
    text = response.text
    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        print("CPI 데이터가 비어 있습니다.")
        return 1

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    last = rows[-1]
    print(f"저장: {out}")
    print(f"행 수: {len(rows)}")
    print(f"최신: {last.get('observation_date')} = {last.get('CPIAUCSL')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
