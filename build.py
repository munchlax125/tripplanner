# -*- coding: utf-8 -*-
"""
src/일정.yaml  ->  조지아_아르메니아_최종일정_상하이반영.html

지도는 지점 위경도만 있으면 투영·축척·마커·라벨·경로선을 자동으로 그립니다.
mapseq 텍스트와 Leaflet 데이터도 같은 소스에서 나오므로 어긋날 수 없습니다.

    python build.py
"""
import io, sys, os, json, math
import yaml

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)

OUT = '조지아_아르메니아_최종일정_상하이반영.html'
COLOR = {'ge': '#42606E', 'am': '#C87518', 'gr': '#1F6FA5',
         'ae': '#A97142', 'cn': '#9E3B34', 'ov': '#42606E'}
NICE_KM = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000]

doc = yaml.safe_load(open('src/일정.yaml', encoding='utf-8'))
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
    parts.append('<path d="M' + ' L'.join('%.1f,%.1f' % q for q in pt) +
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


def gmaps(points):
    def one(p):
        return '%.5f,%.5f' % (p[1], p[2])
    if len(points) == 1:
        return 'https://www.google.com/maps/search/?api=1&query=' + one(points[0])
    mid = '%7C'.join(one(p) for p in points[1:-1]) if len(points) > 2 else ''
    u = ('https://www.google.com/maps/dir/?api=1&origin=' + one(points[0]) +
         '&destination=' + one(points[-1]))
    if mid:
        u += '&waypoints=' + mid
    return u + '&travelmode=driving'


# ───────────────────────── 렌더 ─────────────────────────
def li(r):
    a = ''
    if r.get('bus'):
        a += '<span class="bus">%s</span>' % r['bus']
    a += r.get('text', '')
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
            '<button type="button" class="maptog" data-m="%s">실제 지도 불러오기</button>'
            '<a class="maplink" href="%s" target="_blank" rel="noopener">구글 지도로 열기 ↗</a></p></div>'
            % (mid, svg, seq, cap, mid, gmaps(pts)))


B = []
B.append(HEAD)
B.append('<div class="wrap">\n')
B.append('  <p class="eyebrow">%s</p>' % doc['eyebrow'])
B.append('  <h1 class="title">%s</h1>' % doc['title'])
B.append('  <p class="subtitle">%s</p>' % doc['subtitle'])
B.append('  <p class="standfirst">%s</p>\n' % doc['standfirst'])

B.append('  <div class="summary">\n    <div class="sum-head">\n      <h2>숙박 배분</h2>')
B.append('      <span class="sum-total">%s</span>\n    </div>' % doc['nights_total'])
mx = max(n['n'] for n in doc['nights'])
for n in doc['nights']:
    B.append('    <div class="bar-row"><span class="bar-name">%s</span><span class="bar-track">'
             '<span class="bar-fill %s" style="width:%d%%"></span></span>'
             '<span class="bar-num">%d</span></div>'
             % (n['name'], n['cls'], round(n['n'] / mx * 100), n['n']))
B.append('    <div class="legend">')
for g in doc['legend']:
    B.append('      <span><i class="swatch %s"></i> %s</span>' % (g['cls'], g['label']))
B.append('    </div>\n  </div>\n')

B.append('  <p class="section-label">지상 루트 개요</p>')
ov = next(b for b in doc['blocks'] if b.get('type') == 'overview') if any(
    b.get('type') == 'overview' for b in doc['blocks']) else None
B.append('      ' + render_daymap('m00', 'ov', doc.get('overview_cap', '')) + '\n')

B.append('  <p class="section-label">가는 편</p>')
for f in doc['flights']:
    B.append('  <div class="flight">\n    <div class="flight-date">%s</div>'
             '\n    <div class="flight-body">%s</div>\n  </div>' % (f['date'], f['body']))
B.append('\n  <p class="section-label">본 일정</p>\n')

for blk in doc['blocks']:
    if blk['type'] == 'border':
        B.append('  <div class="border">\n    <div class="day-date"></div><div class="border-rail"></div>'
                 '\n    <div class="border-body">\n      <p class="border-title">%s</p>'
                 '\n      <p class="border-note">%s</p>\n    </div>\n  </div>\n'
                 % (blk['title'], blk['note']))
        continue
    cc = blk['cls'].split()[1]
    B.append('  <div class="%s">' % blk['cls'])
    B.append('    <div class="day-date">%s<em>%s</em></div><div class="day-rail"><i class="node"></i></div>'
             % (blk['date'], blk['dow']))
    B.append('    <div class="day-body">')
    B.append('      <h3 class="day-place">%s</h3>' % blk['place'])
    B.append('      <p class="day-sub">%s</p>' % blk['sub'])
    for seg in blk['sched']:
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

B.append('  <div class="notes">\n    <h2>미리 확인할 것</h2>')
for n in doc['notes']:
    B.append('    <div class="note">\n      <div class="note-key">%s</div>'
             '\n      <div class="note-val">%s</div>\n    </div>' % (n['key'], n['val']))
B.append('    <p class="foot">%s</p>\n  </div>\n' % doc['foot'])
B.append('</div>\n')
B.append(SCRIPT.replace('__MAPPOINTS__', json.dumps(doc['map_points'], ensure_ascii=False)))
B.append('\n</body>\n</html>\n')

html = '\n'.join(B)
open(OUT, 'w', encoding='utf-8').write(html)
print('생성 완료: %s  (%s bytes)' % (OUT, format(len(html.encode('utf-8')), ',')))
print('  일 %d · 국경 %d · 지도 %d · 노트 %d'
      % (sum(1 for b in doc['blocks'] if b['type'] == 'day'),
         sum(1 for b in doc['blocks'] if b['type'] == 'border'),
         len(doc['map_points']), len(doc['notes'])))
