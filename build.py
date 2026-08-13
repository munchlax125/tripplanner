# -*- coding: utf-8 -*-
"""
src/일정.yaml  ->  <output>.html   (파일명은 일정.yaml 의 output 키)

지도는 지점 위경도만 있으면 투영·축척·마커·라벨·경로선을 자동으로 그립니다.
mapseq 텍스트와 Leaflet 데이터도 같은 소스에서 나오므로 어긋날 수 없습니다.

    python build.py
"""
import io, sys, os, json, math, re, urllib.parse
import yaml

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)

NICE_KM = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000]

doc = yaml.safe_load(open('src/일정.yaml', encoding='utf-8'))

# 여행에 관한 값은 전부 일정.yaml 에서 옵니다. 코드에는 여행별 상수가 없습니다.
OUT = doc.get('output')
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
    """나라·지역 키마다 필요한 CSS를 만들어 head.html 의 __COLORCSS__ 자리에 넣습니다."""
    def rules(k, col, alpha):
        r, g, b = _rgb(col)
        return ['.bar-fill.%s,.swatch.%s,.day.%s .day-rail::before,.day.%s.stay .node{background:%s;}'
                % (k, k, k, k, col),
                '.ccard.%s{border-left-color:%s;}' % (k, col),
                '.day.%s .node{border-color:%s;}' % (k, col),
                '.day.%s .bus{color:%s;background:rgba(%d,%d,%d,%s);}' % (k, col, r, g, b, alpha)]
    lt, dk = [], []
    for k, v in RAW_COLORS.items():
        if k == 'ov':
            continue
        lt += rules(k, light_of(v), '.10')
        dk += rules(k, dark_of(v), '.14')
    return ('  ' + '\n  '.join(lt) +
            '\n  @media (prefers-color-scheme:dark){\n    ' + '\n    '.join(dk) + '\n  }')
OVERVIEW_MAP = doc.get('overview_map')               # 없으면 개요 지도를 넣지 않습니다

# 문단 제목. labels 로 덮어쓰거나 빈 문자열을 주면 그 구획이 사라집니다.
LABELS = {'nights': '숙박 배분', 'overview': '루트 개요', 'flights': '항공편',
          'days': '본 일정', 'notes': '미리 확인할 것', 'regions': '나라별로 보기',
          'view_home': '개요', 'view_all': '전체 일정'}
LABELS.update(doc.get('labels') or {})
PROJ = json.load(open('src/basemaps/_proj.json', encoding='utf-8'))
HEAD = open('src/head.html', encoding='utf-8').read()
SCRIPT = open('src/script.html', encoding='utf-8').read()


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

    # 5) 라벨 자동 배치 (좌/우 + 세로 충돌 회피)
    placed = []
    for n in nodes:
        right = n['x'] < W * 0.55
        lx = n['x'] + 13 if right else n['x'] - 13
        ly = n['y'] + 3.4
        while any(abs(ly - p) < 12 for p in placed):
            ly += 12
        placed.append(ly)
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


def view_css():
    """탭 전환 CSS. 나라 키는 colors/blocks 에서 오므로 하드코딩이 없습니다."""
    if not REGIONS:
        return '  .tabs,.ccards{display:none;}'
    out = ['@media screen{',
           '  .vsw{position:absolute;width:1px;height:1px;opacity:0;pointer-events:none;}',
           '  .stage>.home,.stage>.days{display:none;}',
           '  #view-home:checked~.stage>.home,',
           '  #view-all:checked~.stage>.home,',
           '  #view-all:checked~.stage>.days{display:block;}']
    for k in REGIONS:
        out += ['  #view-%s:checked~.stage>.days{display:block;}' % k,
                '  #view-%s:checked~.stage>.days>:not(.%s):not(.keep){display:none;}' % (k, k)]
    act = ',\n'.join('  #view-%s:checked~.tabs .tab[for="view-%s"]' % (v, v)
                     for v in ['home'] + REGIONS + ['all'])
    out += [act + '{background:hsl(var(--background));color:hsl(var(--foreground));'
                  'box-shadow:var(--shadow-sm);}',
            '}']
    return '\n'.join(out)


