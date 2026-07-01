"""
Sentiment 수집 (API 키 불필요): Hacker News / GDELT 글로벌 뉴스 / Google Trends

- Hacker News (Algolia)  : key 불필요
- GDELT 2.0 DOC API      : key 불필요 — NewsAPI(키·30일 제한) 대체. 100+개 언어, 기간 제한 없음
- Google Trends (pytrends): key 불필요 (rate-limit 있어 재시도 처리)

뉴스는 기존 news.csv 스키마(date,category,keyword,title,source,published_at,description)와
동일하게 GDELT로 이어서 누적한다.
"""

import os
import time
import pandas as pd
import requests
from urllib.parse import quote
from datetime import date, datetime, timedelta, timezone

TODAY = date.today().isoformat()


def save(df: pd.DataFrame, filepath: str) -> None:
    """date 컬럼 기준 중복 방지 저장 (당일 1회만 누적)."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    if os.path.exists(filepath):
        existing_dates = set(pd.read_csv(filepath)["date"].astype(str).unique())
        new_rows = df[~df["date"].astype(str).isin(existing_dates)]
        if new_rows.empty:
            print(f"  skip: {filepath} — 신규 날짜 없음")
            return
        new_rows.to_csv(filepath, mode="a", header=False, index=False, encoding="utf-8-sig")
        print(f"  saved {len(new_rows)}행 -> {filepath}")
    else:
        df.to_csv(filepath, mode="w", header=True, index=False, encoding="utf-8-sig")
        print(f"  saved {len(df)}행 -> {filepath}")


# ── Hacker News (Algolia API) — key 불필요 ───────────────────────────────

def collect_hackernews():
    """Hacker News 게시물 수집 (Algolia 무료 API). 테크·금융·소비 글로벌 반응."""
    since_ts = int((datetime.now(timezone.utc) - timedelta(days=1)).timestamp())

    keyword_groups = {
        "tech":     ["AI", "semiconductor", "startup", "LLM", "robotics"],
        "finance":  ["stock market", "inflation", "interest rate", "recession"],
        "energy":   ["oil price", "renewable energy", "EV"],
        "korea":    ["Korea", "Samsung", "Hyundai", "Kakao"],
        "consumer": ["e-commerce", "retail", "consumer"],
    }

    rows = []
    for category, keywords in keyword_groups.items():
        for kw in keywords:
            try:
                resp = requests.get(
                    "https://hn.algolia.com/api/v1/search_by_date",
                    params={
                        "query":          kw,
                        "tags":           "story",
                        "numericFilters": f"created_at_i>{since_ts}",
                        "hitsPerPage":    20,
                    },
                    timeout=10,
                )
                for hit in resp.json().get("hits", []):
                    rows.append({
                        "date":         TODAY,
                        "category":     category,
                        "keyword":      kw,
                        "title":        (hit.get("title") or "")[:200],
                        "points":       hit.get("points", 0),
                        "num_comments": hit.get("num_comments", 0),
                        "author":       hit.get("author", ""),
                        "created_at":   hit.get("created_at", ""),
                        "url":          (hit.get("url") or "")[:200],
                    })
                time.sleep(0.5)
            except Exception as e:
                print(f"  [WARN] HN '{kw}': {e}")

    if rows:
        save(pd.DataFrame(rows), "data/sentiment/hackernews.csv")


# ── GDELT 2.0 DOC API — key 불필요 (NewsAPI 대체) ─────────────────────────

def collect_gdelt_news():
    """
    GDELT DOC API로 영문 글로벌 뉴스 수집. key 불필요, 기간 제한 없음.
    기존 news.csv 스키마(date,category,keyword,title,source,published_at,description)로 누적.
    GDELT ArtList는 본문 요약을 제공하지 않아 description은 출처국가/언어로 채운다.
    """
    keyword_groups = {
        "finance":     ["stock market", "KOSPI", "Korea economy", "inflation", "interest rate"],
        "tech":        ["artificial intelligence", "semiconductor", "Korea startup"],
        "consumer":    ["retail sales", "e-commerce", "consumer sentiment"],
        "energy":      ["oil price", "renewable energy", "energy crisis"],
        "geopolitics": ["North Korea", "US China trade", "geopolitical risk"],
    }
    rows = []

    for category, keywords in keyword_groups.items():
        for kw in keywords:
            try:
                resp = requests.get(
                    "https://api.gdeltproject.org/api/v2/doc/doc",
                    params={
                        "query":      f'"{kw}" sourcelang:english',
                        "mode":       "ArtList",
                        "format":     "json",
                        "maxrecords": 25,
                        "timespan":   "1d",
                        "sort":       "DateDesc",
                    },
                    headers={"User-Agent": "data-collection/1.0"},
                    timeout=20,
                )
                # GDELT는 결과 없을 때 빈 본문/HTML을 주기도 하므로 방어적으로 파싱
                try:
                    articles = resp.json().get("articles", [])
                except ValueError:
                    articles = []
                for a in articles:
                    seen = a.get("seendate", "")  # 형식: 20260630T120000Z
                    try:
                        published = datetime.strptime(seen, "%Y%m%dT%H%M%SZ").isoformat() + "Z"
                    except ValueError:
                        published = seen
                    rows.append({
                        "date":         TODAY,
                        "category":     category,
                        "keyword":      kw,
                        "title":        (a.get("title") or "")[:200],
                        "source":       a.get("domain", ""),
                        "published_at": published,
                        "description":  f"{a.get('sourcecountry', '')} / {a.get('language', '')}".strip(" /"),
                    })
                time.sleep(1)  # GDELT rate-limit 배려
            except Exception as e:
                print(f"  [WARN] GDELT '{kw}': {e}")

    if rows:
        save(pd.DataFrame(rows), "data/sentiment/news.csv")


# ── Google Trends — key 불필요 ────────────────────────────────────────────

def collect_google_trends():
    """
    Google Trends (pytrends, 무키) — best-effort 수집.

    datacenter IP는 구글이 구조적으로 429 차단하므로 안정 수집이 불가능하다.
    재시도·긴 대기 없이 실패 시 즉시 다음 그룹으로 넘어가(fail-fast) 런타임을
    낭비하지 않고, 되는 날만 보너스로 수집한다.
    관심도 축의 안정 소스는 Wikipedia 조회수(collect_wikipedia)가 담당.
    """
    try:
        from pytrends.request import TrendReq
    except ImportError:
        print("  [SKIP] pytrends not installed")
        return

    # 짧은 timeout·재시도 없음 → 막히면 빨리 실패
    pytrends = TrendReq(hl="ko-KR", tz=540, timeout=(5, 15), retries=0)

    keyword_groups = {
        "food_delivery": ["배달음식", "치킨 배달", "배달의민족"],
        "ecommerce":     ["쿠팡", "네이버쇼핑", "무신사"],
        "lifestyle":     ["스타벅스", "헬스장", "캠핑"],
        "finance_kr":    ["재테크", "주식 투자", "부동산"],
        "employment":    ["이직", "취업", "채용공고"],
        "travel":        ["해외여행", "국내여행", "항공권"],
    }
    rows = []
    ok = 0

    for category, keywords in keyword_groups.items():
        try:
            pytrends.build_payload(keywords, cat=0, timeframe="today 1-m", geo="KR")
            df = pytrends.interest_over_time()
            if df.empty:
                continue
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
            ok += 1
        except Exception as e:
            print(f"  [WARN] google trends '{category}' 스킵: {e}")
        time.sleep(1)  # 최소 간격만

    print(f"  google trends: {ok}/{len(keyword_groups)} 그룹 성공")
    if rows:
        save(pd.DataFrame(rows), "data/sentiment/search_trends.csv")


# ── Wikipedia Pageviews (Wikimedia REST, 무키) ────────────────────────────

# 프로젝트 테마(시장·테크·한국 기업·소비) 관심도 추이용 문서
WIKI_ARTICLES = {
    "ko.wikipedia.org": ["삼성전자", "SK하이닉스", "카카오 (기업)", "비트코인",
                          "인공지능", "쿠팡", "코스피", "부동산"],
    "en.wikipedia.org": ["Bitcoin", "Artificial intelligence", "Nvidia", "Stock market"],
}


def collect_wikipedia():
    """
    위키백과 일별 조회수 (Wikimedia Pageviews API, key 불필요, UA 필요).
    데이터가 1~2일 지연되므로 최근 구간을 요청해 가장 최신 일자만 누적한다.
    """
    start = (date.today() - timedelta(days=4)).strftime("%Y%m%d")
    end   = (date.today() - timedelta(days=1)).strftime("%Y%m%d")
    headers = {"User-Agent": "data-collection/1.0 (github actions; daily collection)"}
    rows = []

    for project, articles in WIKI_ARTICLES.items():
        for article in articles:
            title = quote(article.replace(" ", "_"), safe="")
            url = (f"https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/"
                   f"{project}/all-access/user/{title}/daily/{start}/{end}")
            # 빈 응답/일시적 429에 대비해 2회 재시도
            for attempt in range(2):
                try:
                    resp = requests.get(url, headers=headers, timeout=15)
                    if resp.status_code == 404:          # 문서 없음 → 재시도 불필요
                        break
                    items = resp.json().get("items", [])
                    if not items:
                        raise ValueError("empty items")
                    latest = items[-1]                   # 가장 최신 가용 일자
                    rows.append({
                        "date":    f"{latest['timestamp'][:4]}-{latest['timestamp'][4:6]}-{latest['timestamp'][6:8]}",
                        "project": project,
                        "article": article,
                        "views":   latest.get("views", 0),
                        "source":  "wikipedia",
                    })
                    break
                except Exception as e:
                    if attempt == 0:
                        time.sleep(1.5)
                        continue
                    print(f"  [WARN] wikipedia '{article}' ({project}): {e}")
            time.sleep(0.3)

    if rows:
        save(pd.DataFrame(rows), "data/sentiment/wikipedia.csv")


# ── 진입점 ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"=== Sentiment Collection (no-key): {TODAY} ===")
    # 각 수집기 격리: 하나가 죽어도 나머지는 계속 진행
    for collector in (collect_hackernews, collect_gdelt_news,
                      collect_google_trends, collect_wikipedia):
        try:
            collector()
        except Exception as e:
            print(f"  [ERROR] {collector.__name__} 실패: {e}")
    print("Done.")
