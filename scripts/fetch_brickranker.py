import argparse
import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from common import (
    load_json,
    now_iso,
    parse_date,
    save_json,
    safe_float,
    safe_int,
    today_utc,
)
from config import (
    BRICKRANKER_BASE,
    BRICKRANKER_CACHE_DIR,
    BRICKRANKER_EXCLUDED_THEMES,
    BRICKRANKER_HISTORY_DIR,
    BRICKRANKER_LISTING_DIR,
    BRICKRANKER_PRICES_DIR,
    BRICKRANKER_RAW,
    BRICKRANKER_RETRY_MAX,
    BRICKRANKER_SET_DIR,
    BRICKRANKER_SITEMAP,
    BRICKRANKER_SLEEP,
    BRICKRANKER_USER_AGENT,
    END_YEAR,
    RRP_MIN_USD,
    START_YEAR,
)

MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

EXCLUDED_NAME_PARTS = (
    "polybag",
    "key chain",
    "keychain",
    "magnet",
    "lanyard",
    "poster",
    "sticker",
    "stationery",
    "notebook",
    "pencil",
    "mug",
    "cup",
    "bag tag",
    "coin",
    "patch",
    "tattoo",
    "watch",
    "clock",
    "torch",
    "headlamp",
)


def session():
    client = requests.Session()
    client.headers.update(
        {
            "User-Agent": BRICKRANKER_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
    )
    return client


def fetch_html(client, url, sleep, retries=BRICKRANKER_RETRY_MAX):
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            response = client.get(url, timeout=60)
        except requests.exceptions.TooManyRedirects:
            return None, "redirect_loop"
        except requests.RequestException as error:
            last_error = f"network: {error}"
            time.sleep(min(30, sleep * (2 ** attempt)))
            continue
        if response.status_code == 429:
            time.sleep(min(120, max(10, sleep * (2 ** attempt))))
            last_error = "rate_limited"
            continue
        if response.status_code in (403, 503):
            time.sleep(min(120, max(10, sleep * (2 ** attempt))))
            last_error = f"blocked_{response.status_code}"
            continue
        if response.status_code >= 500:
            time.sleep(min(30, sleep * (2 ** attempt)))
            last_error = f"http_{response.status_code}"
            continue
        if response.status_code == 404:
            return None, "not_found"
        if response.status_code >= 400:
            return None, f"http_{response.status_code}"
        return response.text, None
    return None, last_error or "unknown"


def parse_money(text):
    if not text:
        return None
    cleaned = str(text).replace(",", "").replace("$", "").strip()
    if not cleaned or cleaned in {"-", "—"}:
        return None
    try:
        return round(float(cleaned), 2)
    except ValueError:
        return None


def parse_percent(text):
    if not text:
        return None
    cleaned = str(text).replace("%", "").replace(",", "").strip()
    if not cleaned or cleaned in {"-", "—"}:
        return None
    try:
        return round(float(cleaned) / 100.0, 4)
    except ValueError:
        return None


def parse_int_text(text):
    if text is None:
        return 0
    cleaned = re.sub(r"[^\d]", "", str(text))
    return int(cleaned) if cleaned else 0


def slug_to_name(slug):
    return " ".join(part.capitalize() for part in slug.replace("-", " ").split())


def normalize_set_number(value):
    text = str(value or "").strip()
    if not text:
        return None
    if re.match(r"^[A-Za-z]*\d+", text) and "-" not in text:
        return f"{text}-1"
    return text


def set_number_parts(set_no):
    if not set_no:
        return None, 1
    if "-" in set_no:
        base, variant = set_no.rsplit("-", 1)
        try:
            return base, int(variant)
        except ValueError:
            return set_no, 1
    return set_no, 1


def sitemap_urls(client, force, sleep):
    cache = BRICKRANKER_CACHE_DIR / "themes-sitemap.xml"
    if cache.exists() and not force:
        text = cache.read_text(encoding="utf-8")
    else:
        text, error = fetch_html(client, BRICKRANKER_SITEMAP, sleep)
        if not text:
            raise RuntimeError(f"sitemap 실패: {error}")
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(text, encoding="utf-8")
    locs = re.findall(r"<loc>(.*?)</loc>", text)
    urls = []
    for loc in locs:
        path = loc.split("/brickranker/public", 1)[-1]
        if not path.startswith("/themes/"):
            continue
        if "/sets?year=" not in path:
            continue
        match = re.search(r"/themes/([^/]+)/sets\?year=(\d{4})", path)
        if not match:
            continue
        slug, year = match.group(1), int(match.group(2))
        if slug in BRICKRANKER_EXCLUDED_THEMES:
            continue
        urls.append(
            {
                "slug": slug,
                "year": year,
                "url": f"{BRICKRANKER_BASE}{path}",
            }
        )
    urls.sort(key=lambda item: (item["slug"], item["year"]))
    return urls


def listing_cache_path(slug, year):
    return BRICKRANKER_LISTING_DIR / f"{slug}-{year}.json"


def parse_listing(html, slug, year):
    soup = BeautifulSoup(html, "lxml")
    title = soup.find("title")
    theme = slug_to_name(slug)
    if title:
        match = re.match(r"LEGO (.+?) Sets \(\d{4}\)", title.get_text(" ", strip=True))
        if match:
            theme = match.group(1).strip()
    table = None
    for candidate in soup.find_all("table"):
        headers = [th.get_text(" ", strip=True) for th in candidate.find_all("th")]
        if "Set No" in headers and "Value" in headers:
            table = candidate
            break
    if table is None:
        return {"slug": slug, "year": year, "theme": theme, "rows": []}
    headers = [th.get_text(" ", strip=True) for th in table.find_all("th")]
    index = {name: headers.index(name) for name in headers}
    rows = []
    for tr in table.find_all("tr"):
        cells = tr.find_all("td")
        if not cells:
            continue
        values = [cell.get_text(" ", strip=True) for cell in cells]
        if len(values) < len(headers):
            continue
        set_no = normalize_set_number(
            values[index["Set No"]] if "Set No" in index else ""
        )
        if not set_no:
            continue
        name = values[index["Name"]] if "Name" in index else ""
        link = tr.find("a", href=lambda value: value and "/rankings/set/" in value)
        url = urljoin(BRICKRANKER_BASE, link["href"]) if link else None
        retired = (
            values[index["Retired"]].strip() if "Retired" in index else ""
        )
        retired_date = parse_date(retired) if retired else None
        value = parse_money(values[index["Value"]]) if "Value" in index else None
        roi = parse_percent(values[index["ROI"]]) if "ROI" in index else None
        derived_rrp = None
        if value is not None and roi is not None and roi > -1:
            derived_rrp = round(value / (1.0 + roi), 2)
        rows.append(
            {
                "set_number": set_no,
                "name": name,
                "pieces": parse_int_text(values[index["Pieces"]])
                if "Pieces" in index
                else 0,
                "year": parse_int_text(values[index["Year"]])
                if "Year" in index
                else year,
                "retired": retired_date.isoformat() if retired_date else None,
                "value": value,
                "roi": roi,
                "derived_rrp": derived_rrp,
                "url": url,
            }
        )
    return {"slug": slug, "year": year, "theme": theme, "rows": rows}


def load_listings(client, urls, force, sleep, max_pages=0):
    BRICKRANKER_LISTING_DIR.mkdir(parents=True, exist_ok=True)
    results = []
    errors = []
    for index, item in enumerate(urls, start=1):
        if max_pages and index > max_pages:
            break
        path = listing_cache_path(item["slug"], item["year"])
        cached = None if force else load_json(path)
        if cached:
            results.append(cached)
            continue
        html, error = fetch_html(client, item["url"], sleep)
        if not html:
            errors.append({"url": item["url"], "error": error})
            print(f"[오류] 목록 {item['slug']} {item['year']}: {error}")
            continue
        parsed = parse_listing(html, item["slug"], item["year"])
        save_json(path, parsed)
        results.append(parsed)
        if index % 25 == 0 or index == len(urls):
            print(
                f"목록 {index}/{len(urls)} · 오류 {len(errors)} · "
                f"세트 {sum(len(row.get('rows') or []) for row in results)}"
            )
        time.sleep(sleep)
    return results, errors


def build_candidates(listings, as_of):
    by_number = {}
    for listing in listings:
        theme = listing.get("theme") or slug_to_name(listing.get("slug") or "")
        for row in listing.get("rows") or []:
            set_no = row.get("set_number")
            if not set_no:
                continue
            item = {**row, "theme": theme, "theme_slug": listing.get("slug")}
            existing = by_number.get(set_no)
            if existing is None:
                by_number[set_no] = item
            else:
                if existing.get("value") is None and item.get("value") is not None:
                    by_number[set_no] = item
                elif existing.get("url") is None and item.get("url"):
                    existing["url"] = item["url"]
    candidates = []
    reasons = {}
    for item in by_number.values():
        set_no = item["set_number"]
        name = str(item.get("name") or "").lower()
        year = item.get("year") or 0
        retired = parse_date(item.get("retired"))
        value = item.get("value")
        derived_rrp = item.get("derived_rrp")
        if retired is not None and retired >= as_of:
            reasons["not_retired"] = reasons.get("not_retired", 0) + 1
            continue
        if retired is None and year > as_of.year - 2:
            reasons["not_retired"] = reasons.get("not_retired", 0) + 1
            continue
        if year < START_YEAR or year > END_YEAR:
            reasons["year_out_of_range"] = reasons.get("year_out_of_range", 0) + 1
            continue
        if value is None:
            reasons["missing_value"] = reasons.get("missing_value", 0) + 1
            continue
        if derived_rrp is not None and derived_rrp < RRP_MIN_USD:
            reasons["rrp_below_min"] = reasons.get("rrp_below_min", 0) + 1
            continue
        if derived_rrp is None and value < 5:
            reasons["low_value_no_rrp"] = reasons.get("low_value_no_rrp", 0) + 1
            continue
        if any(part in name for part in EXCLUDED_NAME_PARTS):
            reasons["excluded_name"] = reasons.get("excluded_name", 0) + 1
            continue
        item["candidate_rrp"] = derived_rrp
        candidates.append(item)
    candidates.sort(key=lambda item: (item.get("value") or 0, item["set_number"]), reverse=True)
    return candidates, reasons


def parse_retired_for(text):
    if not text:
        return None
    years = re.search(r"(\d+)\s+years?", text, re.I)
    months = re.search(r"(\d+)\s+months?", text, re.I)
    if not years and not months:
        return None
    days = 0.0
    if years:
        days += int(years.group(1)) * 365.25
    if months:
        days += int(months.group(1)) * 30.44
    return days


def parse_release_date(text):
    if not text:
        return None
    match = re.search(r"([A-Z][a-z]{2}) (\d{1,2}), (\d{4})", text)
    if not match:
        return None
    month = MONTHS.get(match.group(1).lower())
    if not month:
        return None
    return date(int(match.group(3)), month, int(match.group(2)))


def parse_month_label(label):
    match = re.match(r"([A-Z][a-z]{2}) (\d{2})", (label or "").strip())
    if not match:
        return None
    month = MONTHS.get(match.group(1).lower())
    if not month:
        return None
    year = 2000 + int(match.group(2))
    return f"{year:04d}-{month:02d}"


def recent_window(monthly, as_of):
    cutoff = (as_of - timedelta(days=210)).strftime("%Y-%m")
    recent = [
        row
        for row in monthly
        if row.get("period") and row["period"] >= cutoff
    ]
    return recent[-7:]


def parse_price_history(soup):
    table = None
    for candidate in soup.find_all("table"):
        headers = [th.get_text(" ", strip=True) for th in candidate.find_all("th")]
        if "Month" in headers and "Avg Price" in headers and "Sales" in headers:
            table = candidate
            break
    if table is None:
        return []
    headers = [th.get_text(" ", strip=True) for th in table.find_all("th")]
    month_index = headers.index("Month")
    price_index = headers.index("Avg Price")
    sales_index = headers.index("Sales")
    rows = []
    for tr in table.find_all("tr"):
        cells = tr.find_all("td")
        if len(cells) <= max(month_index, price_index, sales_index):
            continue
        label = cells[month_index].get_text(" ", strip=True)
        price_text = cells[price_index].get_text(" ", strip=True)
        sales_text = cells[sales_index].get_text(" ", strip=True)
        period = parse_month_label(label)
        if not period:
            continue
        rows.append(
            {
                "period": period,
                "label": label,
                "avg_price": parse_money(price_text.replace("(estimated)", "").strip()),
                "sales": parse_int_text(sales_text),
                "estimated": "estimated" in price_text.lower(),
            }
        )
    rows.sort(key=lambda item: item["period"])
    return rows


def parse_set_page(html, set_number, listing, as_of):
    soup = BeautifulSoup(html, "lxml")
    text = " ".join(soup.get_text(" ").split())
    details_start = text.find("Set details")
    details_end = text.find("Set rating", details_start)
    if details_end < 0:
        details_end = details_start + 2500
    details = text[details_start:details_end] if details_start >= 0 else text

    def grab(pattern, source=details):
        match = re.search(pattern, source, re.I)
        return match.group(1).strip() if match else None

    name = grab(r"Name:\s*(.*?)\s*Theme:")
    theme = grab(r"Theme:\s*(.*?)\s*Sub Theme:")
    subtheme = grab(r"Sub Theme:\s*(.*?)\s*Set number:")
    parsed_set_no = grab(r"Set number:\s*(\S+)")
    pieces = parse_int_text(grab(r"Pieces:\s*([\d,]+)"))
    minifigs = parse_int_text(grab(r"Minifigures:\s*([\d,]+)"))
    released_text = grab(r"Released:\s*([A-Z][a-z]{2} \d{1,2}, \d{4})")
    retired_text = grab(r"Retired:\s*([A-Z][a-z]{2} \d{1,2}, \d{4})")
    rrp = parse_money(grab(r"RRP:\s*\$([\d,]+\.\d{2})"))
    confidence = grab(r"Confidence:\s*(High|Medium|Low)")
    current_value = parse_money(grab(r"Current value:\s*\$([\d,]+\.\d{2})"))
    increase = parse_percent(grab(r"Increase from RRP:\s*(-?[\d.]+)%"))
    yearly_roi = parse_percent(grab(r"Yearly ROI:\s*(-?[\d.]+)%"))
    retired_for = grab(r"Retired for:\s*(.*?)\s*Pieces:")
    total_sales = safe_int(grab(r"We have recorded\s+([\d,]+)\s+sales", text))
    if not total_sales:
        total_sales = 0

    released = parse_release_date(released_text)
    retired = parse_release_date(retired_text)
    listing_retired = parse_date(listing.get("retired"))
    if retired is None:
        retired = listing_retired
    if released is None:
        year = listing.get("year")
        released = date(year, 1, 1) if year else None

    if current_value is None:
        current_value = listing.get("value")
    if rrp is None:
        rrp = listing.get("derived_rrp")
    if not theme:
        theme = listing.get("theme")
    if not name:
        name = listing.get("name")
    if not parsed_set_no:
        parsed_set_no = set_number

    monthly = parse_price_history(soup)
    recent = recent_window(monthly, as_of) if monthly else []
    sales_6m = sum(row.get("sales") or 0 for row in recent)
    prices = [row.get("avg_price") for row in recent if row.get("avg_price") is not None]
    if not recent:
        prices = [current_value] if current_value is not None else []
    low = min(prices) if prices else current_value
    high = max(prices) if prices else current_value
    months_with_sales = sum(1 for row in recent if (row.get("sales") or 0) > 0)

    canonical = soup.find("link", rel="canonical")
    source_url = canonical.get("href") if canonical else listing.get("url")
    og_image = soup.find("meta", property="og:image")
    image = og_image.get("content") if og_image else ""
    if image and not image.startswith("http"):
        image = urljoin(BRICKRANKER_BASE, image)

    status = grab(r"Status:\s*(.*?)\s*Retired for:")
    exit_date_estimated = False
    release_date_estimated = False
    if released is None:
        release_date_estimated = True
    if retired is None:
        days = parse_retired_for(retired_for)
        if days and as_of:
            retired = as_of - timedelta(days=days)
            exit_date_estimated = True
        elif released and released.year <= as_of.year - 3:
            retired = released + timedelta(days=730)
            exit_date_estimated = True

    return {
        "set_number": parsed_set_no or set_number,
        "name": name or "",
        "theme": theme or "",
        "subtheme": subtheme or "",
        "theme_slug": listing.get("theme_slug") or "",
        "status": status or "",
        "released_date": released.isoformat() if released else None,
        "retired_date": retired.isoformat() if retired else None,
        "released_date_estimated": release_date_estimated,
        "exit_date_estimated": exit_date_estimated,
        "pieces": pieces or listing.get("pieces") or 0,
        "minifigs": minifigs or 0,
        "rrp_usd": rrp,
        "current_value": current_value,
        "increase_from_rrp": increase,
        "yearly_roi": yearly_roi,
        "confidence": confidence or "",
        "retired_for": retired_for or "",
        "total_sales": total_sales,
        "sales_6m": sales_6m,
        "months_with_sales": months_with_sales,
        "price_low_6m": low,
        "price_high_6m": high,
        "monthly": monthly,
        "image": image,
        "source_url": source_url,
        "candidate_rrp": listing.get("candidate_rrp"),
        "listing_value": listing.get("value"),
        "listing_roi": listing.get("roi"),
        "as_of": as_of.isoformat(),
    }



def search_set(client, set_no, sleep):
    url = f"{BRICKRANKER_BASE}/api/search"
    for attempt in range(1, BRICKRANKER_RETRY_MAX + 1):
        try:
            response = client.get(
                url,
                params={"q": set_no},
                headers={"Accept": "application/json"},
                timeout=60,
            )
        except requests.RequestException:
            time.sleep(min(30, sleep * (2 ** attempt)))
            continue
        if response.status_code == 429:
            time.sleep(min(60, max(10, sleep * (2 ** attempt))))
            continue
        if response.status_code >= 500:
            time.sleep(min(30, sleep * (2 ** attempt)))
            continue
        if response.status_code != 200:
            return None
        try:
            body = response.json()
        except ValueError:
            return None
        for item in (body.get("data") or {}).get("sets") or []:
            if str(item.get("set_num")) == set_no:
                return item
        return None
    return None


def parsed_from_search(search, listing, as_of):
    set_no = listing["set_number"]
    released = parse_date(search.get("released_us")) or parse_date(
        listing.get("retired")
    )
    retired = parse_date(search.get("retired_us"))
    rrp = safe_float(search.get("rrp_us"))
    value = listing.get("value")
    if released is None or retired is None or rrp is None or value is None:
        return None
    if retired >= as_of or rrp < RRP_MIN_USD:
        return None
    if abs(rrp - released.year) < 0.01:
        return None
    base = set_no.split("-", 1)[0]
    return {
        "set_number": set_no,
        "name": str(search.get("name") or listing.get("name") or ""),
        "theme": listing.get("theme") or "",
        "subtheme": "",
        "theme_slug": listing.get("theme_slug") or "",
        "status": "Retired",
        "released_date": released.isoformat(),
        "retired_date": retired.isoformat(),
        "released_date_estimated": False,
        "exit_date_estimated": False,
        "pieces": safe_int(search.get("num_parts")) or listing.get("pieces") or 0,
        "minifigs": 0,
        "rrp_usd": round(rrp, 2),
        "current_value": value,
        "increase_from_rrp": listing.get("roi"),
        "yearly_roi": None,
        "confidence": "Medium",
        "retired_for": "",
        "total_sales": 0,
        "sales_6m": 0,
        "months_with_sales": 0,
        "price_low_6m": value,
        "price_high_6m": value,
        "monthly": [],
        "image": f"{BRICKRANKER_BASE}/img/sets/small/{base}.webp",
        "source_url": listing.get("url")
        or f"{BRICKRANKER_BASE}/rankings/set/{set_no}/x",
        "candidate_rrp": listing.get("candidate_rrp"),
        "listing_value": listing.get("value"),
        "listing_roi": listing.get("roi"),
        "as_of": as_of.isoformat(),
        "fallback_metadata": True,
    }

def set_cache_path(set_no):
    return BRICKRANKER_SET_DIR / f"{set_no.replace('/', '_')}.json"


def price_cache_path(set_no):
    return BRICKRANKER_PRICES_DIR / f"{set_no.replace('/', '_')}__new_sold.json"


def history_cache_path(set_no):
    return BRICKRANKER_HISTORY_DIR / f"{set_no.replace('/', '_')}.json"


def record_for_build(parsed):
    set_no = parsed["set_number"]
    base, variant = set_number_parts(set_no)
    return {
        "setID": None,
        "number": base,
        "numberVariant": variant,
        "name": parsed["name"],
        "year": int(parsed["released_date"][:4]) if parsed["released_date"] else None,
        "theme": parsed["theme"],
        "subtheme": parsed["subtheme"],
        "category": "Collectable Minifigures"
        if "minifig" in parsed["theme_slug"].lower()
        else "Normal",
        "launchDate": f"{parsed['released_date']}T00:00:00"
        if parsed["released_date"]
        else None,
        "exitDate": f"{parsed['retired_date']}T00:00:00"
        if parsed["retired_date"]
        else None,
        "pieces": parsed["pieces"],
        "minifigs": parsed["minifigs"],
        "USRetailPrice": f"{parsed['rrp_usd']:.2f}" if parsed["rrp_usd"] else None,
        "image": {"imageURL": parsed["image"]},
        "bricksetURL": f"https://brickset.com/sets/{set_no}",
        "packagingType": "Box",
        "availability": "retired",
        "wantCount": 0,
        "rating": None,
        "reviewCount": 0,
        "want": 0,
        "source": "BrickRanker",
        "source_url": parsed["source_url"],
        "confidence": parsed["confidence"],
        "yearly_roi_reported": parsed["yearly_roi"],
        "sales_6m": parsed["sales_6m"],
        "releaseDateEstimated": parsed.get("released_date_estimated", False),
        "exitDateEstimated": parsed.get("exit_date_estimated", False),
    }


def price_payload(parsed):
    set_no = parsed["set_number"]
    value = parsed["current_value"]
    if value is None:
        return None
    detail = []
    for row in parsed["monthly"][-7:]:
        detail.append(
            {
                "quantity": row.get("sales") or 0,
                "seller_count": 0,
                "price": f"{row.get('avg_price') or value:.2f}",
            }
        )
    return {
        "meta": {"code": 200, "message": "OK", "description": "BrickRanker"},
        "data": {
            "item": {"no": set_no, "type": "SET", "name": parsed["name"]},
            "new_or_used": "N",
            "currency_code": "USD",
            "min_price": f"{(parsed['price_low_6m'] or value):.2f}",
            "max_price": f"{(parsed['price_high_6m'] or value):.2f}",
            "avg_price": f"{value:.2f}",
            "qty_avg_price": f"{value:.2f}",
            "unit_quantity": parsed["months_with_sales"],
            "total_quantity": parsed["sales_6m"],
            "price_detail": detail,
        },
        "_source": "BrickRanker",
        "_request": {"set_number": set_no, "condition": "new", "guide_type": "sold"},
    }


def listing_candidate_has_value(candidate):
    return candidate.get("value") is not None


def collect_sets(
    client, candidates, force, sleep, max_sets=0, max_requests=0, as_of=None
):
    BRICKRANKER_SET_DIR.mkdir(parents=True, exist_ok=True)
    BRICKRANKER_PRICES_DIR.mkdir(parents=True, exist_ok=True)
    BRICKRANKER_HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    parsed_sets = []
    errors = []
    requests_made = 0
    for index, candidate in enumerate(candidates, start=1):
        if max_sets and len(parsed_sets) >= max_sets:
            break
        if max_requests and requests_made >= max_requests:
            print(f"[중단] 요청 한도 {max_requests}회에 도달했습니다. 다음 실행에서 재개됩니다.")
            return parsed_sets, errors, False
        set_no = candidate["set_number"]
        path = set_cache_path(set_no)
        cached = None if force else load_json(path)
        if cached and not cached.get("error"):
            parsed_sets.append(cached)
            continue
        if cached and cached.get("error") in {
            "rrp_below_min",
            "not_retired",
            "invalid_rrp",
        }:
            continue
        url = candidate.get("url") or f"{BRICKRANKER_BASE}/rankings/set/{set_no}/x"
        html, error = fetch_html(client, url, sleep)
        requests_made += 1
        if not html and candidate.get("url"):
            fallback = f"{BRICKRANKER_BASE}/rankings/set/{set_no}/x"
            if fallback != url:
                html, error = fetch_html(client, fallback, sleep)
                requests_made += 1
                url = fallback
        if not html:
            search = search_set(client, set_no, sleep)
            requests_made += 1
            if search and listing_candidate_has_value(candidate):
                parsed = parsed_from_search(search, candidate, as_of or today_utc())
                if parsed:
                    save_json(path, parsed)
                    save_json(history_cache_path(set_no), {
                        "set_number": set_no,
                        "source_url": parsed["source_url"],
                        "current_value": parsed["current_value"],
                        "confidence": parsed["confidence"],
                        "yearly_roi": parsed["yearly_roi"],
                        "monthly": [],
                    })
                    payload = price_payload(parsed)
                    if payload:
                        save_json(price_cache_path(set_no), payload)
                    parsed_sets.append(parsed)
                    time.sleep(sleep)
                    continue
            errors.append({"set_number": set_no, "url": url, "error": error})
            print(f"[오류] {set_no}: {error}")
            time.sleep(sleep)
            continue
        try:
            parsed = parse_set_page(html, set_no, candidate, as_of or date.today())
        except Exception as exc:
            errors.append({"set_number": set_no, "url": url, "error": str(exc)})
            print(f"[오류] {set_no}: {exc}")
            time.sleep(sleep)
            continue
        release_year = (
            int(parsed["released_date"][:4]) if parsed.get("released_date") else None
        )
        rrp = parsed.get("rrp_usd")
        if not rrp or rrp < RRP_MIN_USD:
            save_json(path, {"error": "rrp_below_min", "set_number": set_no})
            time.sleep(sleep)
            continue
        if release_year is not None and abs(rrp - release_year) < 0.01:
            save_json(path, {"error": "invalid_rrp", "set_number": set_no})
            time.sleep(sleep)
            continue
        if not parsed.get("retired_date"):
            save_json(path, {"error": "not_retired", "set_number": set_no})
            time.sleep(sleep)
            continue
        if parse_date(parsed["retired_date"]) >= (as_of or today_utc()):
            save_json(path, {"error": "not_retired", "set_number": set_no})
            time.sleep(sleep)
            continue
        save_json(path, parsed)
        save_json(history_cache_path(set_no), {
            "set_number": set_no,
            "source_url": parsed["source_url"],
            "current_value": parsed["current_value"],
            "confidence": parsed["confidence"],
            "yearly_roi": parsed["yearly_roi"],
            "monthly": parsed["monthly"],
        })
        payload = price_payload(parsed)
        if payload:
            save_json(price_cache_path(set_no), payload)
        parsed_sets.append(parsed)
        if index % 20 == 0 or index == len(candidates):
            print(
                f"세트 {index}/{len(candidates)} · 완료 {len(parsed_sets)} · 오류 {len(errors)} · 요청 {requests_made}"
            )
        time.sleep(sleep)
    return parsed_sets, errors, True


def write_raw(parsed_sets, complete, listing_count, candidate_count, reasons, errors):
    combined = {item["set_number"]: item for item in parsed_sets}
    if BRICKRANKER_SET_DIR.exists():
        for path in BRICKRANKER_SET_DIR.glob("*.json"):
            item = load_json(path)
            if item and not item.get("error"):
                combined.setdefault(item["set_number"], item)
    parsed_sets = list(combined.values())
    records = [record_for_build(item) for item in parsed_sets]
    records.sort(key=lambda item: item["number"] or "")
    parsed_numbers = {item["set_number"] for item in parsed_sets}
    errors = [
        error
        for error in errors
        if error.get("set_number") not in parsed_numbers
    ]
    save_json(
        BRICKRANKER_RAW,
        {
            "fetched_at": now_iso(),
            "source": "BrickRanker",
            "source_url": BRICKRANKER_BASE,
            "complete": complete,
            "listing_pages": listing_count,
            "candidate_count": candidate_count,
            "count": len(records),
            "candidate_reasons": reasons,
            "errors": errors[:200],
            "sets": records,
        },
    )
    print(f"저장: {BRICKRANKER_RAW} ({len(records)}개)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--sleep", type=float, default=BRICKRANKER_SLEEP)
    parser.add_argument("--max-listing-pages", type=int, default=0)
    parser.add_argument("--max-sets", type=int, default=0)
    parser.add_argument("--max-requests", type=int, default=0)
    parser.add_argument("--listing-only", action="store_true")
    parser.add_argument("--as-of", default=None)
    args = parser.parse_args()

    as_of = parse_date(args.as_of) if args.as_of else today_utc()
    client = session()
    print("BrickRanker sitemap 확인...")
    urls = sitemap_urls(client, args.force, args.sleep)
    print(f"테마/연도 페이지: {len(urls)}개")

    listings, listing_errors = load_listings(
        client, urls, args.force, args.sleep, args.max_listing_pages
    )
    print(f"목록 수집 완료: {len(listings)}개 페이지 / 오류 {len(listing_errors)}")
    candidates, reasons = build_candidates(listings, as_of)
    print(f"후보 세트: {len(candidates)}개")
    for reason, count in sorted(reasons.items(), key=lambda pair: -pair[1]):
        print(f"  제외 {reason}: {count}")
    if args.listing_only:
        save_json(
            BRICKRANKER_CACHE_DIR / "candidates.json",
            {
                "generated_at": now_iso(),
                "count": len(candidates),
                "reasons": reasons,
                "candidates": candidates,
            },
        )
        print(f"후보 저장: {BRICKRANKER_CACHE_DIR / 'candidates.json'}")
        return 0

    parsed_sets, set_errors, complete = collect_sets(
        client,
        candidates,
        args.force,
        args.sleep,
        args.max_sets,
        args.max_requests,
        as_of,
    )
    write_raw(
        parsed_sets,
        complete and not listing_errors and not set_errors,
        len(listings),
        len(candidates),
        reasons,
        listing_errors + set_errors,
    )
    print(f"완료: {len(parsed_sets)}개 / 오류 {len(set_errors)}")
    if not complete:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
