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
def get_headers() -> dict:
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": f"https://cafe.naver.com/f-e/cafes/{CAFE_ID}/menus/{MENU_ID}",
        "Cookie": f"NID_AUT={NID_AUT}; NID_SES={NID_SES}",
        "Accept": "application/json",
    }


def fetch_article_list(page: int = 1) -> list:
    """게시판 글 목록 가져오기"""
    url = (
        f"https://apis.naver.com/cafe-web/cafe2/ArticleListV2.json"
        f"?cafeId={CAFE_ID}&menuId={MENU_ID}&pageSize=20&page={page}"
        f"&boardType=L&userIdType=nickName&orderBy=date"
    )
    try:
        resp = requests.get(url, headers=get_headers(), timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return data.get("message", {}).get("result", {}).get("articleList", [])
    except Exception as e:
        print(f"[오류] 글 목록 가져오기 실패: {e}")
        return []


def fetch_article_content(article_id: int) -> str:
    """게시글 본문 가져오기"""
    url = (
        f"https://apis.naver.com/cafe-web/cafe-articleapi/v2"
        f"/cafes/{CAFE_ID}/articles/{article_id}"
    )
    try:
        resp = requests.get(url, headers=get_headers(), timeout=15)
        resp.raise_for_status()
        data = resp.json()
        result = data.get("result", {})
        content = result.get("article", {}).get("contentHtml", "")
        # HTML 태그 제거
        content = re.sub(r"<[^>]+>", "\n", content)
        content = re.sub(r"&nbsp;", " ", content)
        content = re.sub(r"&lt;", "<", content)
        content = re.sub(r"&gt;", ">", content)
        content = re.sub(r"\n{3,}", "\n\n", content)
        return content.strip()
    except Exception as e:
        print(f"[오류] 글 본문 가져오기 실패 (ID:{article_id}): {e}")
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


# ===== 메인 =====
def main():
    print(f"[시작] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    if not NID_AUT or not NID_SES:
        print("[오류] 네이버 쿠키가 설정되지 않았습니다. GitHub Secrets를 확인하세요.")
        return

    processed_ids = load_processed_ids()
    new_entries_count = 0

    print(f"[정보] 기처리 게시글 수: {len(processed_ids)}")

    # 최근 글 목록 가져오기 (2페이지까지)
    articles = []
    for page in range(1, 3):
        articles.extend(fetch_article_list(page))

    print(f"[정보] 가져온 글 수: {len(articles)}")

    # 프로리그 게시글 필터링 & 처리
    for article in articles:
        article_id = article.get("articleId")
        title = article.get("subject", "")
        post_date = article.get("writeDateTimestamp", "")

        if not article_id or article_id in processed_ids:
            continue

        if not is_proleague_post(title):
            print(f"  [건너뜀] '{title}'")
            continue

        print(f"\n[처리] {title} (ID: {article_id})")

        # 게시글 작성일 파싱
        try:
            post_date_str = datetime.fromtimestamp(post_date / 1000).strftime("%Y-%m-%d")
        except Exception:
            post_date_str = datetime.now().strftime("%Y-%m-%d")

        # 경기 날짜 추출
        match_date = extract_match_date(title, post_date_str)
        print(f"  경기 날짜: {match_date}")

        # 본문 가져오기
        content = fetch_article_content(article_id)
        if not content:
            print(f"  [경고] 본문 없음, 건너뜀")
            continue

        # 파싱
        entries = parse_post_content(content, match_date)
        if not entries:
            print(f"  [경고] 파싱 실패, 건너뜀")
            continue

        print(f"  파싱된 항목 수: {len(entries)}")

        # JSON 파일에 추가
        data_file = get_data_file(match_date)
        append_entries(data_file, entries)

        processed_ids.add(article_id)
        new_entries_count += len(entries)

    # 처리된 ID 저장
    save_processed_ids(processed_ids)

    print(f"\n[완료] 새로 추가된 항목: {new_entries_count}개")


if __name__ == "__main__":
    main()
