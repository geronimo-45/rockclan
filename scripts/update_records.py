"""
RockClan 프로리그 기록실 자동화 스크립트
Playwright(헤드리스 크롬)으로 JavaScript SPA 렌더링
"""
import os, json, re
from datetime import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright

CAFE_ID   = "31553306"
MENU_ID   = "29"
REPO_ROOT = Path(__file__).parent.parent
PROCESSED_FILE = REPO_ROOT / "scripts" / "processed_ids.json"

NID_AUT         = os.environ.get("NAVER_NID_AUT", "")
NID_SES         = os.environ.get("NAVER_NID_SES", "")
CAFE_JSESSIONID = os.environ.get("CAFE_JSESSIONID", "")
CAFE_NCI4       = os.environ.get("CAFE_NCI4", "")
CAFE_NCMC4      = os.environ.get("CAFE_NCMC4", "")
CAFE_NCU        = os.environ.get("CAFE_NCU", "")
CAFE_NCVC2      = os.environ.get("CAFE_NCVC2", "")
CAFE_NCVID      = os.environ.get("CAFE_NCVID", "")

NICK_MAP = {
    "낭만":"Nangman","스트":"Strive","스트라이브":"Strive","팡":"Pang","비니":"Veeny",
    "루빡":"Rupark","달선":"dalsun2","제주":"JeJu","미스티":"MiSTY",
    "고마진":"GgoMajin","g마진":"GgoMajin","g마":"GgoMajin","현호":"Hyunho",
    "프렌드":"Friend","글로리":"Glory","로키":"Rocky","지지":"Zeze","제제":"Zeze",
    "동9":"dong9","스키다시":"Skidashi","먹꼼":"MUNGOM","뭉꼼":"MUNGOM",
    "도파민":"dopamine","도파":"dopamine","승9":"Seung9","승구":"Seung9",
    "지드래곤":"Gdragon","지드":"Gdragon","파이브":"5making","5메":"5making",
    "어태":"Attaboy","어태보이":"Attaboy","미니":"Miny","은":"eun","이은":"eun",
}
MONTH_NAMES = {1:"jan",2:"feb",3:"mar",4:"apr",5:"may",6:"jun",
               7:"jul",8:"aug",9:"sep",10:"oct",11:"nov",12:"dec"}

def resolve_id(nick):
    nick = nick.strip()
    if nick in NICK_MAP: return NICK_MAP[nick]
    for k,v in NICK_MAP.items():
        if k.lower()==nick.lower(): return v
    return nick

def load_processed_ids():
    if PROCESSED_FILE.exists():
        with open(PROCESSED_FILE,"r",encoding="utf-8") as f:
            return set(json.load(f))
    return set()

def save_processed_ids(ids):
    PROCESSED_FILE.parent.mkdir(exist_ok=True)
    with open(PROCESSED_FILE,"w",encoding="utf-8") as f:
        json.dump(sorted(list(ids)),f)

def build_cookies():
    """Playwright용 쿠키 목록 생성"""
    cookie_defs = [
        ("NID_AUT",    NID_AUT,         ".naver.com"),
        ("NID_SES",    NID_SES,         ".naver.com"),
        ("JSESSIONID", CAFE_JSESSIONID, ".cafe.naver.com"),
        ("nci4",       CAFE_NCI4,       ".cafe.naver.com"),
        ("ncmc4",      CAFE_NCMC4,      ".cafe.naver.com"),
        ("ncu",        CAFE_NCU,        ".cafe.naver.com"),
        ("ncvc2",      CAFE_NCVC2,      ".cafe.naver.com"),
        ("ncvid",      CAFE_NCVID,      ".cafe.naver.com"),
    ]
    return [
        {"name": name, "value": val, "domain": domain, "path": "/"}
        for name, val, domain in cookie_defs if val
    ]

