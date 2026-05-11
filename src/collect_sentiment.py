"""
Sentiment 수집: 뉴스 헤드라인 / Hacker News / 네이버 뉴스 / Google Trends / 네이버 데이터랩
- secrets: NEWS_API_KEY
           NAVER_CLIENT_ID, NAVER_CLIENT_SECRET
- Hacker News: API key 불필요 (Algolia 무료 공개 API)
- 네이버 뉴스: 기존 NAVER_* 키 재사용
"""

import os
import json
import time
import pandas as pd
import requests
from datetime import date, timedelta


TODAY = date.today().isoformat()
YESTERDAY = (date.today() - timedelta(days=1)).isoformat()


def save(df: pd.DataFrame, filepath: str) -> None:
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    if os.path.exists(filepath):
        if TODAY in pd.read_csv(filepath)["date"].astype(str).values:
            print(f"  skip: {filepath} already has {TODAY}")
            return
        df.to_csv(filepath, mode="a", header=False, index=False, encoding="utf-8-sig")
    else:
        df.to_csv(filepath, mode="w", header=True, index=False, encoding="utf-8-sig")
    print(f"  saved {len(df)} rows -> {filepath}")


# ── Hacker News (Algolia API) — key 불필요 ───────────────────────────────

def collect_hackernews():
    """
    Hacker News 상위 게시물 수집 (Algolia 무료 API, key 불필요)
    테크·스타트업·경제 글로벌 커뮤니티 반응 → Reddit investing/technology 대체
    """
    from datetime import timezone
    import time as _time

    # 카테고리별 검색어
    keyword_groups = {
        "tech":       ["AI", "semiconductor", "startup", "LLM", "robotics"],
        "finance":    ["stock market", "inflation", "interest rate", "recession"],
        "energy":     ["oil price", "renewable energy", "EV"],
        "korea":      ["Korea", "Samsung", "Hyundai", "Kakao"],
        "consumer":   ["e-commerce", "retail", "consumer"],
    }

    # 최근 24시간 타임스탬프
    since_ts = int((date.today() - timedelta(days=1)).replace(
        tzinfo=timezone.utc).timestamp())

    rows = []
    for category, keywords in keyword_groups.items():
        for kw in keywords:
            try:
                resp = requests.get(
                    "https://hn.algolia.com/api/v1/search_by_date",
                    params={
                        "query":         kw,
                        "tags":          "story",        # 게시물만 (댓글 제외)
                        "numericFilters": f"created_at_i>{since_ts}",
                        "hitsPerPage":   20,
                    },
                    timeout=10,
                )
                for hit in resp.json().get("hits", []):
                    rows.append({
                        "date":        TODAY,
                        "category":    category,
                        "keyword":     kw,
                        "title":       (hit.get("title") or "")[:200],
                        "points":      hit.get("points", 0),
                        "num_comments":hit.get("num_comments", 0),
                        "author":      hit.get("author", ""),
                        "created_at":  hit.get("created_at", ""),
                        "url":         (hit.get("url") or "")[:200],
                    })
                _time.sleep(0.5)
            except Exception as e:
                print(f"  [WARN] HN '{kw}': {e}")

    if rows:
        save(pd.DataFrame(rows), "data/sentiment/hackernews.csv")


# ── 네이버 뉴스 검색 — 기존 NAVER_* 키 재사용 ────────────────────────────

