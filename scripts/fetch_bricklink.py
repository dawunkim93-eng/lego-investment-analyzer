import argparse
import sys
import time
from pathlib import Path
from urllib.parse import quote

import requests
from requests_oauthlib import OAuth1

from common import (
    env,
    exclusion_reason,
    load_json,
    now_iso,
    parse_date,
    safe_float,
    safe_int,
    save_json,
    set_number,
    today_utc,
)
from config import (
    BRICKLINK_API_BASE,
    BRICKLINK_CURRENCY,
    BRICKLINK_DAILY_LIMIT,
    BRICKLINK_RAW_DIR,
    BRICKLINK_RETRY_MAX,
    BRICKLINK_SLEEP,
    BRICKSET_RAW,
)

CONDITIONS = {"new": "N", "used": "U"}


def make_session():
    consumer_key = env("BRICKLINK_CONSUMER_KEY")
    consumer_secret = env("BRICKLINK_CONSUMER_SECRET")
    token = env("BRICKLINK_TOKEN") or env("BRICKLINK_ACCESS_TOKEN")
    token_secret = env("BRICKLINK_TOKEN_SECRET") or env(
        "BRICKLINK_ACCESS_TOKEN_SECRET"
    )
    missing = [
        name
        for name, value in (
            ("BRICKLINK_CONSUMER_KEY", consumer_key),
            ("BRICKLINK_CONSUMER_SECRET", consumer_secret),
            ("BRICKLINK_TOKEN", token),
            ("BRICKLINK_TOKEN_SECRET", token_secret),
        )
        if not value
    ]
    if missing:
        return None, missing
    session = requests.Session()
    session.auth = OAuth1(consumer_key, consumer_secret, token, token_secret)
    session.headers.update(
        {"Accept": "application/json", "User-Agent": "lego-investment-analyzer/1.0"}
    )
    return session, []


def cache_path(out_dir, set_no, condition):
    safe = set_no.replace("/", "_")
    return Path(out_dir) / f"{safe}__{condition}_sold.json"


def fetch_guide(session, set_no, condition, sleep):
    guide_params = {
        "guide_type": "sold",
        "new_or_used": CONDITIONS[condition],
        "currency_code": BRICKLINK_CURRENCY,
    }
    url = f"{BRICKLINK_API_BASE}/items/SET/{quote(set_no, safe='')}/price"
    last_error = None
    for attempt in range(1, BRICKLINK_RETRY_MAX + 1):
        try:
            response = session.get(url, params=guide_params, timeout=60)
        except requests.RequestException as error:
            last_error = f"network: {error}"
            time.sleep(min(30, sleep * (2 ** attempt)))
            continue

        if response.status_code == 429:
            retry_after = safe_int(response.headers.get("Retry-After")) or 60
            time.sleep(min(120, max(5, retry_after)))
            last_error = "rate_limited"
            continue
        if response.status_code >= 500:
            last_error = f"http_{response.status_code}"
            time.sleep(min(30, sleep * (2 ** attempt)))
            continue
        if response.status_code == 404:
            return {"error": "not_found", "http_status": 404}
        if response.status_code in (401, 403):
            return {
                "error": f"auth_{response.status_code}",
                "http_status": response.status_code,
                "retryable": True,
            }
        if response.status_code >= 400:
            return {
                "error": f"http_{response.status_code}",
                "http_status": response.status_code,
                "body": response.text[:500],
            }
        try:
            body = response.json()
        except ValueError:
            last_error = "invalid_json"
            time.sleep(min(30, sleep * (2 ** attempt)))
            continue

        meta = body.get("meta") or {}
        code = safe_int(meta.get("code"))
        if code is not None and code != 200:
            return {
                "error": str(meta.get("message") or f"api_{code}"),
                "api_code": code,
                "body": body,
            }
        body["_fetched_at"] = now_iso()
        body["_request"] = {
            "set_number": set_no,
            "condition": condition,
            "guide_type": "sold",
            "currency": BRICKLINK_CURRENCY,
        }
        return body

    return {"error": last_error or "unknown", "retryable": True}