def fetch_article_by_id(page, article_id):
    """Playwright로 게시글 접근 → (제목, 본문, 날짜) 반환"""
    target_url = f"https://cafe.naver.com/f-e/cafes/{CAFE_ID}/articles/{article_id}"
    try:
        resp = page.goto(target_url, wait_until="networkidle", timeout=30000)
        print(f"  [HTTP] {resp.status if resp else '?'}")

        if resp and resp.status == 404:
            return None, None, None

        # 리다이렉트 감지: 내소식 또는 다른 페이지로 이동했으면 글 없음
        current_url = page.url
        if "articleid" not in current_url and f"articles/{article_id}" not in current_url:
            print(f"  [리다이렉트] {current_url[:80]} → 글 없음")
            return None, None, None

        # 페이지 렌더링 대기
        try:
            page.wait_for_selector(
                "h3.ArticleTitle, .article_header h3, .se-module-text, .ArticleWriteFormView",
                timeout=10000
            )
        except:
            pass

        html = page.content()
        title_el = None

        # 제목 추출 시도 (더 많은 셀렉터)
        for selector in [
            "h3.ArticleTitle",
            ".article_header h3",
            ".ArticleTitle",
            ".tit_h1",
            "h3.title",
            ".article-head h3",
            ".ArticleTitle__title",
            "[class*='ArticleTitle']",
            "[class*='article-title']",
            "[class*='article_title']",
        ]:
            try:
                el = page.query_selector(selector)
                if el:
                    t = el.inner_text().strip()
                    if t and t not in ("네이버 카페","내소식","") and len(t) > 2:
                        title_el = t
                        print(f"  [셀렉터] '{selector}' → '{t}'")
                        break
            except: pass

        # og:title 시도
        if not title_el:
            m = re.search(r'<meta property="og:title" content="([^"]+)"', html)
            if m:
                t = m.group(1).strip()
                if t and t not in ("네이버 카페","NAVER","내소식") and len(t) > 2:
                    title_el = t
                    print(f"  [og:title] '{t}'")

        # 마지막: 모든 텍스트에서 프로리그 패턴 직접 검색
        if not title_el:
            m = re.search(r"(\d+월\s*\d+일\s*프로리그\s*\d+차[^<\"\n]*)", html)
            if m:
                title_el = m.group(1).strip()
                print(f"  [직접검색] '{title_el}'")

        # 디버그: 페이지의 모든 h2, h3 요소 출력
        if not title_el:
            print("  [디버그] 페이지 h2/h3 목록:")
            for tag in ["h1","h2","h3","h4"]:
                els = page.query_selector_all(tag)
                for el in els[:5]:
                    try: print(f"    <{tag}> '{el.inner_text().strip()[:80]}'")
                    except: pass
            print("  [디버그] class에 title 포함 요소:")
            els = page.query_selector_all("[class*='title']")
            for el in els[:10]:
                try:
                    cls = el.get_attribute("class") or ""
                    txt = el.inner_text().strip()[:60]
                    if txt: print(f"    class='{cls[:40]}' → '{txt}'")
                except: pass
            print(f"  [실패] 제목 없음 (URL:{current_url[:60]})")
            return None, None, None

        # 날짜 추출
        post_date_str = datetime.now().strftime("%Y-%m-%d")
        for pat in [r'"writeDateTimestamp"\s*:\s*(\d{10,})',
                    r'"writeDate"\s*:\s*"(\d{4}-\d{2}-\d{2})',
                    r'<span[^>]*class="[^"]*date[^"]*"[^>]*>(\d{4}\.\d{2}\.\d{2})']:
            m = re.search(pat, html)
            if m:
                val = m.group(1)
                if val.isdigit():
                    post_date_str = datetime.fromtimestamp(int(val)/1000).strftime("%Y-%m-%d")
                else:
                    post_date_str = val[:10].replace(".", "-")
                break

        # 본문 추출
        content = ""
        for selector in [".se-main-container", ".article_body", "#tbody", ".ArticleContentBox"]:
            try:
                el = page.query_selector(selector)
                if el:
                    content = el.inner_text()
                    break
            except: pass

        if not content:
            content = page.inner_text("body") if page.query_selector("body") else ""

        content = re.sub(r'[ \t]+',' ', content)
        content = re.sub(r'\n{3,}','\n\n', content).strip()

        print(f"  [파싱] 제목:'{title_el}' / 날짜:{post_date_str} / 본문:{len(content)}자")
        return title_el, content, post_date_str

    except Exception as e:
        print(f"  [오류] {e}")
        return None, None, None

