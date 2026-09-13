# -*- coding: utf-8 -*-
"""
src/일정.yaml  ->  <output>.html   (파일명은 일정.yaml 의 output 키)

지도는 지점 위경도만 있으면 투영·축척·마커·라벨·경로선을 자동으로 그립니다.
mapseq 텍스트와 Leaflet 데이터도 같은 소스에서 나오므로 어긋날 수 없습니다.

    python build.py
"""
import io, sys, os, json, math, re, urllib.parse
import yaml

import outpath

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)

NICE_KM = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000]

doc = yaml.safe_load(open('src/일정.yaml', encoding='utf-8'))

# 여행에 관한 값은 전부 일정.yaml 에서 옵니다. 코드에는 여행별 상수가 없습니다.
OUT = outpath.resolve(doc)          # 폴더는 output_dir 이 정합니다 (기본 결과물/)
if not OUT:
    sys.exit("src/일정.yaml 에 'output: 파일명.html' 을 넣으세요.")
RAW_COLORS = dict(doc.get('colors') or {})
if not RAW_COLORS:
    sys.exit("src/일정.yaml 에 'colors: {키: \"#RRGGBB\"}' 를 넣으세요 "
             "(키는 blocks 의 cls 두 번째 낱말과 같아야 합니다).")


def light_of(v):
    """colors 값은 '#RRGGBB' 또는 {light: ..., dark: ...} 둘 다 됩니다."""
    return v['light'] if isinstance(v, dict) else v


def dark_of(v):
    return v.get('dark', v['light']) if isinstance(v, dict) else v


# SVG 안에 박히는 색(마커·경로선)은 라이트 값을 씁니다 — 파일에 굳어지므로
COLOR = {k: light_of(v) for k, v in RAW_COLORS.items()}
COLOR.setdefault('ov', next(iter(COLOR.values())))   # 개요 지도 경로선 색


def _rgb(h):
    h = h.lstrip('#')
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def color_css():
    """나라·지역 색을 토큰으로 만들어 head.html 의 __COLORCSS__ 자리에 넣습니다.

    라이트/다크를 '토큰'에서만 갈라 놓습니다. 그래야 OS 설정(무표시)과
    사용자가 명시한 data-theme 세 상태가 모두 같은 규칙으로 해결됩니다.
    """
    keys = [k for k in RAW_COLORS if k != 'ov']

    def tokens(pick, alpha):
        out = []
        for k in keys:
            col = pick(RAW_COLORS[k])
            r, g, b = _rgb(col)
            out.append('--c-%s:%s; --c-%s-rgb:%d %d %d; --c-%s-a:%s;'
                       % (k, col, k, r, g, b, k, alpha))
        return out

    lt = tokens(light_of, '.10')
    dk = tokens(dark_of, '.14')
    rules = []
    for k in keys:
        rules += [
            '.bar-fill.%s,.swatch.%s,.day.%s .day-rail::before,.day.%s.stay .node'
            '{background:var(--c-%s);}' % (k, k, k, k, k),
            '.ccard.%s{--cc:var(--c-%s);}' % (k, k),
            '.ctr.%s .cdate,.tl.%s .tl-d{border-left-color:var(--c-%s);}' % (k, k, k),
            '.day.%s .node{border-color:var(--c-%s);}' % (k, k),
            '.day.%s .bus{color:var(--c-%s);'
            'background:rgb(var(--c-%s-rgb)/var(--c-%s-a));}' % (k, k, k, k)]
    return ('  :root{\n    ' + '\n    '.join(lt) + '\n  }\n'
            '  @media (prefers-color-scheme:dark){\n    :root:not([data-theme="light"]){\n      '
            + '\n      '.join(dk) + '\n    }\n  }\n'
            '  :root[data-theme="dark"]{\n    ' + '\n    '.join(dk) + '\n  }\n'
            '  ' + '\n  '.join(rules))
OVERVIEW_MAP = doc.get('overview_map')               # 없으면 개요 지도를 넣지 않습니다

# 문단 제목. labels 로 덮어쓰거나 빈 문자열을 주면 그 구획이 사라집니다.
LABELS = {'nights': '숙박 배분', 'overview': '루트 개요', 'flights': '항공편',
          'days': '본 일정', 'notes': '미리 확인할 것', 'regions': '나라별로 보기',
          'view_home': '개요', 'view_all': '전체 일정', 'view_cost': '예상경비',
          'outline': '하루씩 훑어보기', 'moves': '이동 수단', 'move_back': '뒤로',
          'cost_kind': '무엇에 쓰나', 'cost_region': '어디에 쓰나',
          'cost_cash': '통화별로 얼마나 필요한가', 'cost_daily': '일자별',
          'cost_move': '구간별 교통비', 'cost_tick': '입장료', 'cost_rate': '적용 환율'}
LABELS.update(doc.get('labels') or {})
PROJ = json.load(open('src/basemaps/_proj.json', encoding='utf-8'))
HEAD = open('src/head.html', encoding='utf-8').read()
SCRIPT = open('src/script.html', encoding='utf-8').read()

# 예산.yaml 이 있으면 '예상경비' 탭이 자동으로 붙습니다 (없으면 그 탭만 빠집니다)
BUDGET_SRC = doc.get('budget_source', 'src/예산.yaml')
BUD = (yaml.safe_load(open(BUDGET_SRC, encoding='utf-8'))
       if BUDGET_SRC and os.path.exists(BUDGET_SRC) else None)
