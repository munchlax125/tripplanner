# -*- coding: utf-8 -*-
"""새 여행을 물어보고 src/일정.yaml · src/예산.yaml 을 만듭니다.

    python new_trip.py                  # 물어보면서 만들기
    python new_trip.py --from 답.yaml   # 미리 적어둔 답으로 (테스트·재현용)
    python new_trip.py --force          # 이미 있는 src/ YAML 을 덮어쓰기

날짜·요일·숙박 도시는 답에서 자동으로 펼칩니다. 하루씩 빈 일정 블록이 만들어지므로
끝나자마자 `python build.py` 가 그대로 돕니다. 내용은 그 뒤에 채우면 됩니다.

여행별 상수는 이 파일에도 없습니다 — 전부 사용자가 답한 값에서 나옵니다.
"""
import argparse, datetime as dt, io, os, sys
import yaml

import outpath

# 콘솔·파이프·NUL 어디로 나가든 UTF-8 로 씁니다.
# isatty() 로 갈라선 안 됩니다 — Windows 의 NUL 은 문자 장치라 isatty() 가 True 이고,
# 그러면 cp949 스트림이 그대로 남아 '—' 같은 글자에서 터집니다.
for _s in ('stdout', 'stderr'):
    try:
        getattr(sys, _s).reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, ValueError):
        setattr(sys, _s, io.TextIOWrapper(getattr(sys, _s).buffer,
                                          encoding='utf-8', errors='replace'))
# 답을 파이프로 밀어 넣을 때만 stdin 도 UTF-8 로 봅니다. 콘솔은 건드리지 않습니다.
if not sys.stdin.isatty():
    try:
        sys.stdin.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, ValueError):
        pass
os.chdir(os.path.dirname(os.path.abspath(__file__)))

ITIN, BUDGET = 'src/일정.yaml', 'src/예산.yaml'
DOW = '월화수목금토일'
TPL_RATE_ROW0 = 4                    # 예산_템플릿.xlsx 환율 시트의 첫 통화 행

# 지역 색 기본값. 여행별 상수가 아니라 그냥 순서대로 꺼내 쓰는 팔레트입니다.
PALETTE = [('#42606E', '#8FB4C4'), ('#C87518', '#E5A153'), ('#1F6FA5', '#7EC1E8'),
           ('#A97142', '#D9A66C'), ('#9E3B34', '#DE8B82'), ('#4A7C59', '#8FBF9F')]

A = {}                               # --from 으로 미리 받은 답
BATCH = False


def die(msg):
    sys.exit('\n[중단] %s' % msg)


def ask(key, prompt, default=None, cast=str):
    """A 에 답이 있으면 그걸 쓰고, 없으면 물어봅니다."""
    if key in A and A[key] is not None:
        return cast(A[key]) if cast is not str else A[key]
    if BATCH:
        if default is None:
            die("답 파일에 '%s' 가 없습니다." % key)
        return default
    tail = ' [%s]' % default if default not in (None, '') else ''
    while True:
        v = input('%s%s: ' % (prompt, tail)).strip()
        if not v and default is not None:
            return default
        if not v:
            print('  값이 필요합니다.')
            continue
        try:
            return cast(v)
        except ValueError:
            print('  형식이 올바르지 않습니다.')


def ask_rows(key, title, fields, minimum=1):
    """같은 모양의 항목을 여러 개 받습니다. 빈 줄을 넣으면 끝납니다."""
    if key in A and A[key]:
        return list(A[key])
    if BATCH:
        die("답 파일에 '%s' 가 없습니다." % key)
    print('\n· %s — 다 넣었으면 빈 줄에서 엔터' % title)
    out = []
    while True:
        row, blank = {}, False
        for i, (fk, fp, cast, dflt) in enumerate(fields):
            v = input('   %s: ' % fp).strip()
            if i == 0 and not v:
                blank = True
                break
            if not v and dflt is not None:
                v = dflt
            try:
                row[fk] = cast(v) if v != '' else ''
            except ValueError:
                print('   형식이 올바르지 않습니다. 이 항목을 다시 넣어주세요.')
                row = None
                break
        if blank:
            if len(out) >= minimum:
                return out
            print('   최소 %d개는 필요합니다.' % minimum)
            continue
        if row is not None:
            out.append(row)
            print('   → %d개째' % len(out))