def is_proleague_post(title):
    return bool(re.search(r"\d+월\s*\d+일\s*프로리그\s*\d+차", title.strip()))

def extract_match_date(title, post_date):
    m = re.search(r"(\d+)월\s*(\d+)일", title)
    if m:
        month,day = int(m.group(1)),int(m.group(2))
        year = int(post_date[:4]) if post_date else datetime.now().year
        return f"{year}-{month:02d}-{day:02d}"
    return post_date[:10] if post_date else datetime.now().strftime("%Y-%m-%d")

def parse_post_content(text, match_date):
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    team1,team2 = [],[]
    for line in lines:
        if re.search(r"Team#?1|팀#?1",line,re.IGNORECASE):
            part = re.split(r"[:：]",line,1)[-1].strip()
            team1 = [resolve_id(n) for n in re.split(r"[\s,]+",part) if n]
        elif re.search(r"Team#?2|팀#?2",line,re.IGNORECASE):
            part = re.split(r"[:：]",line,1)[-1].strip()
            team2 = [resolve_id(n) for n in re.split(r"[\s,]+",part) if n]

    pat = re.compile(r"^(\d+)set\s*[▶►▸>]\s*(.+)",re.IGNORECASE)
    sets = [(int(m.group(1)),m.group(2).strip()) for line in lines for m in [pat.match(line)] if m]
    if not sets:
        print("  [경고] 세트 정보 없음"); return []

    score_m = re.search(r"(\d+:\d+)\s*$", sets[-1][1])
    final_score = score_m.group(1) if score_m else ""
    winner_team = []
    if final_score:
        a,b = map(int,final_score.split(":"))
        winner_team = team1 if a>b else team2

    entries = [{"date":match_date,"map":"Match","team1":team1,"team2":team2,
                "winner":winner_team,"score":final_score}]
    for _,raw in sets:
        e = parse_set(raw,match_date,team1,team2)
        if e: entries.append(e)
    return entries

def parse_set(raw, match_date, team1, team2):
    parts = [p.strip() for p in raw.split("/")]
    if len(parts)<2: return None
    map_name = normalize_map(parts[0])
    score_m = re.search(r"(\d+:\d+)\s*$",parts[-1])
    score = score_m.group(1) if score_m else ""
    if not re.match(r"^\d+:\d+",map_name) and len(parts)>=3:
        vs_m = re.search(r"^(.+?)\s+vs\s+(.+)$",parts[1],re.IGNORECASE)
        if vs_m:
            p1,p2 = resolve_id(vs_m.group(1).strip()),resolve_id(vs_m.group(2).strip())
            winner = p1 if (vs_m.group(1).strip() in parts[2] or p1 in parts[2]) else p2
            return {"date":match_date,"map":map_name,"player1":p1,"player2":p2,"winner":winner,"score":score}
    for part in parts[1:]:
        vi = part.lower().find(" vs ")
        if vi>=0:
            left  = [resolve_id(n) for n in re.split(r"[\s,]+",part[:vi]) if n]
            right = [resolve_id(n) for n in re.split(r"[\s,]+",part[vi+4:]) if n]
            wn = [resolve_id(n) for n in re.split(r"[\s,]+",parts[-1].split("승")[0]) if n]
            winner = left if any(w in left for w in wn) else right
            return {"date":match_date,"map":map_name,"team1":left,"team2":right,"winner":winner,"score":score}
    t1_win = any(kw in parts[-1] for kw in ["낭만팀","1팀","Team1","#1팀"])
    return {"date":match_date,"map":map_name,"team1":team1,"team2":team2,
            "winner":team1 if t1_win else team2,"score":score}

