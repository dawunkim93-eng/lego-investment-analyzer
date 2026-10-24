import json
import random
import subprocess
import sys
from datetime import date
from pathlib import Path

from common import save_json
from config import ROOT

DEMO_DIR = ROOT / "data" / "demo"
RAW_DIR = DEMO_DIR / "raw"
PRICES_DIR = RAW_DIR / "bricklink"
SAMPLE_JSON = ROOT / "data" / "sets.sample.json"
SAMPLE_COVERAGE = ROOT / "data" / "coverage.sample.json"
SAMPLE_REPORT = ROOT / "report" / "LEGO_재테크_분석_샘플.md"

THEMES = (
    ("Star Wars", "Ultimate Collector Series"),
    ("Technic", "Normal"),
    ("Icons", "Modular Buildings"),
    ("Ideas", "Normal"),
    ("Harry Potter", "Normal"),
    ("Creator Expert", "Normal"),
    ("City", "Normal"),
    ("Ninjago", "Normal"),
    ("Marvel Super Heroes", "Normal"),
    ("Disney", "Normal"),
    ("Speed Champions", "Normal"),
    ("Friends", "Normal"),
    ("Minecraft", "Normal"),
    ("Architecture", "Normal"),
    ("Seasonal", "Normal"),
)

RRPS = (20, 25, 30, 40, 50, 60, 80, 100, 120, 150, 200, 250, 300, 400, 500)


def build_cpi():
    rows = ["observation_date,CPIAUCSL"]
    value = 130.0
    for year in range(1990, 2027):
        for month in range(1, 13):
            if year == 2026 and month > 10:
                break
            value *= 1.0 + (0.024 / 12.0)
            rows.append(f"{year:04d}-{month:02d}-01,{value:.4f}")
    path = RAW_DIR / "cpi.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


def make_payload(set_no, name, condition, avg, qty, lots):
    low = round(avg * 0.82, 2)
    high = round(avg * 1.22, 2)
    detail = []
    if lots > 0:
        for index in range(min(lots, 8)):
            detail.append(
                {
                    "quantity": max(1, qty // max(1, lots)),
                    "seller_count": max(1, lots // 4),
                    "price": str(round(low + (high - low) * index / 8, 2)),
                }
            )
    return {
        "meta": {"code": 200, "message": "OK", "description": "demo"},
        "data": {
            "item": {
                "no": set_no,
                "type": "SET",
                "name": name,
            },
            "new_or_used": "N" if condition == "new" else "U",
            "currency_code": "USD",
            "min_price": str(low),
            "max_price": str(high),
            "avg_price": str(round(avg, 2)),
            "qty_avg_price": str(round(avg, 2)),
            "unit_quantity": lots,
            "total_quantity": qty,
            "price_detail": detail,
        },
    }


def main():
    rng = random.Random(42)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    PRICES_DIR.mkdir(parents=True, exist_ok=True)
    as_of = date(2026, 10, 24)
    records = []

    for index in range(1, 73):
        theme, subtheme = THEMES[(index - 1) % len(THEMES)]
        release_year = rng.randint(2004, 2021)
        lifespan = rng.randint(2, 6)
        exit_year = min(release_year + lifespan, 2024)
        launch = date(release_year, rng.randint(1, 12), rng.randint(1, 27))
        exit_date = date(exit_year, rng.randint(1, 12), rng.randint(1, 27))
        if exit_date <= launch:
            exit_date = date(exit_year + 1, 6, 1)
        rrp = rng.choice(RRPS)
        set_no = f"9{index:04d}"
        name = f"샘플 {theme} 세트 {index:02d}"
        records.append(
            {
                "setID": 100000 + index,
                "number": set_no,
                "numberVariant": 1,
                "name": name,
                "year": release_year,
                "theme": theme,
                "themeGroup": theme,
                "subtheme": subtheme,
                "category": "Normal",
                "launchDate": f"{launch.isoformat()}T00:00:00",
                "exitDate": f"{exit_date.isoformat()}T00:00:00",
                "pieces": rng.randint(150, 7500),
                "minifigs": rng.randint(0, 25),
                "USRetailPrice": f"{rrp:.2f}",
                "image": {"imageURL": "", "thumbnailURL": ""},
                "bricksetURL": f"https://brickset.com/sets/{set_no}-1",
                "packagingType": "Box",
                "availability": "retail",
                "wantCount": rng.randint(0, 5000),
                "rating": round(rng.uniform(3.2, 4.9), 1),
                "reviewCount": rng.randint(0, 200),
            }
        )

        years = (as_of - launch).days / 365.25
        annual = rng.gauss(0.055, 0.065)
        if index % 17 == 0:
            annual = rng.uniform(0.18, 0.28)
        if index % 23 == 0:
            annual = rng.uniform(-0.06, -0.01)
        new_price = rrp * (1.0 + annual) ** max(1.0, years)
        new_price = min(rrp * 12.0, max(rrp * 0.55, new_price))
        used_price = new_price * rng.uniform(0.58, 0.86)
        new_qty = max(1, int(rng.lognormvariate(3.0, 1.0)))
        used_qty = max(1, int(rng.lognormvariate(3.2, 1.0)))
        lots = max(1, int(new_qty / 3))
        used_lots = max(1, int(used_qty / 3))

        save_json(
            PRICES_DIR / f"{set_no}-1__new_sold.json",
            make_payload(set_no, name, "new", new_price, new_qty, lots),
        )
        save_json(
            PRICES_DIR / f"{set_no}-1__used_sold.json",
            make_payload(set_no, name, "used", used_price, used_qty, used_lots),
        )

    save_json(
        RAW_DIR / "brickset.json",
        {
            "fetched_at": "2026-10-24T00:00:00+00:00",
            "demo": True,
            "count": len(records),
            "sets": records,
        },
    )
    build_cpi()

    command = [
        sys.executable,
        str(ROOT / "scripts" / "build_dataset.py"),
        "--input",
        str(RAW_DIR / "brickset.json"),
        "--prices-dir",
        str(PRICES_DIR),
        "--cpi",
        str(RAW_DIR / "cpi.csv"),
        "--out",
        str(SAMPLE_JSON),
        "--coverage-out",
        str(SAMPLE_COVERAGE),
        "--report",
        str(SAMPLE_REPORT),
        "--as-of",
        as_of.isoformat(),
    ]
    subprocess.run(command, check=True)

    document = json.loads(SAMPLE_JSON.read_text(encoding="utf-8"))
    document["meta"]["demo"] = True
    document["meta"]["source"] = "DEMO"
    document["meta"]["demo_note"] = "UI 확인용 가상 데이터입니다. 실제 분석 결과가 아닙니다."
    save_json(SAMPLE_JSON, document)
    if SAMPLE_REPORT.exists():
        report = SAMPLE_REPORT.read_text(encoding="utf-8")
        report = report.replace(
            "- 데이터: Brickset + BrickLink",
            "- 데이터: DEMO (가상 데이터, 실제 분석 아님)",
        )
        report = report.replace(
            "# LEGO 재테크 분석 리포트",
            "# LEGO 재테크 분석 리포트 (샘플)\n\n> UI 확인용 가상 데이터입니다. 실제 분석 결과가 아닙니다.",
        )
        SAMPLE_REPORT.write_text(report, encoding="utf-8")
    print(f"샘플 데이터: {SAMPLE_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
