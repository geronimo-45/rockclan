"""
RockClan 프로리그 기록실 자동화 스크립트
GitHub Actions에서 실행됨 (30분마다)
"""

import os
import json
import re
import requests
from datetime import datetime, date
from pathlib import Path

# ===== 설정 =====
CAFE_ID = "31553306"
MENU_ID = "29"
REPO_ROOT = Path(__file__).parent.parent

# GitHub Secrets에서 쿠키 읽기
NID_AUT = os.environ.get("NAVER_NID_AUT", "")
NID_SES = os.environ.get("NAVER_NID_SES", "")

# 처리 완료된 게시글 ID 추적 파일
PROCESSED_FILE = REPO_ROOT / "scripts" / "processed_ids.json"

# ===== 닉네임 → JSON ID 매핑 =====
NICK_MAP = {
    "낭만": "Nangman",
    "스트": "Strive",
    "스트라이브": "Strive",
    "팡": "Pang",
    "비니": "Veeny",
    "루빡": "Rupark",
    "달선": "dalsun2",
    "제주": "JeJu",
    "미스티": "MiSTY",
    "고마진": "GgoMajin",
    "g마진": "GgoMajin",
    "g마": "GgoMajin",
    "현호": "Hyunho",
    "프렌드": "Friend",
    "글로리": "Glory",
    "로키": "Rocky",
    "지지": "Zeze",
    "제제": "Zeze",
    "동9": "dong9",
    "스키다시": "Skidashi",
    "먹꼼": "MUNGOM",
    "뭉꼼": "MUNGOM",
    "도파민": "dopamine",
    "도파": "dopamine",
    "승9": "Seung9",
    "승구": "Seung9",
    "지드래곤": "Gdragon",
    "지드": "Gdragon",
    "파이브": "5making",
    "5메": "5making",
    "어태": "Attaboy",
    "어태보이": "Attaboy",
    "미니": "Miny",
    "은": "eun",
    "이은": "eun",
}

MONTH_NAMES = {
    1: "jan", 2: "feb", 3: "mar", 4: "apr",
    5: "may", 6: "jun", 7: "jul", 8: "aug",
    9: "sep", 10: "oct", 11: "nov", 12: "dec"
}


# ===== 닉네임 변환 =====
def resolve_id(nick: str) -> str:
    nick = nick.strip()
    if nick in NICK_MAP:
        return NICK_MAP[nick]
    lower = nick.lower()
    for k, v in NICK_MAP.items():
        if k.lower() == lower:
            return v
    return nick  # 매핑 없으면 그대로 사용


# ===== 처리된 ID 관리 =====
def load_processed_ids() -> set:
    if PROCESSED_FILE.exists():
        with open(PROCESSED_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_processed_ids(ids: set):
    PROCESSED_FILE.parent.mkdir(exist_ok=True)
    with open(PROCESSED_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(list(ids)), f)


# ===== 네이버 카페 API =====
def get_headers(accept_html: bool = False) -> dict:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Referer": f"https://cafe.naver.com/f-e/cafes/{CAFE_ID}/menus/{MENU_ID}",
        "Cookie": f"NID_AUT={NID_AUT}; NID_SES={NID_SES}",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8" if accept_html else "application/json",
        "Accept-Language": "ko-KR,ko;q=0.9",
    }