def normalize_map(raw):
    raw = raw.strip()
    if "에결" in raw: return "투혼(에결)"
    m = re.match(r"^(\d+)[:\s]?(\d+)\s*(.+)",raw)
    return f"{m.group(1)}:{m.group(2)}{m.group(3)}" if m else raw

def get_data_file(match_date):
    try:
        dt = datetime.strptime(match_date,"%Y-%m-%d")
        return REPO_ROOT / f"data_{MONTH_NAMES.get(dt.month,f'm{dt.month:02d}')}.json"
    except: return REPO_ROOT/"data.json"

def load_json_file(path):
    if path.exists():
        with open(path,"r",encoding="utf-8") as f: return json.load(f)
    return {"month":path.stem,"matches":[],"generated_at":""}

def save_json_file(path, data):
    data["generated_at"] = datetime.now().isoformat()+"Z"
    with open(path,"w",encoding="utf-8") as f: json.dump(data,f,ensure_ascii=False,indent=2)
    print(f"  [저장] {path.name}")

def append_entries(path, entries):
    data = load_json_file(path)
    data["matches"].extend(entries)
    save_json_file(path, data)

def update_index_html(new_month_filename):
    index_path = REPO_ROOT/"index.html"
    if not index_path.exists(): return
    month_key = new_month_filename.replace("data_","").replace(".json","")
    with open(index_path,"r",encoding="utf-8") as f: content = f.read()
    if f"'{month_key}'" in content or f'"{month_key}"' in content: return
    updated = 0
    def rep(m):
        nonlocal updated
        pre,body,suf = m.group(1),m.group(2),m.group(3)
        q = "'" if "'" in body else '"'
        nb = body.rstrip() + ("" if body.rstrip().endswith(",") else ",") + f" {q}{month_key}{q}"
        updated += 1; return pre+nb+suf
    nc = re.sub(r"(const\s+months\s*=\s*\[)([\s\S]*?)(\];)",rep,content)
    if updated:
        with open(index_path,"w",encoding="utf-8") as f: f.write(nc)
        print(f"  [업데이트] index.html에 '{month_key}' 추가")

def main():
    print(f"[시작] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    if not NID_AUT or not NID_SES:
        print("[오류] 쿠키 없음"); return
    print(f"[정보] NID_AUT:✅ NID_SES:✅ JSESSIONID:{'✅' if CAFE_JSESSIONID else '❌'}")

    processed_ids = load_processed_ids()
    start_id = max(processed_ids)+1 if processed_ids else 741
    print(f"[정보] 기처리:{len(processed_ids)}개, 시작 ID:{start_id}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
            locale="ko-KR",
        )
        # 쿠키 주입
        context.add_cookies(build_cookies())
        page = context.new_page()

        MAX_FAILS,fails,cur,new_count = 10,0,start_id,0
        while fails < MAX_FAILS:
            if cur in processed_ids: cur+=1; continue
            print(f"\n[시도] ID:{cur}")
            title,content,post_date = fetch_article_by_id(page, cur)
            if title is None:
                fails+=1; print(f"  [스킵] 연속실패 {fails}/{MAX_FAILS}"); cur+=1; continue
            fails=0; processed_ids.add(cur)
            if not is_proleague_post(title):
                print(f"  [건너뜀] '{title}'"); cur+=1; continue
            print(f"  [처리] '{title}'")
            match_date = extract_match_date(title,post_date)
            print(f"  날짜:{match_date}")
            if not content: print("  [경고] 본문없음"); cur+=1; continue
            entries = parse_post_content(content,match_date)
            if not entries: print("  [경고] 파싱실패"); cur+=1; continue
            print(f"  항목수:{len(entries)}")
            df = get_data_file(match_date)
            is_new = not df.exists()
            append_entries(df,entries)
            if is_new: update_index_html(df.name)
            new_count+=len(entries); cur+=1

        browser.close()

    save_processed_ids(processed_ids)
    print(f"\n[완료] 추가:{new_count}개 / 마지막 ID:{cur-1}")

if __name__ == "__main__":
    main()