if BUD and not BUD.get('days'):
    BUD = None


# ───────────────────────── 지도 생성 ─────────────────────────
def build_map(mid, points, cap, color, trigger_pad=13, fit_pad=46):
    """points: [[이름, lat, lon], ...] -> (svg, mapseq_html)

    지점이 캔버스를 벗어날 때만 균일 축소/이동으로 자동 재배치합니다.
    (마커 반지름이 10이라 13px 안쪽으로 들어오면 잘려 보입니다)
    """
    P = PROJ[mid]
    W, H = P['W'], P['H']
    bm = open('src/basemaps/' + P['basemap'], encoding='utf-8').read()

    # 1) 기본 투영
    raw = [(P['a'] * lo + P['b'], P['c'] * la + P['d']) for _, la, lo in points]

    # 2) 캔버스를 벗어날 때만 자동 맞춤
    xs = [q[0] for q in raw]; ys = [q[1] for q in raw]
    need = (min(xs) < trigger_pad or max(xs) > W - trigger_pad or
            min(ys) < trigger_pad or max(ys) > H - trigger_pad)
    s, tx, ty = 1.0, 0.0, 0.0
    if need:
        sx = (W - 2 * fit_pad) / max(max(xs) - min(xs), 1e-6)
        sy = (H - 2 * fit_pad) / max(max(ys) - min(ys), 1e-6)
        s = min(sx, sy, 3.0)
        tx = fit_pad - s * min(xs) + ((W - 2 * fit_pad) - s * (max(xs) - min(xs))) / 2
        ty = fit_pad - s * min(ys) + ((H - 2 * fit_pad) - s * (max(ys) - min(ys))) / 2
    pt = [(s * x + tx, s * y + ty) for x, y in raw]

    # 3) 축척 막대 (보기 좋은 km 단위 자동 선택)
    pxkm = P['pxkm'] * s
    km = next((k for k in NICE_KM if 110 <= k * pxkm <= 280),
              min(NICE_KM, key=lambda k: abs(k * pxkm - 190)))
    bar = km * pxkm
    sy_ = H - 15

    # 4) 중복 지점(같은 곳 재방문) 병합 — 마커는 한 번만, 번호는 묶어서
    nodes = []
    for i, (x, y) in enumerate(pt):
        hit = next((n for n in nodes if math.hypot(n['x'] - x, n['y'] - y) < 14), None)
        if hit:
            hit['idx'].append(i + 1)
        else:
            nodes.append({'x': x, 'y': y, 'idx': [i + 1], 'name': points[i][0]})

    # 5) 라벨 자동 배치 (좌/우 + 충돌 회피)
    # 세로만 보고 밀어내면 안 됩니다 — 지도 반대편에 있어 겹칠 리 없는 라벨끼리도
    # y 가 비슷하다는 이유로 서로를 12px 씩 밀어내고, 그러면 라벨이 제 마커에서
    # 한참 떨어져 어느 지점 이름인지 알 수 없게 됩니다. 가로 범위까지 겹칠 때만 밀어냅니다.
    def lblw(t):
        """라벨 폭 어림 (.maplbl.stop = 10px). 한글·한자는 한 자 10px, 나머지는 5.5px."""
        return sum(10.0 if ord(c) > 0x2E7F else 5.5 for c in t) + 4

    placed = []                       # (x0, x1, y) — 라벨이 실제로 차지하는 상자
    for n in nodes:
        right = n['x'] < W * 0.55
        lx = n['x'] + 13 if right else n['x'] - 13
        w = lblw(n['name'])
        x0, x1 = (lx, lx + w) if right else (lx - w, lx)
        ly = n['y'] + 3.4
        while any(abs(ly - py) < 12 and x0 < px1 and px0 < x1 for px0, px1, py in placed):
            ly += 12
        placed.append((x0, x1, ly))
        n['lx'], n['ly'], n['anchor'] = lx, ly, ('start' if right else 'end')

    esc = lambda t: (t.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))
    parts = ['<svg class="mapsvg" viewBox="0 0 %d %d" preserveAspectRatio="xMidYMid meet" '
             'role="img" aria-label="경로 지도"><rect width="%d" height="%d" class="mapbg"/>' % (W, H, W, H)]
    if need:
        parts.append('<g transform="translate(%.1f,%.1f) scale(%.4f)">%s</g>' % (tx, ty, s, bm))
    else:
        parts.append(bm)
    parts.append('<path class="maproute" d="M' + ' L'.join('%.1f,%.1f' % q for q in pt) +
                 '" fill="none" stroke="%s" stroke-width="1.8" stroke-opacity=".62" '
                 'stroke-dasharray="5 4" stroke-linejoin="round"/>' % color)
    for n in nodes:
        parts.append('<text x="%.1f" y="%.1f" class="maplbl stop" text-anchor="%s">%s</text>'
                     % (n['lx'], n['ly'], n['anchor'], esc(n['name'])))
    for n in nodes:
        lab = '·'.join(str(i) for i in n['idx'])
        parts.append('<circle cx="%.1f" cy="%.1f" r="10.0" fill="#fff" fill-opacity=".95"/>'
                     '<circle cx="%.1f" cy="%.1f" r="8.5" fill="%s"/>'
                     '<text x="%.1f" y="%.1f" class="mapn">%s</text>'
                     % (n['x'], n['y'], n['x'], n['y'], color, n['x'], n['y'] + 3.3, lab))
    parts.append('<line x1="34" y1="%d" x2="%.1f" y2="%d" class="mapscale"/>'
                 '<line x1="34" y1="%d" x2="34" y2="%d" class="mapscale"/>'
                 '<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" class="mapscale"/>'
                 '<text x="%.1f" y="%d" class="mapsm">%d km</text>'
                 '<text x="%d" y="22" class="mapsm" text-anchor="end">N ↑</text></svg>'
                 % (sy_, 34 + bar, sy_, sy_ - 3, sy_ + 3, 34 + bar, sy_ - 3, 34 + bar, sy_ + 3,
                    40 + bar, sy_ + 3.5, km, W - 34))

    seq = ' <span class="mapdot">·</span> '.join(
        '<b>%d</b> %s' % (i + 1, esc(p[0])) for i, p in enumerate(points))
    return ''.join(parts), seq


