import json
import math
import os
import statistics
import sys
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import (
    END_YEAR,
    EXCLUDED_CATEGORIES,
    EXCLUDED_NAME_PARTS,
    EXCLUDED_PACKAGING_PARTS,
    EXCLUDED_THEMES,
    MIN_YEARS_SINCE_RELEASE,
    RRP_MIN_USD,
    START_YEAR,
)

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except Exception:
    pass


def env(name, default=None):
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value


def today_utc():
    return datetime.now(timezone.utc).date()


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_date(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    return None


def safe_float(value):
    if value is None or value == "":
        return None
    if isinstance(value, str):
        value = value.strip().replace(",", "").replace("$", "")
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def safe_int(value):
    number = safe_float(value)
    if number is None:
        return None
    return int(number)


def load_json(path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        temp_name = handle.name
    Path(temp_name).replace(path)


def set_number(record):
    raw = str(record.get("number") or "").strip()
    if not raw:
        raw = str(record.get("setNumber") or "").strip()
    if not raw:
        return ""
    if "-" in raw:
        return raw
    variant = record.get("numberVariant")
    if variant is None:
        return raw
    return f"{raw}-{variant}"


def image_url(record):
    image = record.get("image")
    if isinstance(image, dict):
        return image.get("imageURL") or image.get("thumbnailURL") or ""
    if isinstance(image, str):
        return image
    return record.get("imageURL") or record.get("thumbnailURL") or ""


def retail_price_us(record):
    candidates = [record.get("USRetailPrice")]
    lego_com = record.get("LEGOCom")
    if isinstance(lego_com, dict):
        us = lego_com.get("US")
        if isinstance(us, dict):
            candidates.extend([us.get("retailPrice"), us.get("price")])
    for candidate in candidates:
        price = safe_float(candidate)
        if price is not None and price > 0:
            return round(price, 2)
    return None


def theme_name(record):
    theme = str(record.get("theme") or "").strip()
    return theme or "기타"


def normalized_name(record):
    return " ".join(str(record.get("name") or "").split())


def exclusion_reason(record, today=None):
    today = today or today_utc()
    set_no = set_number(record)
    name = normalized_name(record).lower()
    theme = theme_name(record).lower()
    category = str(record.get("category") or "").strip().lower()
    packaging = str(record.get("packagingType") or "").strip().lower()
    is_cmf = "collectable minifigure" in category or "collectible minifigure" in category

    if not set_no:
        return "missing_set_number"
    if theme in EXCLUDED_THEMES:
        return "excluded_theme"
    if category in EXCLUDED_CATEGORIES:
        return "excluded_category"
    if any(part in name for part in EXCLUDED_NAME_PARTS):
        return "excluded_name"
    if not is_cmf and any(part in packaging for part in EXCLUDED_PACKAGING_PARTS):
        return "excluded_packaging"

    launch = parse_date(record.get("launchDate"))
    exit_date = parse_date(record.get("exitDate"))
    if launch is None:
        return "missing_launch_date"
    if exit_date is None:
        return "missing_exit_date"
    if exit_date >= today:
        return "not_retired"
    if launch.year < START_YEAR or launch.year > END_YEAR:
        return "year_out_of_range"

    rrp = retail_price_us(record)
    if rrp is None:
        return "missing_rrp"
    if abs(rrp - launch.year) < 0.01:
        return "invalid_rrp"
    if rrp < RRP_MIN_USD:
        return "rrp_below_min"

    years = (today - launch).days / 365.25
    if years < MIN_YEARS_SINCE_RELEASE:
        return "too_new"
    return None


def normalize_brickset(record, today=None):
    today = today or today_utc()
    launch = parse_date(record.get("launchDate"))
    exit_date = parse_date(record.get("exitDate"))
    rrp = retail_price_us(record)
    category = str(record.get("category") or "").strip()
    return {
        "set_number": set_number(record),
        "brickset_id": record.get("setID"),
        "name": normalized_name(record),
        "theme": theme_name(record),
        "theme_group": str(record.get("themeGroup") or "").strip(),
        "subtheme": str(record.get("subtheme") or "").strip(),
        "category": category,
        "is_cmf": "collectable minifigure" in category.lower()
        or "collectible minifigure" in category.lower(),
        "year": safe_int(record.get("year")) or (launch.year if launch else None),
        "launch_date": launch.isoformat() if launch else None,
        "exit_date": exit_date.isoformat() if exit_date else None,
        "launch_date_estimated": bool(record.get("releaseDateEstimated")),
        "exit_date_estimated": bool(record.get("exitDateEstimated")),
        "retired": bool(exit_date and exit_date < today),
        "pieces": safe_int(record.get("pieces")) or 0,
        "minifigs": safe_int(record.get("minifigs")) or 0,
        "rrp_usd": rrp,
        "image": image_url(record),
        "brickset_url": record.get("bricksetURL")
        or f"https://brickset.com/sets/{set_number(record)}",
        "bricklink_url": f"https://www.bricklink.com/v2/catalog/catalogitem.page?S={set_number(record)}",
        "source_url": str(record.get("source_url") or "").strip(),
        "availability": str(record.get("availability") or "").strip(),
        "packaging_type": str(record.get("packagingType") or "").strip(),
        "rating": safe_float(record.get("rating")),
        "review_count": safe_int(record.get("reviewCount")) or 0,
        "want_count": safe_int(record.get("wantCount")) or 0,
        "owned_count": safe_int(record.get("ownedCount")) or 0,
        "confidence": str(record.get("confidence") or "").strip(),
        "raw_year": record.get("year"),
    }


def extract_price_guide(payload):
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    if not isinstance(data, dict):
        return None
    avg = safe_float(data.get("avg_price"))
    if avg is None or avg <= 0:
        return None
    details = data.get("price_detail")
    if not isinstance(details, list):
        details = []
    quantity = safe_int(data.get("total_quantity"))
    if quantity is None:
        quantity = sum(safe_int(item.get("quantity")) or 0 for item in details)
    lots = safe_int(data.get("unit_quantity"))
    if lots is None:
        lots = len(details)
    seller_count = safe_int(data.get("seller_count"))
    if seller_count is None:
        seller_count = sum(safe_int(item.get("seller_count")) or 0 for item in details)
    return {
        "avg_price": round(avg, 2),
        "min_price": round(safe_float(data.get("min_price")) or avg, 2),
        "max_price": round(safe_float(data.get("max_price")) or avg, 2),
        "quantity": quantity or 0,
        "lots": lots or 0,
        "sellers": seller_count or 0,
        "currency": str(data.get("currency_code") or ""),
        "new_or_used": str(data.get("new_or_used") or ""),
    }


def median(values):
    cleaned = [value for value in values if value is not None]
    if not cleaned:
        return None
    return round(statistics.median(cleaned), 4)


def mean(values):
    cleaned = [value for value in values if value is not None]
    if not cleaned:
        return None
    return round(sum(cleaned) / len(cleaned), 4)


def cagr(multiple, years):
    if multiple is None or years is None or multiple <= 0 or years < 0.5:
        return None
    return multiple ** (1.0 / years) - 1.0


def month_key(value):
    if isinstance(value, str):
        value = parse_date(value)
    if value is None:
        return None
    return f"{value.year:04d}-{value.month:02d}"


def rrp_band(rrp):
    from config import RRP_BANDS

    if rrp is None:
        return None
    for label, low, high in RRP_BANDS:
        if low <= rrp < high:
            return label
    return None


def round_or_none(value, digits=4):
    if value is None:
        return None
    return round(value, digits)


def compact_number(value):
    if value is None:
        return "-"
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if abs(value) >= 1_000:
        return f"{value / 1_000:.1f}K"
    return f"{value:.0f}"