def candidate_sets(input_path, today):
    raw = load_json(input_path)
    if not raw:
        return []
    candidates = []
    for item in raw.get("sets") or []:
        if exclusion_reason(item, today=today):
            continue
        number = set_number(item)
        if not number:
            continue
        candidates.append(
            {
                "set_number": number,
                "name": str(item.get("name") or "").strip(),
                "rrp_usd": item.get("USRetailPrice")
                or (item.get("LEGOCom") or {}).get("US", {}).get("retailPrice"),
                "want": safe_int(item.get("wantCount")) or 0,
                "launch": parse_date(item.get("launchDate")),
            }
        )

    def priority(item):
        return (item["want"], safe_float(item["rrp_usd"]) or 0.0)

    return sorted(candidates, key=priority, reverse=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(BRICKSET_RAW))
    parser.add_argument("--out-dir", default=str(BRICKLINK_RAW_DIR))
    parser.add_argument("--limit", type=int, default=BRICKLINK_DAILY_LIMIT)
    parser.add_argument("--sleep", type=float, default=BRICKLINK_SLEEP)
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--conditions", choices=("new", "used", "both"), default="both"
    )
    parser.add_argument("--max-sets", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    today = today_utc()
    raw_meta = load_json(args.input) or {}
    if raw_meta.get("complete") is False:
        print("경고: Brickset 원본이 미완료 상태입니다. 일부 연도만 수집되었을 수 있습니다.")
    candidates = candidate_sets(args.input, today)
    if args.max_sets:
        candidates = candidates[: args.max_sets]
    if not candidates:
        print("분석 후보가 없습니다. 먼저 fetch_brickset.py를 실행하세요.")
        return 1

    conditions = ("new", "used") if args.conditions == "both" else (args.conditions,)
    Path(args.out_dir).mkdir(parents=True, exist_ok=True)

    print(f"후보 {len(candidates)}개 / 조건 {', '.join(conditions)}")
    if args.dry_run:
        for item in candidates[:10]:
            print(f"  {item['set_number']} {item['name']} / want={item['want']}")
        return 0

    session, missing = make_session()
    if session is None:
        print("BrickLink API 인증 정보가 없습니다: " + ", ".join(missing))
        print("BrickLink 로그인 후 API 키를 발급해 .env에 추가하세요.")
        return 1

    calls = 0
    fetched = 0
    skipped = 0
    errors = 0
    stopped = False

    for index, item in enumerate(candidates, start=1):
        set_no = item["set_number"]
        pending = []
        for condition in conditions:
            path = cache_path(args.out_dir, set_no, condition)
            if not args.force and path.exists():
                existing = load_json(path)
                if existing and not existing.get("retryable"):
                    continue
            pending.append(condition)

        if not pending:
            skipped += 1
            continue

        if calls + len(pending) > args.limit:
            print(f"[중단] API 호출 한도 {args.limit}회에 도달했습니다. 다음 실행에서 재개됩니다.")
            stopped = True
            break

        for condition in pending:
            if calls >= args.limit:
                stopped = True
                break
            body = fetch_guide(session, set_no, condition, args.sleep)
            calls += 1
            if body.get("retryable"):
                print(f"[재시도 필요] {set_no} {condition}: {body.get('error')}")
                errors += 1
                continue
            save_json(cache_path(args.out_dir, set_no, condition), body)
            if body.get("error"):
                errors += 1
            else:
                fetched += 1
            time.sleep(args.sleep)

        if index % 25 == 0 or index == len(candidates):
            print(
                f"{index}/{len(candidates)} 세트 / 호출 {calls} / 저장 {fetched} / 오류 {errors} / 스킵 {skipped}"
            )
        if stopped:
            break

    print(
        f"\n완료: 호출 {calls}, 저장 {fetched}, 오류 {errors}, 기존 캐시 스킵 {skipped}"
    )
    if stopped:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