MAP_Q = doc.get('map_queries') or {}


def gmaps(points):
    """'구글 지도로 열기' 링크.

    경유지를 좌표로 넘기면 구글에서 핀이 전부 무명(42°39'43.9"N …)으로 떠서
    사진·영업시간·리뷰를 볼 수 없습니다. map_queries 에 검색어가 있으면 이름으로
    넘겨 각 지점이 제대로 된 장소 카드로 열리게 합니다.
    """
    def one(p):
        q = MAP_Q.get(p[0])
        return urllib.parse.quote(q) if q else '%.5f,%.5f' % (p[1], p[2])
    if len(points) == 1:
        return 'https://www.google.com/maps/search/?api=1&query=' + one(points[0])
    mid = '%7C'.join(one(p) for p in points[1:-1]) if len(points) > 2 else ''
    u = ('https://www.google.com/maps/dir/?api=1&origin=' + one(points[0]) +
         '&destination=' + one(points[-1]))
    if mid:
        u += '&waypoints=' + mid
    return u + '&travelmode=driving'


# ───────────────────────── 관광지 → 구글 지도 ─────────────────────────
# places: 이름 -> [위도, 경도] 이면 좌표 핀, 문자열이면 검색어.
# 긴 이름부터 걸어야 '아크로폴리스 박물관'이 '아크로폴리스'에 먼저 먹히지 않습니다.
PLACES = sorted((doc.get('places') or {}).items(), key=lambda kv: -len(kv[0]))


def gmap_url(v):
    if isinstance(v, (list, tuple)):
        q = '%.7f,%.7f' % (v[0], v[1])
    else:
        q = urllib.parse.quote(str(v))
    return 'https://www.google.com/maps/search/?api=1&amp;query=' + q


def linkify(text):
    """행 본문의 관광지 이름에 구글 지도 링크를 겁니다 (한 행에 이름당 한 번)."""
    if not text or not PLACES:
        return text
    # 원래 있던 태그는 얼려두고, 링크로 바꾼 조각도 얼려서 중첩을 막습니다
    chunks = [[s, s.startswith('<')] for s in re.split(r'(<[^>]+>)', text) if s]
    for name, val in PLACES:
        out, done = [], False
        for c, frozen in chunks:
            if frozen or done:
                out.append([c, frozen])
                continue
            j = c.find(name)
            if j < 0:
                out.append([c, False])
                continue
            if j:
                out.append([c[:j], False])
            out.append(['<a class="gmap" href="%s" target="_blank" rel="noopener">%s</a>'
                        % (gmap_url(val), name), True])
            if j + len(name) < len(c):
                out.append([c[j + len(name):], False])
            done = True
        chunks = out
    return ''.join(c for c, _ in chunks)


# ───────────────────────── 렌더 ─────────────────────────
def li(r):
    a = ''
    if r.get('bus'):
        a += '<span class="bus">%s</span>' % r['bus']
    a += linkify(r.get('text', ''))
    if r.get('tag'):
        a += ' <span class="tag%s">%s</span>' % (' hot' if r['tag'].get('hot') else '', r['tag']['text'])
    for sm in r.get('small', []):
        a += '<small>%s</small>' % sm
    return '        <li><span class="t">%s</span><span class="a">%s</span></li>' % (r['t'], a)


def render_daymap(mid, day_cls, cap):
    pts = doc['map_points'][mid]
    col = COLOR.get(day_cls, COLOR['ov'])
    svg, seq = build_map(mid, pts, cap, col)
    return ('<div class="daymap" id="%s">%s<p class="mapseq">%s</p>'
            '<p class="mapcap">%s</p><p class="mapctl">'
            '<button type="button" class="maptog" data-m="%s" data-color="%s">실제 지도 불러오기</button>'
            '<a class="maplink" href="%s" target="_blank" rel="noopener">구글 지도로 열기 ↗</a></p></div>'
            % (mid, svg, seq, cap, mid, col, gmaps(pts)))


def section(key, cls=''):
    """문단 제목. labels 에서 빈 문자열로 지우면 그 구획이 사라집니다."""
    if LABELS.get(key):
        B.append('  <p class="section-label%s">%s</p>'
                 % ((' ' + cls) if cls else '', LABELS[key]))


