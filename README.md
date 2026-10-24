# LEGO 재테크 분석

단종된 LEGO 세트의 **현재 신품 시세 대비 출시가(RRP) 수익률**을 분석하는 모바일 앱형 정적 사이트입니다.
560px 카드 UI, 라이트/다크 모드, 5개 탭(개요·수익률·테마·데이터·설명서)으로 구성됩니다.
정적 파일만으로 동작하며, 로컬에서는 `python3 -m http.server`로 엽니다. 모든 숫자는 `scripts/`가 생성합니다.

## 분석 기준

- 대상: 1990~2024년 출시, 단종된 세트
- 가격: US RRP **$20 이상**
- 제외: Duplo, 4+, Junior, 잡화, 도서, 폴리백, RRP 데이터 오류
- 랭킹 조건: 단종 후 3년 이상 + 최근 6개월 신품 체결 10건 이상
- 가격 상태: **BrickRanker 신품(New) 최근 6개월 평균 판매가**

## 데이터 출처

| 소스 | 내용 |
|---|---|
| [BrickRanker](https://brickranker.com) | RRP, 출시일·단종일, 현재 신품가, 월별 평균가·판매량, 연간 ROI, 테마, 브릭/미니피그 수 |
| [FRED CPIAUCSL](https://fred.stlouisfed.org/series/CPIAUCSL) | 실질 CAGR 계산용 미국 소비자물가지수 |

BrickRanker는 공개 페이지이며 `robots.txt`가 전체 접근을 허용합니다. 수집은 **0.7초 간격·캐시·재개·백오프**로 서버 부하를 최소화합니다. 데이터는 BrickLink 등 마켓플레이스 판매 기록을 집계한 3자 추정치입니다.

## 빠른 시작

API 키가 필요 없습니다. 이 저장소에는 이미 수집된 `data/sets.json`이 포함되어 있어 바로 대시보드를 열 수도 있습니다.

```bash
cd ~/lego-investment-analyzer
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

.venv/bin/python scripts/fetch_cpi.py
.venv/bin/python scripts/fetch_brickranker.py
.venv/bin/python scripts/build_dataset.py \
  --input data/raw/brickranker.json \
  --prices-dir data/raw/brickranker_prices
.venv/bin/python scripts/validate.py

# 또는 한 번에
./scripts/run_all.sh

python3 -m http.server 8000
# http://localhost:8000
```

### 수집을 나눠서 실행

```bash
.venv/bin/python scripts/fetch_brickranker.py --max-listing-pages 200
.venv/bin/python scripts/fetch_brickranker.py --max-sets 500
.venv/bin/python scripts/fetch_brickranker.py --max-requests 300
```

- `--max-listing-pages`: 테마/연도 목록 페이지만 제한
- `--max-sets`: 세트 상세 페이지 수 제한
- `--max-requests`: 이번 실행의 HTTP 요청 수 제한
- 중단 후 같은 명령을 다시 실행하면 캐시에서 이어서 수집합니다.
- `--force`는 캐시를 무시하고 다시 받습니다.

## 지표

- `ROI = 현재가 / RRP - 1`
- `CAGR = (현재가 / RRP)^(1/보유연수) - 1`
- `실질 CAGR`: FRED CPI로 출시 시점 물가를 현재 물가로 환산
- `유동성`: 최근 6개월 신품 체결 수량
- 절대 차익, 테마·단종연도·RRP 구간별 중위 CAGR
- `단종일 추정`: 공개 단종일이 없을 때 출시일·상태로 추정한 세트 표시
- 상위 세트 카드에는 최근 12개월 가격 스파크라인을 표시

## GitHub Pages 배포

이 프로젝트는 GitHub Pages에 바로 올릴 수 있는 정적 사이트입니다.

1. GitHub에 `lego-investment-analyzer` 저장소를 만듭니다.
2. `index.html`, `app.js`, `styles.css`, `data/sets.json`, `.nojekyll`을 포함해 push합니다.
3. 저장소 **Settings → Pages → Build and deployment**에서 `Deploy from a branch`를 선택합니다.
4. 브랜치 `main`, 폴더 `/ (root)`를 선택하고 저장합니다.
5. `https://<계정>.github.io/lego-investment-analyzer/`에서 확인합니다.

`data/sets.json`은 저장소에 포함해야 하며, `data/raw/` 캐시는 `.gitignore`로 제외되어 있습니다.

## 구조

```text
index.html · app.js · styles.css · .nojekyll
data/
  raw/brickranker.json
  raw/brickranker/                 # 목록·세트 페이지 캐시
  raw/brickranker_prices/          # build_dataset 입력용 신품 가격 캐시
  raw/brickranker_history/         # 월별 가격 이력
  sets.json                        # 대시보드 데이터
  coverage.json
scripts/
  config.py
  common.py
  fetch_brickranker.py
  fetch_cpi.py
  build_dataset.py
  recompute_liquidity.py
  validate.py
  make_demo.py
  run_all.sh
report/
```

## 한계

- **신품(New) 전용**: BrickRanker는 중고 가격을 제공하지 않아 `Sealed Premium`과 중고 수익률은 분석하지 않습니다.
- 현재가는 최근 6개월 평균이라 개별 거래·상태·구성에 따라 크게 달라질 수 있습니다.
- RRP는 실제 구매가가 아니며, 수수료·배송·보관·세금·할인은 반영하지 않았습니다.
- 저유동성 세트의 평균가는 소수 거래에 좌우될 수 있습니다.
- 단종일이 없는 세트는 추정값이며, 재출시·리메이크 세트는 가치가 희석될 수 있습니다.
- 투자 판단의 참고 자료이며 미래 수익을 보장하지 않습니다.

## 참고: Brickset / BrickLink API

기존 `fetch_brickset.py`·`fetch_bricklink.py`는 선택용으로 남겨두었습니다.

- Brickset: 무료 키 발급 전 **로그인 + reCAPTCHA + 이메일 인증** 필요
- BrickLink: **LEGO 계정 로그인 + 고정 IP 등록 + IP별 access token** 필요 → 일반 가정용 회선에서는 사실상 사용 불가
- 현재 기본 파이프라인은 위 API 키 없이 BrickRanker만 사용합니다.