def fetch_article_list(page: int = 1) -> list:
    """
    게시판 글 목록 가져오기 — iframe HTML 파싱 방식
    네이버 카페는 실제 컨텐츠를 iframe 안에 표시하므로
    ArticleList.nhn 엔드포인트로 HTML을 직접 파싱합니다.
    """
    url = (
        f"https://cafe.naver.com/ArticleList.nhn"
        f"?search.clubid={CAFE_ID}"
        f"&search.menuid={MENU_ID}"
        f"&search.boardtype=L"
        f"&search.page={page}"
        f"&userDisplay=20"
    )
    try:
        resp = requests.get(url, headers=get_headers(accept_html=True), timeout=15)
        print(f"  [HTML] 글 목록 상태코드: {resp.status_code}")

        if resp.status_code in (401, 403):
            print("  [오류] 인증 실패 — 쿠키를 다시 복사해주세요.")
            return []

        resp.raise_for_status()

        articles = []
        html = resp.text

        # Next.js 앱: __NEXT_DATA__ JSON에서 게시글 목록 추출
        next_data_match = re.search(r'<script id="__NEXT_DATA__"[^>]*>([\s\S]*?)</script>', html)
        if next_data_match:
            try:
                next_data = json.loads(next_data_match.group(1))
                print(f"  [디버그] __NEXT_DATA__ 발견, 키: {list(next_data.get('props', {}).get('pageProps', {}).keys())[:10]}")

                # 다양한 경로에서 articleList 찾기
                page_props = next_data.get("props", {}).get("pageProps", {})

                candidates = [
                    page_props.get("articleList"),
                    page_props.get("articles"),
                    page_props.get("data", {}).get("articleList") if isinstance(page_props.get("data"), dict) else None,
                    page_props.get("initialData", {}).get("articleList") if isinstance(page_props.get("initialData"), dict) else None,
                ]

                for candidate in candidates:
                    if isinstance(candidate, list) and len(candidate) > 0:
                        for item in candidate:
                            aid = item.get("articleId") or item.get("id")
                            title = item.get("subject") or item.get("title") or item.get("name", "")
                            if aid and title:
                                articles.append({
                                    "articleId": int(aid),
                                    "subject": title.strip(),
                                    "writeDateTimestamp": item.get("writeDateTimestamp") or int(datetime.now().timestamp() * 1000),
                                })
                        if articles:
                            break

                if not articles:
                    print(f"  [디버그] pageProps 전체 키: {json.dumps(list(page_props.keys()))}")
            except Exception as e:
                print(f"  [오류] __NEXT_DATA__ 파싱 실패: {e}")
        else:
            print(f"  [디버그] __NEXT_DATA__ 없음 — 다른 방식 시도")

        # fallback: 직접 API 호출 (카페 내부 API)
        if not articles:
            api_url = (
                f"https://cafe.naver.com/api/cafes/{CAFE_ID}/menus/{MENU_ID}/articles"
                f"?page={page}&perPage=20&orderBy=desc"
            )
            try:
                api_resp = requests.get(api_url, headers=get_headers(), timeout=15)
                print(f"  [API fallback] 상태코드: {api_resp.status_code}")
                if api_resp.status_code == 200:
                    api_data = api_resp.json()
                    print(f"  [API fallback] 응답 키: {list(api_data.keys())[:10]}")
                    raw_list = (
                        api_data.get("articleList")
                        or api_data.get("articles")
                        or api_data.get("result", {}).get("articleList")
                        or []
                    )
                    for item in raw_list:
                        aid = item.get("articleId") or item.get("id")
                        title = item.get("subject") or item.get("title", "")
                        if aid and title:
                            articles.append({
                                "articleId": int(aid),
                                "subject": title.strip(),
                                "writeDateTimestamp": item.get("writeDateTimestamp") or int(datetime.now().timestamp() * 1000),
                            })
            except Exception as e:
                print(f"  [API fallback] 실패: {e}")

        # 게시글 링크 패턴: articleid=숫자
        # 예: href="...articleid=733&..."
        article_ids = re.findall(r'articleid=(\d+)', html)
        seen = set()

        # 제목 파싱: <a ...>제목</a> 구조에서 추출
        # 링크에서 articleid와 제목 동시 추출
        link_pattern = re.compile(
            r'<a[^>]+articleid=(\d+)[^>]*>(.*?)</a>',
            re.DOTALL | re.IGNORECASE
        )

        for m in link_pattern.finditer(html):
            aid = int(m.group(1))
            if aid in seen:
                continue
            seen.add(aid)

            raw_title = m.group(2)
            # HTML 태그 제거 & 공백 정리
            title = re.sub(r'<[^>]+>', '', raw_title).strip()
            title = re.sub(r'\s+', ' ', title)

            # 빈 제목이나 숫자만 있는 경우 스킵
            if not title or title.isdigit():
                continue

            articles.append({
                "articleId": aid,
                "subject": title,
                "writeDateTimestamp": int(datetime.now().timestamp() * 1000),
            })

        print(f"  [HTML] 페이지 {page}: {len(articles)}개 글 파싱됨")
        return articles

    except Exception as e:
        print(f"  [오류] 글 목록 가져오기 실패: {e}")
        return []