# ───────────────────────── 나라(지역)별 보기 ─────────────────────────
# 라디오 + :checked 로만 전환합니다. 자바스크립트가 없어도, 인쇄해도 전부 보입니다.
LEG = {g['cls']: g['label'] for g in (doc.get('legend') or [])}


def cckey(blk):
    """cls 의 두 번째 낱말이 색 키이자 나라 키입니다."""
    p = blk.get('cls', '').split()
    return p[1] if len(p) > 1 else 'ov'


def day_id(blk):
    """날짜 앵커 id — '9.24' -> 'd-9-24'. 개요에서 눌러 그 날짜로 바로 갑니다."""
    return 'd-' + re.sub(r'[^0-9A-Za-z]+', '-', str(blk.get('date', ''))).strip('-')


REGIONS = []                      # 날짜 블록에 실제로 쓰인 키를 문서 순서대로
for _b in doc['blocks']:
    if _b['type'] == 'day' and cckey(_b) not in REGIONS:
        REGIONS.append(cckey(_b))

# 국경·이동 블록은 '도착하는 쪽'에 붙입니다 — 뒤에 오는 날짜 블록을 따라갑니다
BLK_CC, _nx = {}, REGIONS[-1] if REGIONS else 'ov'
for _b in reversed(doc['blocks']):
    if _b['type'] == 'day':
        _nx = cckey(_b)
    BLK_CC[id(_b)] = _nx


def region_meta(k):
    """(이름, 날짜 범위, 일수, 박수, 도시 목록)"""
    ds = [b for b in doc['blocks'] if b['type'] == 'day' and cckey(b) == k]
    dates = [b.get('date', '') for b in ds if b.get('date')]
    span = dates[0] if len(dates) < 2 else '%s – %s' % (dates[0], dates[-1])
    nn = sum(n['n'] for n in (doc.get('nights') or []) if n['cls'] == k)
    cities = []
    for n in (doc.get('nights') or []):
        if n['cls'] == k and n['name'] not in cities:
            cities.append(n['name'])
    return LEG.get(k, k), span, len(ds), nn, cities


VIEWS = ['home'] + REGIONS + ['all'] + (['cost'] if BUD else [])


def view_css():
    """탭 전환 CSS. 나라 키는 colors/blocks 에서 오므로 하드코딩이 없습니다."""
    if not REGIONS:
        return '  .tabs,.ccards{display:none;}'
    out = ['@media screen{',
           '  .vsw{position:absolute;width:1px;height:1px;opacity:0;pointer-events:none;}',
           '  .stage>.home,.stage>.days,.stage>.cost{display:none;}',
           '  #view-home:checked~.stage>.home,',
           '  #view-cost:checked~.stage>.cost,',
           '  #view-all:checked~.stage>.home,',
           '  #view-all:checked~.stage>.days{display:block;}',
           '  #view-cost:checked~.stage>.notes{display:none;}']
    # .days 의 div 자식(날짜·국경 블록) 순번 — 나라별로 첫/마지막 날의 세로선을 다듬습니다
    idx, first_d, last_d = 0, {}, {}
    for b in doc['blocks']:
        idx += 1
        if b['type'] == 'day':
            k = cckey(b)
            first_d.setdefault(k, idx)
            last_d[k] = idx
    for k in REGIONS:
        out += ['  #view-%s:checked~.stage>.days{display:block;}' % k,
                '  #view-%s:checked~.stage>.days>:not(.%s):not(.keep){display:none;}' % (k, k)]
        if k in first_d:
            out.append('  #view-%s:checked~.stage>.days>div:nth-of-type(%d) .day-rail::before'
                       '{top:30px;}' % (k, first_d[k]))
            out.append('  #view-%s:checked~.stage>.days>div:nth-of-type(%d) .day-rail::before'
                       '{bottom:auto;height:32px;}' % (k, last_d[k]))
            if first_d[k] == last_d[k]:      # 하루짜리 나라는 점 하나만
                out.append('  #view-%s:checked~.stage>.days>div:nth-of-type(%d) .day-rail::before'
                           '{top:30px;height:0;}' % (k, first_d[k]))
    # 개요에서 날짜 줄을 누르면 그 날짜로 이동합니다. 해시가 걸린 동안만 본 일정을
    # 그 나라로 펼치고, 탭을 한 번 누르면 #view-home 이 풀려 이 규칙이 통째로 꺼집니다.
    out.append('  #view-home:checked~.stage:has(>.days>:target)>.home{display:none;}')
    for k in REGIONS:
        out += ['  #view-home:checked~.stage:has(>.days>.%s:target)>.days{display:block;}' % k,
                '  #view-home:checked~.stage:has(>.days>.%s:target)>.days'
                '>:not(.%s):not(.keep){display:none;}' % (k, k)]
    act = ',\n'.join('  #view-%s:checked~.tabs .tab[for="view-%s"]' % (v, v) for v in VIEWS)
    out += [act + '{background:var(--segment);color:var(--segment-foreground);'
                  'box-shadow:var(--surface-shadow);}',
            '}']
    return '\n'.join(out)