def collect_naver_news():
    """
    네이버 뉴스 검색 API (기존 NAVER_CLIENT_ID/SECRET 그대로 사용)
    한국 뉴스 반응 수집 → Reddit korea 대체
    """
    client_id     = os.environ.get("NAVER_CLIENT_ID")
    client_secret = os.environ.get("NAVER_CLIENT_SECRET")
    if not (client_id and client_secret):
        print("  [SKIP] Naver News: credentials missing")
        return

    keyword_groups = {
        "economy":    ["금리", "물가", "경기침체", "수출", "환율"],
        "industry":   ["반도체", "이차전지", "AI 산업", "바이오"],
        "consumer":   ["소비트렌드", "온라인쇼핑", "배달시장"],
        "employment": ["취업시장", "고용", "실업률"],
        "realestate": ["부동산", "아파트 가격", "전세"],
    }

    rows = []
    headers = {
        "X-Naver-Client-Id":     client_id,
        "X-Naver-Client-Secret": client_secret,
    }

    for category, keywords in keyword_groups.items():
        for kw in keywords:
            try:
                resp = requests.get(
                    "https://openapi.naver.com/v1/search/news.json",
                    headers=headers,
                    params={
                        "query":   kw,
                        "display": 20,
                        "sort":    "date",   # 최신순
                    },
                    timeout=10,
                )
                for item in resp.json().get("items", []):
                    # HTML 태그 간단 제거
                    title = item.get("title", "").replace("<b>", "").replace("</b>", "")
                    rows.append({
                        "date":      TODAY,
                        "category":  category,
                        "keyword":   kw,
                        "title":     title[:200],
                        "source":    item.get("originallink", "")[:100],
                        "pub_date":  item.get("pubDate", ""),
                        "description": item.get("description", "")
                            .replace("<b>", "").replace("</b>", "")[:300],
                    })
                time.sleep(0.3)
            except Exception as e:
                print(f"  [WARN] Naver news '{kw}': {e}")

    if rows:
        save(pd.DataFrame(rows), "data/sentiment/naver_news.csv")


# ── 뉴스 헤드라인 (NewsAPI) ───────────────────────────────────────────────

def collect_news():
    api_key = os.environ.get("NEWS_API_KEY")
    if not api_key:
        print("  [SKIP] News: API key missing")
        return

    # 업계별 키워드 → 나중에 세그먼트별 분석 가능하도록 category 구분
    keyword_groups = {
        "finance":    ["stock market", "KOSPI", "Korea economy", "inflation", "interest rate"],
        "tech":       ["artificial intelligence", "semiconductor", "startup Korea"],
        "consumer":   ["retail sales", "e-commerce", "consumer sentiment"],
        "energy":     ["oil price", "renewable energy", "energy crisis"],
        "geopolitics":["North Korea", "US China trade", "geopolitical risk"],
    }
    rows = []

    # 3일치 요청: 하루 실패해도 재수집 가능 + 초기 세팅 시 데이터 확보
    from_date = (date.today() - timedelta(days=3)).isoformat()

    for category, keywords in keyword_groups.items():
        for kw in keywords:
            try:
                resp = requests.get(
                    "https://newsapi.org/v2/everything",
                    params={
                        "q":        kw,
                        "from":     from_date,
                        "sortBy":   "publishedAt",
                        "apiKey":   api_key,
                        "pageSize": 15,
                        "language": "en",
                    },
                    timeout=10,
                )
                for a in resp.json().get("articles", []):
                    rows.append({
                        "date":         TODAY,
                        "category":     category,
                        "keyword":      kw,
                        "title":        (a.get("title") or "")[:200],
                        "source":       (a.get("source") or {}).get("name", ""),
                        "published_at": a.get("publishedAt", ""),
                        "description":  (a.get("description") or "")[:300],
                    })
                time.sleep(0.3)
            except Exception as e:
                print(f"  [WARN] news '{kw}': {e}")

    if rows:
        save(pd.DataFrame(rows), "data/sentiment/news.csv")


# ── Google Trends (pytrends) ──────────────────────────────────────────────

def collect_google_trends():
    try:
        from pytrends.request import TrendReq
    except ImportError:
        print("  [SKIP] pytrends not installed")
        return

    pytrends = TrendReq(hl="ko-KR", tz=540)

    keyword_groups = {
        "food_delivery":  ["배달음식", "치킨 배달", "배달의민족"],
        "ecommerce":      ["쿠팡", "네이버쇼핑", "무신사"],
        "lifestyle":      ["스타벅스", "헬스장", "캠핑"],
        "finance_kr":     ["재테크", "주식 투자", "부동산"],
        "employment":     ["이직", "취업", "채용공고"],
        "travel":         ["해외여행", "국내여행", "항공권"],
    }
    rows = []

    for category, keywords in keyword_groups.items():
        success = False
        for attempt in range(2):          # 차단 시 1회 재시도
            try:
                pytrends.build_payload(keywords, cat=0, timeframe="today 1-m", geo="KR")
                df = pytrends.interest_over_time()
                if df.empty:
                    break
                latest = df.iloc[-1]
                for kw in keywords:
                    if kw in latest:
                        rows.append({
                            "date":     TODAY,
                            "category": category,
                            "keyword":  kw,
                            "interest": int(latest[kw]),
                            "source":   "google",
                        })
                success = True
                break
            except Exception as e:
                wait = 10 * (attempt + 1)
                print(f"  [WARN] google trends '{category}' (attempt {attempt+1}): {e} — {wait}s 대기")
                time.sleep(wait)
        time.sleep(5 if success else 2)   # 성공 후 충분한 간격

    if rows:
        save(pd.DataFrame(rows), "data/sentiment/search_trends.csv")