def fetch_article_content(article_id: int) -> str:
    """
    게시글 본문 가져오기 — iframe HTML 직접 파싱
    네이버 카페 글은 iframe 내부에 렌더링되므로
    ArticleRead.nhn으로 접근합니다.
    """
    url = (
        f"https://cafe.naver.com/ArticleRead.nhn"
        f"?clubid={CAFE_ID}&articleid={article_id}"
    )
    try:
        resp = requests.get(url, headers=get_headers(accept_html=True), timeout=15)
        print(f"  [HTML] 본문 상태코드: {resp.status_code} (ID:{article_id})")
        resp.raise_for_status()

        html = resp.text

        # 본문 영역 추출: se-main-container 또는 ArticleContentBox
        content = ""

        # 방법1: 본문 div 추출
        body_patterns = [
            r'<div[^>]+class="[^"]*se-main-container[^"]*"[^>]*>([\s\S]*?)</div>\s*</div>\s*</div>',
            r'<div[^>]+id="tbody"[^>]*>([\s\S]*?)</div>',
            r'<div[^>]+class="[^"]*article_body[^"]*"[^>]*>([\s\S]*?)</div>',
        ]

        for pat in body_patterns:
            m = re.search(pat, html, re.IGNORECASE)
            if m:
                content = m.group(1)
                break

        # 방법2: 전체 HTML에서 텍스트 추출 (fallback)
        if not content:
            content = html

        # HTML → 텍스트 변환
        content = re.sub(r'<br\s*/?>', '\n', content, flags=re.IGNORECASE)
        content = re.sub(r'<[^>]+>', ' ', content)
        content = re.sub(r'&nbsp;', ' ', content)
        content = re.sub(r'&lt;', '<', content)
        content = re.sub(r'&gt;', '>', content)
        content = re.sub(r'&amp;', '&', content)
        content = re.sub(r'&#39;', "'", content)
        content = re.sub(r'[ \t]+', ' ', content)
        content = re.sub(r'\n{3,}', '\n\n', content)

        result = content.strip()
        print(f"  [HTML] 본문 길이: {len(result)}자")
        return result

    except Exception as e:
        print(f"  [오류] 글 본문 가져오기 실패 (ID:{article_id}): {e}")
        return ""


def is_proleague_post(title: str) -> bool:
    """프로리그 경기 결과 게시글인지 판별"""
    title = title.strip()
    # "N월 N일 프로리그 N차" 패턴
    if re.search(r"\d+월\s*\d+일\s*프로리그\s*\d+차", title):
        return True
    return False


def extract_match_date(title: str, post_date: str) -> str:
    """게시글 제목에서 날짜 추출. 예: '2월 25일' → '2026-02-25'"""
    m = re.search(r"(\d+)월\s*(\d+)일", title)
    if m:
        month = int(m.group(1))
        day = int(m.group(2))
        # 연도는 게시글 작성년도 기준
        year = int(post_date[:4]) if post_date else datetime.now().year
        return f"{year}-{month:02d}-{day:02d}"
    return post_date[:10] if post_date else datetime.now().strftime("%Y-%m-%d")