# ───────────────────────── 이동 수단 ─────────────────────────
# 아이콘은 단순 도형으로만 그립니다 — 외부 아이콘 폰트·라이브러리를 쓰지 않습니다.
ICONS = {
    'plane': '<path d="M21.5 2.5 2.5 11l8 2.5 2.5 8z"/><path d="M21.5 2.5 10.5 13.5"/>',
    'bus': '<rect x="3" y="4" width="18" height="13" rx="2"/><path d="M3 10h18M12 4v6"/>'
           '<circle cx="7.5" cy="19.4" r="1.6"/><circle cx="16.5" cy="19.4" r="1.6"/>',
    'train': '<rect x="5" y="3" width="14" height="13" rx="3"/><path d="M5 10h14"/>'
             '<circle cx="9" cy="13" r="1"/><circle cx="15" cy="13" r="1"/>'
             '<path d="m8.5 16-2.5 4M15.5 16l2.5 4M3.5 20h17"/>',
}
MOVES = doc.get('move_groups') or []


def icon(name):
    return ('<svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" '
            'aria-hidden="true">%s</svg>' % ICONS.get(name, ''))


def move_rows(g):
    """그룹 하나가 보여줄 줄들 — (날짜, 본문, 금액, 참고인가).

    flights 는 일정.yaml, 나머지는 예산.yaml 의 transport 에서 by 로 골라 옵니다.
    note: true 인 줄은 개수에서 빼고 흐리게 깔아 둡니다.
    """
    if g.get('source') == 'flights':
        return [(f.get('date', ''), f.get('body', ''), '', bool(f.get('note')))
                for f in (doc.get('flights') or [])]
    if not BUD:
        return []
    R, out = BUD['rates'], []
    for t in BUD.get('transport') or []:
        if t.get('by') != g['key']:
            continue
        sub = ' · '.join(x for x in [t.get('mode', ''), t.get('note', '')] if x)
        out.append((t['date'], '<b>%s</b><small>%s</small>' % (t.get('seg', ''), sub),
                    money(round(t['amt'] * R[t['cur']])), False))
    return out


def move_section():
    if not MOVES:
        return []
    data = [(g, move_rows(g)) for g in MOVES]
    data = [(g, r) for g, r in data if r]
    if not data:
        return []
    # <details> 로 만듭니다 — 여닫기를 브라우저가 처리하므로 CSS 규칙 하나가
    # 어긋나도 목록이 새어 나오지 않습니다. name 을 같이 주면 하나만 열립니다.
    n_of = lambda rows: sum(1 for r in rows if not r[3])
    O = ['  <div class="mvbox">']
    for g, rows in data:
        O.append('    <details class="mvitem" name="move">')
        O.append('      <summary class="mvcard">%s<b>%s</b><span class="mvn">%d%s</span>'
                 '<span class="mvchev" aria-hidden="true"></span></summary>'
                 % (icon(g.get('icon', '')), g['label'], n_of(rows), g.get('unit', '')))
        O.append('      <div class="mvlist">')
        for date, body, amt, is_note in rows:
            O.append('        <div class="mvr%s"><span class="mvd">%s</span>'
                     '<span class="mvb">%s</span><span class="mva">%s</span></div>'
                     % (' mvnote' if is_note else '', date, body, amt))
        O.append('      </div>')
        O.append('    </details>')
    O.append('  </div>')
    return O


def move_css():
    """<details> 로 여닫으므로 나라 키에 딸린 CSS 가 필요 없습니다."""
    return '' if MOVES else '  .mvbox{display:none;}'


# ───────────────────────── 예상경비 ─────────────────────────
def money(n):
    return format(int(round(n)), ',')