# 브라우저 탭 제목: doc_title 이 없으면 title 에서 태그만 벗겨 씁니다
tab = doc.get('doc_title') or re.sub(r'<[^>]+>', '', str(doc.get('title', '여행 일정')))

B = []
B.append(HEAD.replace('__TITLE__', tab)
             .replace('__COLORCSS__', color_css())
             .replace('__VIEWCSS__', view_css()))
B.append('<div class="wrap">\n')
for key, tpl in (('eyebrow', '  <p class="eyebrow">%s</p>'),
                 ('title', '  <h1 class="title">%s</h1>'),
                 ('subtitle', '  <p class="subtitle">%s</p>'),
                 ('standfirst', '  <p class="standfirst">%s</p>\n')):
    if doc.get(key):
        B.append(tpl % doc[key])

# 보기 전환 스위치 — .tabs·.stage 보다 앞에 있어야 ~ 선택자가 걸립니다
for v in ['home'] + REGIONS + ['all']:
    B.append('  <input class="vsw" type="radio" name="view" id="view-%s"%s>'
             % (v, ' checked' if v == 'home' else ''))
if REGIONS:
    B.append('  <nav class="tabs">')
    B.append('    <label class="tab" for="view-home">%s</label>' % LABELS['view_home'])
    for k in REGIONS:
        B.append('    <label class="tab" for="view-%s"><i class="swatch %s"></i>%s</label>'
                 % (k, k, LEG.get(k, k)))
    B.append('    <label class="tab" for="view-all">%s</label>' % LABELS['view_all'])
    B.append('  </nav>\n')
B.append('  <div class="stage">\n  <div class="home">')

nights = doc.get('nights') or []
if nights:
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
    section('overview')
    B.append('      ' + render_daymap(OVERVIEW_MAP, 'ov', doc.get('overview_cap', '')) + '\n')

if doc.get('flights'):
    section('flights')
    for f in doc['flights']:
        B.append('  <div class="flight">\n    <div class="flight-date">%s</div>'
                 '\n    <div class="flight-body">%s</div>\n  </div>' % (f['date'], f['body']))
    B.append('')

# 나라 카드 — 눌러서 그 나라만 보기
if REGIONS:
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
B.append('  </div>\n\n  <div class="days">')
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
    B.append('  <div class="%s">' % blk['cls'])
    B.append('    <div class="day-date">%s<em>%s</em></div><div class="day-rail"><i class="node"></i></div>'
             % (blk.get('date', ''), blk.get('dow', '')))
    B.append('    <div class="day-body">')
    B.append('      <h3 class="day-place">%s</h3>' % blk.get('place', ''))
    if blk.get('sub'):
        B.append('      <p class="day-sub">%s</p>' % blk['sub'])
    for seg in blk.get('sched', []):
        if seg.get('label'):
            B.append('      <p class="opt-label">%s</p>' % seg['label'])
        B.append('      <ul class="sched">')
        B += [li(r) for r in seg['rows']]
        B.append('      </ul>')
    if blk.get('map'):
        B.append('      ' + render_daymap(blk['map']['id'], cc, blk['map']['cap']))
    for f in blk.get('flags', []):
        B.append('      <div class="flag">%s</div>' % f)
    B.append('    </div>\n  </div>\n')

B.append('  </div>\n')                                   # .days 닫기

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
print('  일 %d · 국경 %d · 지도 %d · 노트 %d'
      % (sum(1 for b in doc['blocks'] if b['type'] == 'day'),
         sum(1 for b in doc['blocks'] if b['type'] == 'border'),
         len(doc['map_points']), len(doc['notes'])))