# ── 네이버 데이터랩 (검색어 트렌드) ──────────────────────────────────────

def collect_naver_datalab():
    """
    네이버 데이터랩 검색어 트렌드 API
    - 발급: https://developers.naver.com/apps/  (애플리케이션 등록 → 데이터랩 검색어 트렌드)
    - 무료, 하루 25,000 호출
    - Google Trends보다 차단 없고 한국 검색량을 더 정확히 반영
    """
    client_id     = os.environ.get("NAVER_CLIENT_ID")
    client_secret = os.environ.get("NAVER_CLIENT_SECRET")
    if not (client_id and client_secret):
        print("  [SKIP] Naver DataLab: credentials missing")
        return

    keyword_groups = [
        {"groupName": "배달앱",   "keywords": ["배달의민족", "쿠팡이츠", "요기요"]},
        {"groupName": "온라인쇼핑", "keywords": ["쿠팡", "11번가", "지마켓"]},
        {"groupName": "패션",     "keywords": ["무신사", "지그재그", "에이블리"]},
        {"groupName": "재테크",   "keywords": ["주식", "부동산", "코인"]},
        {"groupName": "취업",     "keywords": ["취업", "이직", "자소서"]},
        {"groupName": "여행",     "keywords": ["해외여행", "항공권", "호텔"]},
        {"groupName": "건강",     "keywords": ["헬스장", "다이어트", "영양제"]},
        {"groupName": "AI",       "keywords": ["챗GPT", "AI", "클로드"]},
    ]

    rows = []
    end_date   = TODAY
    start_date = (date.today() - timedelta(days=1)).isoformat()  # 전날 하루치

    try:
        resp = requests.post(
            "https://openapi.naver.com/v1/datalab/search",
            headers={
                "X-Naver-Client-Id":     client_id,
                "X-Naver-Client-Secret": client_secret,
                "Content-Type":          "application/json",
            },
            data=json.dumps({
                "startDate":    start_date,
                "endDate":      end_date,
                "timeUnit":     "date",
                "keywordGroups": keyword_groups,
            }),
            timeout=15,
        )
        results = resp.json().get("results", [])
        for result in results:
            group_name = result["title"]
            for point in result.get("data", []):
                rows.append({
                    "date":     point["period"],
                    "category": group_name,
                    "ratio":    point["ratio"],   # 0~100 상대값
                    "source":   "naver",
                })
    except Exception as e:
        print(f"  [WARN] naver datalab: {e}")

    if rows:
        # 네이버 데이터는 date 컬럼이 이미 들어있으므로 TODAY 체크 대신 직접 저장
        df = pd.DataFrame(rows)
        fp = "data/sentiment/search_trends.csv"
        os.makedirs(os.path.dirname(fp), exist_ok=True)
        if os.path.exists(fp):
            existing = pd.read_csv(fp)
            # 같은 날짜+source 중복 방지
            mask = ~((existing["date"].astype(str) == TODAY) & (existing["source"] == "naver"))
            combined = pd.concat([existing[mask], df], ignore_index=True)
            combined.to_csv(fp, index=False, encoding="utf-8-sig")
        else:
            df.to_csv(fp, index=False, encoding="utf-8-sig")
        print(f"  saved {len(df)} rows -> {fp}")


# ── 진입점 ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"=== Sentiment Collection: {TODAY} ===")
    collect_hackernews()     # key 불필요
    collect_naver_news()     # NAVER_* 재사용
    collect_news()           # NEWS_API_KEY
    collect_google_trends()
    collect_naver_datalab()
    print("Done.")