def build_budget():
    """예산.yaml 을 그대로 계산해 보여줍니다 — 엑셀과 같은 식, 같은 값."""
    R = BUD['rates']
    krw = lambda a, c: round(a * R[c])

    # 날짜 문자열이 일정.yaml('9.19')과 예산.yaml('9/19')에서 다를 수 있습니다
    norm = lambda d: str(d).replace('/', '.').strip()
    date_cc = {norm(b['date']): cckey(b)
               for b in doc['blocks'] if b['type'] == 'day' and b.get('date')}

    tr, en = {}, {}
    for t in BUD.get('transport') or []:
        tr[norm(t['date'])] = tr.get(norm(t['date']), 0) + krw(t['amt'], t['cur'])
    for t in BUD.get('tickets') or []:
        en[norm(t['date'])] = en.get(norm(t['date']), 0) + krw(t['amt'], t['cur'])

    rows, cum, last_cc = [], 0, None
    kind = {'교통': 0, '입장료': 0, '식비': 0, '숙박': 0, '카페': 0}
    per_cc = {}
    for d in BUD.get('days') or []:
        k = norm(d['date'])
        cells = {'교통': tr.get(k, 0), '입장료': en.get(k, 0),
                 '식비': d.get('food', 0), '숙박': d.get('stay', 0), '카페': d.get('cafe', 0)}
        tot = sum(cells.values())
        cum += tot
        for kk, v in cells.items():
            kind[kk] += v
        # 일정에 날짜 블록이 없는 날(귀국일 등)은 직전 나라에 붙입니다 — 합계가 새면 안 됩니다
        cc = date_cc.get(k) or last_cc
        last_cc = cc or last_cc
        if cc:
            per_cc[cc] = per_cc.get(cc, 0) + tot
        rows.append((d, cells, tot, cum, cc))

    local = cum
    air = sum(f['krw'] for f in (BUD.get('flights') or []))
    budget = BUD.get('total_budget') or 0
    left = budget - air - local

    O = ['  <div class="cost">']

    def kpi(lbl, val, sub='', cls=''):
        O.append('    <div class="kpi%s"><span class="kpi-l">%s</span>'
                 '<span class="kpi-v">%s</span><span class="kpi-s">%s</span></div>'
                 % ((' ' + cls) if cls else '', lbl, val, sub))

    O.append('  <div class="kpis">')
    if budget:
        kpi('총예산', money(budget) + '원')
    kpi('항공권', money(air) + '원', '결제 완료')
    kpi('현지 지출', money(local) + '원', '%d일' % len(rows))
    if budget:
        kpi('남는 돈', money(left) + '원',
            '소계 %s원' % money(air + local), 'good' if left >= 0 else 'bad')
    O.append('  </div>')

    def bars(title, items):
        """items: [(표시이름, 금액, 색키, 보조설명)]"""
        items = [i for i in items if i[1]]
        if not items:
            return
        O.append('  <div class="csec">')
        O.append('  <p class="section-label">%s</p>' % title)
        O.append('  <div class="summary">')
        mx = max(i[1] for i in items) or 1
        for name, v, cls, sub in items:
            O.append('    <div class="bar-row"><span class="bar-name">%s%s</span>'
                     '<span class="bar-track"><span class="bar-fill %s" style="width:%d%%"></span></span>'
                     '<span class="bar-num">%s</span></div>'
                     % (name, ('<small>%s</small>' % sub) if sub else '',
                        cls, round(v / mx * 100), money(v)))
        O.append('  </div>')
        O.append('  </div>')

    # 무엇에 쓰나 · 어디에 쓰나 — 넓은 화면에서 나란히 놓입니다
    O.append('  <div class="cpair">')
    bars(LABELS['cost_kind'],
         [(k, v, '', '%d%%' % round(v / local * 100) if local else '') for k, v in kind.items()])
    if per_cc:
        ndays = {}
        for d, _c, _t, _u, cc in rows:
            if cc:
                ndays[cc] = ndays.get(cc, 0) + 1
        bars(LABELS['cost_region'],
             [(LEG.get(k, k), per_cc[k], k,
               '%d일 · 하루 평균 %s원' % (ndays.get(k, 0), money(per_cc[k] / max(ndays.get(k, 1), 1))))
              for k in REGIONS if k in per_cc])
    O.append('  </div>')

    # 통화별로 얼마나 필요한가 — 현지에서 실제로 쥐고 있어야 하는 돈
    cash = {}
    for t in (BUD.get('transport') or []) + (BUD.get('tickets') or []):
        c = t['cur']
        a, w = cash.get(c, (0, 0))
        cash[c] = (a + t['amt'], w + krw(t['amt'], t['cur']))
    if cash:
        O.append('  <p class="section-label">%s</p>' % LABELS['cost_cash'])
        O.append('  <div class="rates">')
        for c, (a, w) in cash.items():
            amt = format(int(a), ',') if float(a).is_integer() else format(a, ',')
            O.append('    <div class="rate"><b>%s %s</b><span>%s원</span></div>'
                     % (amt, c, money(w)))
        O.append('  </div>')
        O.append('  <p class="mapcap">교통·입장료만 더한 값입니다. 식비·숙박은 카드로 낼 수 있는지에 따라 달라져 뺐습니다.</p>')

    # 일자별
    O.append('  <p class="section-label">%s</p>' % LABELS['cost_daily'])
    O.append('  <div class="ctab"><div class="ctr chead">'
             '<span>날짜</span><span>내용</span><span>하루</span><span>누계</span></div>')
    for d, cells, tot, cu, cc in rows:
        det = ' · '.join('%s %s' % (k, money(v)) for k, v in cells.items() if v)
        O.append('    <div class="ctr%s"><span class="cdate">%s<em>%s</em></span>'
                 '<span class="cdesc">%s<small>%s</small></span>'
                 '<span class="cnum">%s</span><span class="cnum cacc">%s</span></div>'
                 % ((' ' + cc) if cc else '', d.get('date', ''), d.get('dow', ''),
                    d.get('desc', ''), det, money(tot), money(cu)))
    O.append('    <div class="ctr cfoot"><span>합계</span><span></span>'
             '<span class="cnum">%s</span><span class="cnum"></span></div>' % money(local))
    O.append('  </div>')

    # 구간별 교통비 · 입장료 — 엑셀을 열지 않아도 되게
    def detail(title, items, name_of, sub_of, total=None):
        if not items:
            return
        O.append('  <p class="section-label">%s</p>' % title)
        O.append('  <div class="ctab">')
        for t in items:
            cc = date_cc.get(norm(t['date']), '')
            w = krw(t['amt'], t['cur'])
            num = ('%s<small>%s %s</small>' % (money(w), format(t['amt'], ','), t['cur'])
                   if w else '<span class="cfree">무료</span>')
            O.append('    <div class="ctr d3%s"><span class="cdate">%s</span>'
                     '<span class="cdesc">%s<small>%s</small></span>'
                     '<span class="cnum">%s</span></div>'
                     % ((' ' + cc) if cc else '', t['date'], name_of(t), sub_of(t), num))
        if total is not None:
            O.append('    <div class="ctr d3 cfoot"><span>합계</span><span></span>'
                     '<span class="cnum">%s</span></div>' % money(total))
        O.append('  </div>')

    detail(LABELS['cost_move'], BUD.get('transport') or [],
           lambda t: t.get('seg', ''),
           lambda t: ' · '.join(x for x in [t.get('mode', ''), t.get('note', '')] if x),
           total=kind['교통'])
    detail(LABELS['cost_tick'], BUD.get('tickets') or [],
           lambda t: t.get('place', ''), lambda t: t.get('note', ''),
           total=kind['입장료'])

    # 환율
    if BUD.get('rates'):
        O.append('  <p class="section-label">%s</p>' % LABELS['cost_rate'])
        O.append('  <div class="rates">')
        for c, v in R.items():
            O.append('    <div class="rate"><b>1 %s</b><span>%s원</span></div>'
                     % (c, format(v, ',')))
        O.append('  </div>')

    notes = (BUD.get('budget_notes') or []) + (BUD.get('transport_notes') or [])
    for n in notes:
        O.append('  <div class="flag">%s</div>' % n)
    O.append('  </div>\n')
    return '\n'.join(O)


