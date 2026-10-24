import argparse
import json
import sys
import time
import requests

from common import (
    env,
    exclusion_reason,
    load_json,
    now_iso,
    parse_date,
    save_json,
    set_number,
    today_utc,
)
from config import (
    BRICKSET_PAGE_SIZE,
    BRICKSET_RAW,
    BRICKSET_SLEEP,
    BRICKSET_YEAR_DIR,
    END_YEAR,
    START_YEAR,
)

API_URL = "https://brickset.com/api/v3.asmx/getSets"


def call_api(api_key, params, timeout=60):
    payload = {"apiKey": api_key, "params": json.dumps(params)}
    response = requests.post(API_URL, data=payload, timeout=timeout)
    response.raise_for_status()
    body = response.json()
    if body.get("status") != "success":
        message = str(body.get("message") or "unknown error")
        if "limit" in message.lower():
            raise RuntimeError("API_LIMIT")
        raise RuntimeError(message)
    return body


def year_cache_path(year):
    return BRICKSET_YEAR_DIR / f"year-{year}.json"


def fetch_year(api_key, year, force=False, sleep=BRICKSET_SLEEP, max_calls=90):
    path = year_cache_path(year)
    cached = None if force else load_json(path)
    if cached and cached.get("complete"):
        return cached["sets"], 0

    sets = []
    pages_fetched = 0
    matches = 0
    if cached and not force:
        sets = list(cached.get("sets") or [])
        pages_fetched = int(cached.get("pages_fetched") or 0)
        matches = int(cached.get("matches") or 0)

    calls = 0
    page = pages_fetched + 1
    while True:
        if calls >= max_calls:
            save_json(
                path,
                {
                    "year": year,
                    "matches": matches,
                    "pages_fetched": pages_fetched,
                    "complete": False,
                    "fetched_at": now_iso(),
                    "sets": sets,
                },
            )
            raise RuntimeError("CALL_BUDGET")

        params = {
            "year": str(year),
            "pageSize": BRICKSET_PAGE_SIZE,
            "pageNumber": page,
            "extendedData": 1,
            "orderBy": "Number",
        }
        try:
            body = call_api(api_key, params)
        except RuntimeError as error:
            if str(error) == "API_LIMIT":
                save_json(
                    path,
                    {
                        "year": year,
                        "matches": matches,
                        "pages_fetched": pages_fetched,
                        "complete": False,
                        "fetched_at": now_iso(),
                        "sets": sets,
                    },
                )
                raise
            raise

        calls += 1
        matches = int(body.get("matches") or matches or 0)
        page_sets = body.get("sets") or []
        known = {set_number(item) for item in sets}
        for item in page_sets:
            number = set_number(item)
            if number and number not in known:
                sets.append(item)
                known.add(number)
        pages_fetched = page
        complete = len(page_sets) < BRICKSET_PAGE_SIZE or len(sets) >= matches
        save_json(
            path,
            {
                "year": year,
                "matches": matches,
                "pages_fetched": pages_fetched,
                "complete": complete,
                "fetched_at": now_iso(),
                "sets": sets,
            },
        )
        if complete:
            return sets, calls
        page += 1
        time.sleep(sleep)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-key", default=env("BRICKSET_API_KEY"))
    parser.add_argument("--start-year", type=int, default=START_YEAR)
    parser.add_argument("--end-year", type=int, default=END_YEAR)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--sleep", type=float, default=BRICKSET_SLEEP)
    parser.add_argument("--max-calls", type=int, default=90)
    args = parser.parse_args()

    if not args.api_key:
        print("BRICKSET_API_KEY가 없습니다.")
        print("https://brickset.com/tools/webservices/requestkey 에서 발급 후 .env에 추가하세요.")
        return 1

    BRICKSET_YEAR_DIR.mkdir(parents=True, exist_ok=True)
    all_sets = {}
    calls = 0
    failed_years = []

    for year in range(args.start_year, args.end_year + 1):
        if calls >= args.max_calls:
            print(f"[중단] 호출 한도 {args.max_calls}회에 도달했습니다. 다음 실행에서 재개됩니다.")
            failed_years.extend(range(year, args.end_year + 1))
            break
        try:
            sets, used = fetch_year(
                args.api_key,
                year,
                force=args.force,
                sleep=args.sleep,
                max_calls=args.max_calls - calls,
            )
        except RuntimeError as error:
            code = str(error)
            if code in {"API_LIMIT", "CALL_BUDGET"}:
                print(f"[중단] {year}년 수집 중 한도 도달: {code}")
                failed_years.append(year)
                break
            print(f"[오류] {year}년: {error}")
            failed_years.append(year)
            continue
        calls += used
        for item in sets:
            number = set_number(item)
            if number:
                all_sets[number] = item
        print(f"{year}: {len(sets)}개 (호출 {calls})")
        time.sleep(args.sleep)

    ordered = sorted(
        all_sets.values(),
        key=lambda item: (
            safe_year(item),
            set_number(item),
        ),
    )
    save_json(
        BRICKSET_RAW,
        {
            "fetched_at": now_iso(),
            "start_year": args.start_year,
            "end_year": args.end_year,
            "complete": not failed_years,
            "failed_years": failed_years,
            "count": len(ordered),
            "sets": ordered,
        },
    )

    today = today_utc()
    reasons = {}
    candidates = 0
    for item in ordered:
        reason = exclusion_reason(item, today=today)
        if reason:
            reasons[reason] = reasons.get(reason, 0) + 1
        else:
            candidates += 1

    print(f"\n저장: {BRICKSET_RAW}")
    print(f"전체 수집: {len(ordered)}")
    print(f"분석 후보: {candidates}")
    for reason, count in sorted(reasons.items(), key=lambda pair: -pair[1]):
        print(f"  제외 {reason}: {count}")
    if failed_years:
        print(f"미완료 연도: {failed_years}")
        return 2
    return 0


def safe_year(item):
    launch = parse_date(item.get("launchDate"))
    if launch:
        return launch.year
    try:
        return int(item.get("year") or 0)
    except (TypeError, ValueError):
        return 0


if __name__ == "__main__":
    sys.exit(main())