# ===== 게시글 파싱 =====
def parse_post_content(text: str, match_date: str) -> list:
    """카페 게시글 본문 → JSON 엔트리 리스트"""
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    entries = []

    team1, team2 = [], []

    # 팀 구성 추출
    for line in lines:
        if "Team#1" in line or "팀#1" in line or "team#1" in line.lower():
            part = re.split(r"[:：]", line, 1)[-1].strip()
            team1 = [resolve_id(n) for n in re.split(r"[\s,]+", part) if n]
        elif "Team#2" in line or "팀#2" in line or "team#2" in line.lower():
            part = re.split(r"[:：]", line, 1)[-1].strip()
            team2 = [resolve_id(n) for n in re.split(r"[\s,]+", part) if n]

    # 세트 결과 추출
    set_pattern = re.compile(r"^(\d+)set\s*[▶►▸>]\s*(.+)", re.IGNORECASE)
    sets = []
    for line in lines:
        m = set_pattern.match(line)
        if m:
            sets.append((int(m.group(1)), m.group(2).strip()))

    if not sets:
        print(f"  [경고] 세트 정보 없음, 건너뜀")
        return []

    # 최종 스코어 & 승리팀 결정
    last_raw = sets[-1][1]
    score_m = re.search(r"(\d+:\d+)\s*$", last_raw)
    final_score = score_m.group(1) if score_m else ""
    winner_team = []
    if final_score:
        a, b = map(int, final_score.split(":"))
        winner_team = team1 if a > b else team2

    # Match 헤더
    entries.append({
        "date": match_date,
        "map": "Match",
        "team1": team1,
        "team2": team2,
        "winner": winner_team,
        "score": final_score,
    })

    # 각 세트
    for set_num, raw in sets:
        entry = parse_set(raw, match_date, team1, team2)
        if entry:
            entries.append(entry)

    return entries


def parse_set(raw: str, match_date: str, team1: list, team2: list) -> dict | None:
    """세트 한 줄 파싱"""
    parts = [p.strip() for p in raw.split("/")]
    if len(parts) < 2:
        return None

    map_raw = parts[0].strip()
    is_ace = "에결" in map_raw
    map_name = normalize_map(map_raw)

    last_part = parts[-1]
    score_m = re.search(r"(\d+:\d+)\s*$", last_part)
    score = score_m.group(1) if score_m else ""

    # 팀 사이즈 확인 (2:2, 3:3, 4:4)
    team_size_m = re.match(r"^(\d+):(\d+)", map_name)

    if not team_size_m and len(parts) >= 3:
        # 1v1 파싱
        players_line = parts[1]
        vs_m = re.search(r"^(.+?)\s+vs\s+(.+)$", players_line, re.IGNORECASE)
        if vs_m:
            p1 = resolve_id(vs_m.group(1).strip())
            p2 = resolve_id(vs_m.group(2).strip())
            winner_line = parts[2]
            winner = determine_winner_1v1(winner_line, p1, p2, vs_m.group(1), vs_m.group(2))
            return {
                "date": match_date,
                "map": map_name,
                "player1": p1,
                "player2": p2,
                "winner": winner,
                "score": score,
            }

    # 팀전 파싱
    winner_line = parts[-1]

    # "스트 , 비니 vs 달선 , 제주" 형식 (vs가 있는 경우)
    for part in parts[1:]:
        vs_idx = part.lower().find(" vs ")
        if vs_idx >= 0:
            left_raw = part[:vs_idx]
            right_raw = part[vs_idx + 4:]
            left = [resolve_id(n) for n in re.split(r"[\s,]+", left_raw) if n]
            right = [resolve_id(n) for n in re.split(r"[\s,]+", right_raw) if n]

            win_names = [resolve_id(n) for n in re.split(r"[\s,]+", winner_line.split("승")[0]) if n]
            winner = left if any(w in left for w in win_names) else right

            return {
                "date": match_date,
                "map": map_name,
                "team1": left,
                "team2": right,
                "winner": winner,
                "score": score,
            }

    # "낭만팀 승" 형식
    t1_win = any(
        kw in winner_line for kw in ["낭만팀", "Team1", "팀1", "#1팀", "1팀"]
    ) or any(resolve_id(n) in winner_line for n in ["낭만", "스트", "팡", "비니"])
    winner = team1 if t1_win else team2

    return {
        "date": match_date,
        "map": map_name,
        "team1": team1,
        "team2": team2,
        "winner": winner,
        "score": score,
    }