# 브라우저 탭 제목: doc_title 이 없으면 title 에서 태그만 벗겨 씁니다
tab = doc.get('doc_title') or re.sub(r'<[^>]+>', '', str(doc.get('title', '여행 일정')))

B = []
B.append(HEAD.replace('__TITLE__', tab)
             .replace('__COLORCSS__', color_css())
             .replace('__VIEWCSS__', view_css())
             .replace('__MOVECSS__', move_css()))
B.append('<div class="wrap">\n')
for key, tpl in (('eyebrow', '  <p class="eyebrow">%s</p>'),
                 ('title', '  <h1 class="title">%s</h1>'),
                 ('subtitle', '  <p class="subtitle">%s</p>'),
                 ('standfirst', '  <p class="standfirst">%s</p>\n')):
    if doc.get(key):
        B.append(tpl % doc[key])

# 보기 전환 스위치 — .tabs·.stage 보다 앞에 있어야 ~ 선택자가 걸립니다
for v in VIEWS:
    B.append('  <input class="vsw" type="radio" name="view" id="view-%s"%s>'
             % (v, ' checked' if v == 'home' else ''))
if REGIONS:
    B.append('  <nav class="tabs">')
    B.append('    <label class="tab" for="view-home">%s</label>' % LABELS['view_home'])
    for k in REGIONS:
        B.append('    <label class="tab" for="view-%s"><i class="swatch %s"></i>%s</label>'
                 % (k, k, LEG.get(k, k)))
    B.append('    <label class="tab" for="view-all">%s</label>' % LABELS['view_all'])
    if BUD:
        B.append('    <label class="tab" for="view-cost">%s</label>' % LABELS['view_cost'])
    B.append('  </nav>\n')
B.append('  <div class="stage">\n  <div class="home">')
# 개요 섹션은 hsec 로 한 칸씩 감쌉니다. 넓은 화면에서는 개요 지도(hs-map)만 오른쪽 칸으로 가고
# 나머지는 왼쪽에 쌓입니다. 왼쪽 개수(--hrows)는 섹션을 다 넣은 뒤에 채웁니다.
# DOM 순서는 그대로라 폰·인쇄에서는 예전과 똑같이 한 줄로 흐릅니다.
_hgrid, _hrows = len(B), 0
B.append('')

nights = doc.get('nights') or []
if nights:
    _hrows += 1
    B.append('  <div class="summary">\n    <div class="sum-head">\n      <h2>%s</h2>' % LABELS['nights'])
    B.append('      <span class="sum-total">%s</span>\n    </div>' % doc.get('nights_total', ''))
    mx = max(n['n'] for n in nights)
    for n in nights:
        B.append('    <div class="bar-row"><span class="bar-name">%s</span><span class="bar-track">'
                 '<span class="bar-fill %s" style="width:%d%%"></span></span>'
                 '<span class="bar-num">%d</span></div>'
                 % (n['name'], n['cls'], round(n['n'] / mx * 100), n['n']))
    if doc.get('legend'):
        B.append('    <div class="legend">')
        for g in doc['legend']:
            B.append('      <span><i class="swatch %s"></i> %s</span>' % (g['cls'], g['label']))
        B.append('    </div>')
    B.append('  </div>\n')

if OVERVIEW_MAP:
    B.append('  <div class="hsec hs-map">')
    section('overview')
    B.append('      ' + render_daymap(OVERVIEW_MAP, 'ov', doc.get('overview_cap', '')))
    B.append('  </div>\n')

_mv = move_section()
if _mv:
    _hrows += 1
    B.append('  <div class="hsec">')
    section('moves')
    B += _mv
    B.append('  </div>\n')
elif doc.get('flights'):
    _hrows += 1
    B.append('  <div class="hsec">')
    section('flights')
    for f in doc['flights']:
        B.append('  <div class="flight">\n    <div class="flight-date">%s</div>'
                 '\n    <div class="flight-body">%s</div>\n  </div>' % (f['date'], f['body']))
    B.append('  </div>\n')

# 나라 카드 — 눌러서 그 나라만 보기
if REGIONS:
    _hrows += 1
    B.append('  <div class="hsec">')
    section('regions')
    B.append('  <div class="ccards">')
    for k in REGIONS:
        name, span, nd, nn, cities = region_meta(k)
        B.append('    <label class="ccard %s" for="view-%s">'
                 '<span class="cc-name">%s</span>'
                 '<span class="cc-span">%s</span>'
                 '<span class="cc-num">%d일%s</span>'
                 '<span class="cc-city">%s</span></label>'
                 % (k, k, name, span, nd, (' · %d박' % nn) if nn else '', ' · '.join(cities)))
    B.append('  </div>')
    B.append('  </div>\n')