def date_of(s):
    s = str(s).strip().replace('.', '-').replace('/', '-')
    for f in ('%Y-%m-%d', '%y-%m-%d', '%m-%d'):
        try:
            d = dt.datetime.strptime(s, f).date()
            return d.replace(year=dt.date.today().year) if f == '%m-%d' else d
        except ValueError:
            pass
    raise ValueError(s)


def main():
    global A, BATCH
    ap = argparse.ArgumentParser(description='새 여행 YAML 만들기')
    ap.add_argument('--from', dest='src', help='미리 적어둔 답 YAML')
    ap.add_argument('--force', action='store_true', help='기존 src/ YAML 덮어쓰기')
    args = ap.parse_args()

    if args.src:
        A = yaml.safe_load(open(args.src, encoding='utf-8')) or {}
        BATCH = True

    exists = [p for p in (ITIN, BUDGET) if os.path.exists(p)]
    if exists and not args.force:
        die('%s 가 이미 있습니다. 덮어쓰려면 --force 를 붙이세요.' % ' · '.join(exists))

    if not BATCH:
        print('\n새 여행을 만듭니다. 대괄호 안은 기본값이라 엔터만 눌러도 됩니다.\n')

    # ── 1. 여행 ──────────────────────────────────────────────────────
    title = ask('title', '여행 제목 (예: 도쿄·하코네)')
    subtitle = ask('subtitle', '한 줄 부제', '')
    eyebrow = ask('eyebrow', '제목 위 작은 글씨', '')
    standfirst = ask('standfirst', '머리말 한 문단 (나중에 채워도 됩니다)', '')
    people = ask('people', '인원', 1, int)

    # ── 2. 날짜 ──────────────────────────────────────────────────────
    start = ask('start', '출발일 (YYYY-MM-DD)', cast=date_of)
    end = ask('end', '귀국일 (YYYY-MM-DD)', cast=date_of)
    if end < start:
        die('귀국일이 출발일보다 빠릅니다.')
    dates = [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]
    n_nights = len(dates) - 1
    print('\n  → %d일 %d박 (%s ~ %s)' % (len(dates), n_nights, start, end))

    # ── 3. 지역 ──────────────────────────────────────────────────────
    regions = ask_rows('regions', '지역·나라 (일정을 색으로 나눌 단위)', [
        ('label', '지역 이름 (예: 일본)', str, None),
        ('key', '색 키 — 영문 소문자 (예: jp)', str, ''),
        ('color', '색 #RRGGBB (엔터=자동)', str, ''),
    ])
    for i, r in enumerate(regions):
        r['key'] = (r.get('key') or 'r%d' % (i + 1)).strip()
        if not r.get('color'):
            lo, hi = PALETTE[i % len(PALETTE)]
            r['color'] = {'light': lo, 'dark': hi}
    rkeys = [r['key'] for r in regions]

    # ── 4. 숙박 (날짜·지역·장소가 전부 여기서 나옵니다) ─────────────
    print('\n  묵는 순서대로 넣으세요. 박수 합이 %d박이어야 합니다.' % n_nights)
    while True:
        nights = ask_rows('nights', '숙박', [
            ('name', '도시·마을 이름', str, None),
            ('region', '지역 색 키 (%s)' % '/'.join(rkeys), str, rkeys[0]),
            ('n', '몇 박', int, None),
        ])
        bad = [x['region'] for x in nights if x['region'] not in rkeys]
        if bad:
            msg = '지역 키 %s 는 위에서 만든 지역(%s)에 없습니다.' % (bad, rkeys)
            die(msg) if BATCH else print('  ' + msg)
            continue
        total = sum(int(x['n']) for x in nights)
        if total == n_nights:
            break
        msg = '박수 합이 %d박인데 여행은 %d박입니다.' % (total, n_nights)
        die(msg) if BATCH else print('  ' + msg + ' 다시 넣어주세요.')

    # 날짜마다 그날 묵는 곳을 펼칩니다. 마지막 날은 숙박이 없어 직전 도시를 씁니다.
    stay_of = []
    for x in nights:
        stay_of += [x] * int(x['n'])
    stay_of.append(stay_of[-1])

    # ── 5. 항공권 ────────────────────────────────────────────────────
    flights = ask_rows('flights', '항공권 (결제 단위로 한 줄씩)', [
        ('body', '구간 (예: 인천 09:00 → 나리타 11:30)', str, None),
        ('date', '날짜 (예: 4.3 금)', str, ''),
        ('krw', '원화 금액', int, '0'),
    ])

    # ── 6. 돈 ────────────────────────────────────────────────────────
    print('\n  현지 통화는 몇 개든 됩니다. 환율 시트 행은 빌드가 알아서 맞춥니다.')
    currencies = ask_rows('currencies', '통화', [
        ('code', '통화 코드 (예: JPY)', str, None),
        ('rate', '1단위가 몇 원인지', float, None),
        ('label', '표시 이름 (엔터=자동)', str, ''),
        ('note', '비고 (환율 기준일 등)', str, ''),
    ])
    total_budget = ask('total_budget', '총예산 (원)', 0, int)
    food = ask('food', '하루 식비 기본값 (원)', 0, int)
    stay_cost = ask('stay', '1박 숙박비 기본값 (원)', 0, int)
    cafe = ask('cafe', '하루 카페·간식 기본값 (원)', 0, int)

    out_html = ask('output_html', 'HTML 파일 이름', '내여행.html')
    out_xlsx = ask('output_xlsx', '엑셀 파일 이름', '내여행_예산.xlsx')

    # ── 일정 YAML ────────────────────────────────────────────────────
    blocks = []
    for i, d in enumerate(dates):
        s = stay_of[i]
        last = (i == len(dates) - 1)
        blocks.append({
            'type': 'day',
            'cls': 'day %s%s' % (s['region'], '' if last else ' stay'),
            'date': '%d.%d' % (d.month, d.day),
            'dow': DOW[d.weekday()],
            'place': s['name'],
            'sub': '',
            'sched': [{'label': None,
                       'rows': [{'t': '', 'text': '여기에 이 날의 일정을 적으세요'}]}],
        })

    itin = {
        'output': out_html,
        'index_copy': 'index.html',       # GitHub Pages 첫 화면 — 빌드가 같은 HTML 을 여기에도 씁니다
        'doc_title': title,
        'budget_source': BUDGET,
        'colors': {r['key']: r['color'] for r in regions},
        'labels': {'nights': '숙박 배분', 'overview': '루트 개요', 'flights': '이동 수단',
                   'days': '본 일정', 'notes': '미리 확인할 것'},
        'eyebrow': eyebrow,
        'title': title.replace('·', '<span class="sep">·</span>'),
        'subtitle': subtitle,
        'standfirst': standfirst,
        'nights_total': '%s = %d박' % (
            ' + '.join('%s %d박' % (x['name'], int(x['n'])) for x in nights), n_nights),
        'nights': [{'name': x['name'], 'cls': x['region'],
                    'w': int(x['n']) * 20, 'n': int(x['n'])} for x in nights],
        'legend': [{'cls': r['key'], 'label': r['label']} for r in regions],
        'flights': [{'date': f.get('date', ''), 'body': '<b>%s</b>' % f['body']}
                    for f in flights],
        'move_groups': [
            {'key': 'air', 'label': '항공편', 'icon': 'plane', 'source': 'flights', 'unit': '편'},
            {'key': 'bus', 'label': '버스', 'icon': 'bus', 'source': 'transport', 'unit': '구간'},
            {'key': 'rail', 'label': '기차', 'icon': 'train', 'source': 'transport', 'unit': '구간'},
        ],
        'blocks': blocks,
        'notes': [{'key': '미리 확인할 것',
                   'val': '휴관일 · 막차 시각 · 예약이 필요한 곳을 여기에 적으세요.'}],
        'foot': '%d인 여행' % people,
        'map_points': {},
        'places': {},
        'map_queries': {},
    }

    # ── 예산 YAML ────────────────────────────────────────────────────
    cur0 = currencies[0]['code']
    days = []
    for i, d in enumerate(dates):
        last = (i == len(dates) - 1)
        days.append({'date': '%d/%d' % (d.month, d.day), 'dow': DOW[d.weekday()],
                     'desc': stay_of[i]['name'], 'food': food,
                     'stay': 0 if last else stay_cost, 'cafe': cafe})
    d0 = days[0]['date']

    budget = {
        'output': out_xlsx,
        'itinerary_source': ITIN,
        'rate_rows': {c['code']: TPL_RATE_ROW0 + i for i, c in enumerate(currencies)},
        'sheet_titles': {'환율': '환율 및 기본 가정', '교통상세': '구간별 교통',
                         '입장료': '입장료', '일자별예산': '일자별 예산 (1인 기준, 원)',
                         '일정': '일정 — 날짜별 코스'},
        'sheet_intros': {
            '교통상세': "'대중교통' 열이 ○ 이면 대중교통으로 갈 수 있는 구간, △ 는 부분적, "
                        "✕ 는 택시가 사실상 필수인 구간입니다.",
            '일자별예산': '%d인 기준입니다.' % people,
            '일정': '일정 YAML 에서 그대로 생성한 시트입니다. 4행에 필터가 걸려 있습니다.'},
        'rate_labels': {c['code']: (c.get('label') or '%s → 원' % c['code'])
                        for c in currencies},
        'rate_notes': {c['code']: c.get('note', '') for c in currencies},
        # 템플릿에 박힌 문구가 아니라 여기 값이 환율 시트에 찍힙니다.
        'rate_sheet': {
            '인원': {'label': '인원', 'note': '%d인 기준' % people},
            '항공권합계': {'label': '항공권 합계', 'note': ''},
            '총예산': {'label': '총예산 (%d인)' % people, 'note': ''},
            'foot': ['노란 셀만 수정하세요. 나머지 시트는 이 값을 참조해 자동 계산됩니다.',
                     '환율은 현지 지출에만 적용됩니다. 출발 직전에 한 번 더 갱신하세요.'],
        },
        'rates': {c['code']: float(c['rate']) for c in currencies},
        'people': people,
        'total_budget': total_budget,
        'flights': [{'name': f['body'], 'krw': int(f.get('krw') or 0)} for f in flights],
        'transport': [{'date': d0, 'seg': '공항 → 시내', 'mode': '(교통수단)', 'by': 'bus',
                       'kind': '시내', 'amt': 0, 'cur': cur0, 'pub': '○',
                       'note': '예시 행입니다. 구간을 실제 값으로 채우세요'}],
        'transport_notes': [],
        'tickets': [{'date': d0, 'place': '(입장료가 있는 곳)', 'amt': 0, 'cur': cur0,
                     'note': '예시 행입니다'}],
        'ticket_note': '',
        'days': days,
        'budget_notes': ['※ 여행자보험·유심·기념품은 별도로 잡으세요.'],
    }

    for path, data in ((ITIN, itin), (BUDGET, budget)):
        yaml.safe_dump(data, open(path, 'w', encoding='utf-8'), allow_unicode=True,
                       sort_keys=False, width=10 ** 6, default_flow_style=False)

    print('\n만들었습니다:')
    print('  %s  — %d일 · 지역 %d · 숙박 %d박' % (ITIN, len(dates), len(regions), n_nights))
    print('  %s  — 통화 %d · 항공권 %d편' % (BUDGET, len(currencies), len(flights)))
    print('\n이어서:')
    print('  python build.py        → %s' % os.path.join(outpath.DEFAULT_DIR, out_html))
    print('  python build_xlsx.py   → %s' % os.path.join(outpath.DEFAULT_DIR, out_xlsx))
    print('\n일정 내용·지도·입장료는 두 YAML 을 열어 채우면 됩니다.')


if __name__ == '__main__':
    try:
        main()
    except (EOFError, KeyboardInterrupt):
        # 답이 모자라거나 사용자가 Ctrl+C 로 끊은 경우. 아무 파일도 만들지 않았습니다.
        sys.exit('\n\n[취소] 아직 아무것도 만들지 않았습니다. 다시 실행하세요.')