def determine_winner_1v1(winner_line, p1_id, p2_id, p1_raw, p2_raw) -> str:
    """1v1 승자 판별"""
    wl = winner_line.replace("승", "").strip()
    wl_resolved = resolve_id(wl)
    if wl_resolved == p1_id or p1_raw.strip() in winner_line:
        return p1_id
    if wl_resolved == p2_id or p2_raw.strip() in winner_line:
        return p2_id
    return p1_id  # fallback


def normalize_map(raw: str) -> str:
    """맵 이름 정규화"""
    raw = raw.strip()
    if "에결" in raw:
        return "투혼(에결)"
    # "2:2투혼", "3:3헌터" 등 유지
    m = re.match(r"^(\d+)[:\s]?(\d+)\s*(.+)", raw)
    if m:
        return f"{m.group(1)}:{m.group(2)}{m.group(3)}"
    return raw


# ===== index.html 자동 업데이트 =====
def update_index_html(new_month_filename: str):
    """
    index.html에 새 월 데이터 파일 참조를 자동으로 추가.

    index.html 안에는 아래 패턴이 두 군데 있음:
      const months = ['oct','nov','dec','jan','feb'];
    → 새 월(예: 'mar')을 배열 끝에 자동으로 추가.
    """
    index_path = REPO_ROOT / "index.html"
    if not index_path.exists():
        print(f"  [경고] index.html 없음, 건너뜀")
        return

    # new_month_filename: "data_mar.json" → month_key: "mar"
    month_key = new_month_filename.replace("data_", "").replace(".json", "")

    with open(index_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 이미 포함되어 있으면 패스
    if f"'{month_key}'" in content or f'"{month_key}"' in content:
        print(f"  [정보] index.html에 이미 '{month_key}' 존재, 건너뜀")
        return

    # 패턴: const months = ['oct','nov','dec','jan','feb'];
    # 따옴표 종류(', ")에 상관없이 배열 끝 항목 뒤에 새 month_key 삽입
    pattern = re.compile(
        r"(const\s+months\s*=\s*\[)([\s\S]*?)(\];)"
    )

    updated_count = 0

    def replacer(m):
        nonlocal updated_count
        prefix = m.group(1)   # "const months = ["
        body   = m.group(2)   # "'oct','nov','dec','jan','feb'"
        suffix = m.group(3)   # "];"

        # 기존 따옴표 스타일 감지 (작은따옴표 우선)
        quote = "'" if "'" in body else '"'

        # 이미 있으면 스킵
        if f"{quote}{month_key}{quote}" in body:
            return m.group(0)

        # 마지막 항목 뒤에 추가
        new_body = body.rstrip()
        if new_body.endswith(","):
            new_body += f" {quote}{month_key}{quote}"
        else:
            new_body += f", {quote}{month_key}{quote}"

        updated_count += 1
        return prefix + new_body + suffix

    new_content = pattern.sub(replacer, content)

    if updated_count == 0:
        print(f"  [경고] index.html에서 'const months = [...]' 패턴을 찾지 못했어요.")
        print(f"         index.html을 직접 확인하고 '{month_key}'를 수동으로 추가해주세요.")
        return

    with open(index_path, "w", encoding="utf-8") as f:
        f.write(new_content)

    print(f"  [업데이트] index.html의 months 배열 {updated_count}곳에 '{month_key}' 추가 완료")


# ===== JSON 파일 관리 =====
def get_data_file(match_date: str) -> Path:
    """날짜에 맞는 JSON 파일 경로 반환"""
    try:
        dt = datetime.strptime(match_date, "%Y-%m-%d")
        month_name = MONTH_NAMES.get(dt.month, f"m{dt.month:02d}")
        return REPO_ROOT / f"data_{month_name}.json"
    except Exception:
        return REPO_ROOT / "data.json"


def load_json_file(path: Path) -> dict:
    """JSON 파일 로드"""
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    # 새 파일 생성
    try:
        dt = datetime.strptime(path.stem.replace("data_", ""), "%b")
        month_str = dt.strftime("%B %Y").replace(
            dt.strftime("%Y"), str(datetime.now().year)
        )
    except Exception:
        month_str = datetime.now().strftime("%B %Y")
    return {
        "month": month_str,
        "matches": [],
        "generated_at": datetime.now().isoformat() + "Z",
    }


def save_json_file(path: Path, data: dict):
    """JSON 파일 저장"""
    data["generated_at"] = datetime.now().isoformat() + "Z"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  [저장] {path.name}")


def append_entries(path: Path, entries: list):
    """JSON 파일에 엔트리 추가"""
    data = load_json_file(path)
    data["matches"].extend(entries)
    save_json_file(path, data)


def fetch_article_by_id(article_id: int):
    """
    게시글 ID로 직접 접근해서 제목 + 본문 + 날짜 반환.
    실패 시 (None, None, None) 반환.
    """
    # 두 가지 URL 시도
    urls = [
        f"https://cafe.naver.com/ArticleRead.nhn?clubid={CAFE_ID}&articleid={article_id}",
        f"https://cafe.naver.com/f-e/cafes/{CAFE_ID}/articles/{article_id}",
    ]

    for url in urls:
        try:
            resp = requests.get(url, headers=get_headers(accept_html=True), timeout=15)
            print(f"  [HTTP] {resp.status_code} ← {url.split('?')[0].split('/')[-1]}")

            if resp.status_code == 404:
                return None, None, None
            if resp.status_code in (401, 403):
                print("  [오류] 인증 실패 — 쿠키를 확인하세요.")
                return None, None, None
            if not resp.ok:
                continue

            html = resp.text

            # 제목 추출
            title = ""
            title_patterns = [
                r'<meta property="og:title" content="([^"]+)"',
                r'<title>([^<]+)</title>',
                r'"subject"\s*:\s*"([^"]+)"',
                r'<h3[^>]+class="[^"]*title[^"]*"[^>]*>([^<]+)</h3>',
            ]
            for pat in title_patterns:
                m = re.search(pat, html)
                if m:
                    title = m.group(1).strip()
                    # og:title에 카페 이름이 붙는 경우 제거 ("제목 : 카페명" 형태)
                    title = re.sub(r'\s*[:\|]\s*.*카페.*$', '', title).strip()
                    title = re.sub(r'\s*[:\|]\s*RockClan.*$', '', title, flags=re.IGNORECASE).strip()
                    if title and len(title) > 2:
                        break

            # 날짜 추출
            post_date_str = datetime.now().strftime("%Y-%m-%d")
            date_patterns = [
                r'"writeDateTimestamp"\s*:\s*(\d+)',
                r'"writeDate"\s*:\s*"(\d{4}-\d{2}-\d{2})',
                r'<meta[^>]+property="article:published_time"[^>]+content="(\d{4}-\d{2}-\d{2})',
            ]
            for pat in date_patterns:
                m = re.search(pat, html)
                if m:
                    val = m.group(1)
                    if val.isdigit():
                        post_date_str = datetime.fromtimestamp(int(val)/1000).strftime("%Y-%m-%d")
                    else:
                        post_date_str = val[:10]
                    break

            # 본문 추출
            content = fetch_article_content_from_html(html, article_id)

            if title or content:
                print(f"  [파싱] 제목: '{title}' / 날짜: {post_date_str} / 본문: {len(content)}자")
                return title, content, post_date_str

        except Exception as e:
            print(f"  [오류] ID {article_id} 접근 실패: {e}")
            continue

    return None, None, None


def fetch_article_content_from_html(html: str, article_id: int) -> str:
    """HTML에서 본문 텍스트 추출"""
    content = ""

    # 본문 영역 추출 시도
    body_patterns = [
        r'<div[^>]+class="[^"]*se-main-container[^"]*"[^>]*>([\s\S]{100,}?)</div>\s*(?:</div>\s*){2}',
        r'<div[^>]+id="tbody"[^>]*>([\s\S]{50,}?)</div>',
        r'"contentHtml"\s*:\s*"([\s\S]+?)"(?:,|\})',
        r'<div[^>]+class="[^"]*article_body[^"]*"[^>]*>([\s\S]{50,}?)</div>',
    ]
    for pat in body_patterns:
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            content = m.group(1)
            break

    if not content:
        content = html

    # HTML → 텍스트
    content = re.sub(r'<br\s*/?>', '\n', content, flags=re.IGNORECASE)
    content = re.sub(r'</p>', '\n', content, flags=re.IGNORECASE)
    content = re.sub(r'<[^>]+>', ' ', content)
    content = re.sub(r'&nbsp;', ' ', content)
    content = re.sub(r'&lt;', '<', content)
    content = re.sub(r'&gt;', '>', content)
    content = re.sub(r'&amp;', '&', content)
    content = re.sub(r'&#39;', "'", content)
    content = re.sub(r'[ \t]+', ' ', content)
    content = re.sub(r'\n{3,}', '\n\n', content)
    return content.strip()


# ===== 메인 =====
def main():
    print(f"[시작] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    if not NID_AUT or not NID_SES:
        print("[오류] 네이버 쿠키가 설정되지 않았습니다. GitHub Secrets를 확인하세요.")
        return

    print(f"[정보] 쿠키 확인 — NID_AUT: {'✅ 설정됨' if NID_AUT else '❌ 없음'} / NID_SES: {'✅ 설정됨' if NID_SES else '❌ 없음'}")
    print(f"[정보] 카페ID: {CAFE_ID}, 메뉴ID: {MENU_ID}")

    processed_ids = load_processed_ids()
    new_entries_count = 0

    # 시작 ID: 처리된 ID 중 최대값 + 1
    start_id = max(processed_ids) + 1 if processed_ids else 741
    print(f"[정보] 기처리 게시글 수: {len(processed_ids)}, 시작 ID: {start_id}")

    # 연속 실패 횟수 (N번 연속 실패하면 종료 — 게시글 번호 공백 허용)
    MAX_CONSECUTIVE_FAILS = 10
    consecutive_fails = 0
    current_id = start_id

    while consecutive_fails < MAX_CONSECUTIVE_FAILS:
        if current_id in processed_ids:
            current_id += 1
            continue

        print(f"\n[시도] 게시글 ID: {current_id}")
        title, content, post_date_str = fetch_article_by_id(current_id)

        if title is None:
            # 존재하지 않는 글 or 접근 불가
            consecutive_fails += 1
            print(f"  [스킵] 연속 실패 {consecutive_fails}/{MAX_CONSECUTIVE_FAILS}")
            current_id += 1
            continue

        consecutive_fails = 0  # 성공하면 카운터 리셋
        processed_ids.add(current_id)

        if not is_proleague_post(title):
            print(f"  [건너뜀] '{title}' — 프로리그 글 아님")
            current_id += 1
            continue

        print(f"  [처리] '{title}'")

        match_date = extract_match_date(title, post_date_str)
        print(f"  경기 날짜: {match_date}")

        if not content:
            print(f"  [경고] 본문 없음, 건너뜀")
            current_id += 1
            continue

        entries = parse_post_content(content, match_date)
        if not entries:
            print(f"  [경고] 파싱 실패, 건너뜀")
            current_id += 1
            continue

        print(f"  파싱된 항목 수: {len(entries)}")

        data_file = get_data_file(match_date)
        is_new_file = not data_file.exists()
        append_entries(data_file, entries)
        if is_new_file:
            print(f"  [신규] {data_file.name} 새로 생성 → index.html 업데이트")
            update_index_html(data_file.name)

        new_entries_count += len(entries)
        current_id += 1

    save_processed_ids(processed_ids)
    print(f"\n[완료] 새로 추가된 항목: {new_entries_count}개 (마지막 확인 ID: {current_id - 1})")


if __name__ == "__main__":
    main()