# 하루씩 훑어보기 — 16일을 한 화면에. 누르면 그 나라로 들어갑니다
_days = [b for b in doc['blocks'] if b['type'] == 'day']
if _days:
    _hrows += 1
    B.append('  <div class="hsec">')
    section('outline')
    B.append('  <div class="tline">')
    for b in _days:
        B.append('    <a class="tl %s" href="#%s"><span class="tl-d">%s<em>%s</em></span>'
                 '<span class="tl-p">%s</span></a>'
                 % (cckey(b), day_id(b), b.get('date', ''), b.get('dow', ''),
                    re.sub(r'<[^>]+>', '', b.get('place', '')).strip()))
    B.append('  </div>')
    B.append('  </div>')
B[_hgrid] = '  <div class="hgrid" style="--hrows:%d">' % max(_hrows, 1)
B.append('  </div>\n  </div>\n\n  <div class="days">')
section('days', 'keep')
B.append('')

seen_cc = set()
for blk in doc['blocks']:
    cc = BLK_CC[id(blk)]
    if cc not in seen_cc and cc in REGIONS:      # 나라가 바뀌는 자리에 머리글
        seen_cc.add(cc)
        name, span, nd, nn, cities = region_meta(cc)
        B.append('  <p class="rgn-head %s"><i class="swatch %s"></i><b>%s</b>'
                 '<span>%s · %d일%s</span></p>'
                 % (cc, cc, name, span, nd, (' · %d박' % nn) if nn else ''))
    if blk['type'] == 'border':
        B.append('  <div class="border %s">\n    <div class="day-date"></div><div class="border-rail"></div>'
                 '\n    <div class="border-body">\n      <p class="border-title">%s</p>'
                 '\n      <p class="border-note">%s</p>\n    </div>\n  </div>\n'
                 % (cc, blk['title'], blk['note']))
        continue
    if cc not in COLOR:
        sys.exit("%s: cls '%s' 의 색 키 '%s' 가 colors 에 없습니다."
                 % (blk.get('date', '?'), blk['cls'], cc))
    B.append('  <div class="%s" id="%s">' % (blk['cls'], day_id(blk)))
    B.append('    <div class="day-date">%s<em>%s</em></div><div class="day-rail"><i class="node"></i></div>'
             % (blk.get('date', ''), blk.get('dow', '')))
    # 글(dtext) · 지도(daymap) · 주의(dflags) 세 덩어리 — 넓은 화면에서 글 | 지도 두 칸이 됩니다
    B.append('    <div class="day-body">')
    B.append('      <div class="dtext">')
    B.append('      <h3 class="day-place">%s</h3>' % blk.get('place', ''))
    if blk.get('sub'):
        B.append('      <p class="day-sub">%s</p>' % blk['sub'])
    for seg in blk.get('sched', []):
        if seg.get('label'):
            B.append('      <p class="opt-label">%s</p>' % seg['label'])
        B.append('      <ul class="sched">')
        B += [li(r) for r in seg['rows']]
        B.append('      </ul>')
    B.append('      </div>')
    if blk.get('map'):
        B.append('      ' + render_daymap(blk['map']['id'], cc, blk['map']['cap']))
    if blk.get('flags'):
        B.append('      <div class="dflags">')
        for f in blk['flags']:
            B.append('      <div class="flag">%s</div>' % f)
        B.append('      </div>')
    B.append('    </div>\n  </div>\n')

B.append('  </div>\n')                                   # .days 닫기

if BUD:
    B.append(build_budget())

if doc.get('notes') or doc.get('foot'):
    B.append('  <div class="notes">')
    if doc.get('notes'):
        if LABELS.get('notes'):
            B.append('    <h2>%s</h2>' % LABELS['notes'])
        for n in doc['notes']:
            B.append('    <div class="note">\n      <div class="note-key">%s</div>'
                     '\n      <div class="note-val">%s</div>\n    </div>' % (n['key'], n['val']))
    if doc.get('foot'):
        B.append('    <p class="foot">%s</p>' % doc['foot'])
    B.append('  </div>\n')
B.append('  </div>\n')                                   # .stage 닫기
B.append('</div>\n')
B.append(SCRIPT.replace('__MAPPOINTS__', json.dumps(doc.get('map_points') or {}, ensure_ascii=False)))
B.append('\n</body>\n</html>\n')

html = '\n'.join(B)
open(OUT, 'w', encoding='utf-8').write(html)
print('생성 완료: %s  (%s bytes)' % (OUT, format(len(html.encode('utf-8')), ',')))
IDX = outpath.index_copy(doc)                             # GitHub Pages 첫 화면
if IDX:
    open(IDX, 'w', encoding='utf-8').write(html)
    print('  같은 내용을 %s 에도 썼습니다' % IDX)
print('  일 %d · 국경 %d · 지도 %d · 노트 %d'
      % (sum(1 for b in doc['blocks'] if b['type'] == 'day'),
         sum(1 for b in doc['blocks'] if b['type'] == 'border'),
         len(doc['map_points']), len(doc['notes'])))
