# -*- coding: utf-8 -*-
"""
src/예산.yaml  ->  <output>.xlsx   (파일명은 예산.yaml 의 output 키 · 템플릿 서식 재사용)

수식·서식은 그대로 두고 데이터 행만 다시 씁니다.
    python build_xlsx.py

'일정' 시트는 예외로 매번 지우고 새로 만듭니다 — 템플릿에 없는 시트라
서식을 물려받을 데가 없고, 그래서 행이 줄어도 옛 값이 남지 않습니다.
소스는 예산.yaml 의 itinerary_source 가 가리키는 일정 YAML 이고,
키가 없거나 파일이 없으면 시트를 만들지 않습니다.
"""
import io, sys, os, re, html
from copy import copy
import yaml, openpyxl
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.chdir(os.path.dirname(os.path.abspath(__file__)))

TPL = 'src/예산_템플릿.xlsx'   # 서식·수식 원본. 데이터는 전부 예산.yaml 에서 옵니다
D = yaml.safe_load(open('src/예산.yaml', encoding='utf-8'))

XLSX = D.get('output')
if not XLSX:
    sys.exit("src/예산.yaml 에 'output: 파일명.xlsx' 를 넣으세요.")
# 템플릿 '환율' 시트의 통화별 행 번호. 통화를 바꾸려면 템플릿 행과 여기를 같이 맞추세요.
RATE_ROW = D.get('rate_rows')
if not RATE_ROW:
    sys.exit("src/예산.yaml 에 'rate_rows: {통화: 행번호}' 를 넣으세요.")

# 시트 제목·설명·통화 표기도 YAML 이 정합니다 (템플릿에 남은 이전 여행 문구를 덮어씁니다)
TITLES = D.get('sheet_titles') or {}
INTROS = D.get('sheet_intros') or {}
RATE_LABEL = D.get('rate_labels') or {}
RATE_NOTE = D.get('rate_notes') or {}

wb = openpyxl.load_workbook(TPL)


def head(sheet, title_row=1, intro_row=None):
    """시트 머리글을 YAML 값으로 덮어씁니다. 값이 없으면 비웁니다."""
    ws = wb[sheet]
    ws.cell(title_row, 1).value = TITLES.get(sheet, sheet)
    if intro_row:
        ws.cell(intro_row, 1).value = INTROS.get(sheet, '')
    return ws


def clear(ws, r0, r1, ncol):
    """템플릿에 남아 있는 이전 여행의 값을 지웁니다.

    행 수가 줄어드는 항목(통화·항공편·주석)은 덮어쓰기만으로는 옛 내용이 남습니다.
    """
    for r in range(r0, r1 + 1):
        for c in range(1, ncol + 1):
            ws.cell(r, c).value = None


def resize(ws, start, need, ncol):
    """템플릿의 데이터 행 수를 실측해 need 행으로 맞춘다."""
    have = 0
    while (ws.cell(start + have, 1).value is not None and
           ws.cell(start + have, 2).value is not None):
        have += 1
    if need > have:
        ws.insert_rows(start + have, need - have)
        for r in range(start + have, start + need):
            for c in range(1, ncol + 1):
                ws.cell(r, c)._style = copy(ws.cell(start, c)._style)
    elif need < have:
        ws.delete_rows(start + need, have - need)
    return have

# ── 환율 ──
ws = head('환율')
# 템플릿 구조: 4~8행 통화 · 9행 인원 · 10~13행 항공권 · 14행 총예산
RATE_BLOCK = D.get('rate_block') or [4, 8]
FLIGHT_BLOCK = D.get('flight_block') or [10, 13]
clear(ws, RATE_BLOCK[0], RATE_BLOCK[1], 3)
for k, r in RATE_ROW.items():
    ws.cell(r, 1).value = RATE_LABEL.get(k, '%s → 원' % k)
    ws.cell(r, 2).value = D['rates'][k]
    ws.cell(r, 3).value = RATE_NOTE.get(k, '')
ws['B9'].value = D['people']
clear(ws, FLIGHT_BLOCK[0], FLIGHT_BLOCK[1], 3)
for i, v in enumerate(D.get('flights') or []):
    ws.cell(FLIGHT_BLOCK[0] + i, 1).value = v['name']
    ws.cell(FLIGHT_BLOCK[0] + i, 2).value = v['krw']
ws['B14'].value = D['total_budget']

# ── 교통상세 ──
ws = head('교통상세', intro_row=2)
START = 5
rows = D['transport']
need = len(rows)
resize(ws, START, need, 9)
for i, t in enumerate(rows):
    r = START + i
    for c, v in enumerate([t['date'], t['seg'], t['mode'], t['kind'],
                           t['amt'], t['cur'],
                           '=ROUND(E%d*환율!$B$%d/1,0)' % (r, RATE_ROW[t['cur']]),
                           t['pub'], t.get('note', '')], start=1):
        ws.cell(r, c).value = v
last = START + need - 1
ws.cell(last + 1, 1).value = '교통비 합계'
ws.cell(last + 1, 7).value = '=SUM(G%d:G%d)' % (START, last)
clear(ws, last + 2, last + 14, 1)
for i, n in enumerate(D.get('transport_notes') or []):
    ws.cell(last + 3 + i, 1).value = n
TR_LAST = last

# ── 입장료 ──
ws = head('입장료')
START = 4
rows = D['tickets']
need = len(rows)
resize(ws, START, need, 6)
for i, t in enumerate(rows):
    r = START + i
    for c, v in enumerate([t['date'], t['place'], t['amt'], t['cur'],
                           '=ROUND(C%d*환율!$B$%d,0)' % (r, RATE_ROW[t['cur']]),
                           t.get('note', '')], start=1):
        ws.cell(r, c).value = v
EN_LAST = START + need - 1
ws.cell(EN_LAST + 1, 2).value = '입장료 합계'
ws.cell(EN_LAST + 1, 5).value = '=SUM(E%d:E%d)' % (START, EN_LAST)
ws.cell(EN_LAST + 3, 1).value = D.get('ticket_note', '')

# ── 일자별예산 ──
ws = head('일자별예산', intro_row=2)
START = 5
resize(ws, START, len(D['days']), 11)     # 날짜 수가 줄면 옛 행이 남으므로 먼저 맞춥니다
SIF = ('=SUMIFS(교통상세!$G$5:$G${L},교통상세!$A$5:$A${L},A{r},'
       '교통상세!$D$5:$D${L},"{k}")')
for i, d in enumerate(D['days']):
    r = START + i
    ws.cell(r, 1).value = d['date']
    ws.cell(r, 2).value = d['dow']
    ws.cell(r, 3).value = d['desc']
    ws.cell(r, 4).value = ('=SUMIF(입장료!$A$4:$A$%d,A%d,입장료!$E$4:$E$%d)' % (EN_LAST, r, EN_LAST))
    ws.cell(r, 5).value = d['food']
    ws.cell(r, 6).value = d['stay']
    ws.cell(r, 7).value = d['cafe']
    ws.cell(r, 8).value = SIF.format(L=TR_LAST, r=r, k='시외')
    ws.cell(r, 9).value = SIF.format(L=TR_LAST, r=r, k='시내')
    ws.cell(r, 10).value = '=SUM(D%d:I%d)' % (r, r)
    ws.cell(r, 11).value = '=J%d' % r if i == 0 else '=K%d+J%d' % (r - 1, r)
LAST = START + len(D['days']) - 1
for c in range(4, 11):
    ws.cell(LAST + 1, c).value = '=SUM(%s%d:%s%d)' % (
        chr(64 + c), START, chr(64 + c), LAST)
clear(ws, LAST + 10, LAST + 30, 1)
for i, n in enumerate(D.get('budget_notes') or []):
    ws.cell(LAST + 10 + i, 1).value = n

# ── 일정 ──────────────────────────────────────────────────────────────
# 코스와 비용을 한 파일에서 보려고 붙인 시트입니다. 일정 YAML 이 유일한 소스라
# HTML 과 엑셀이 갈라질 수 없습니다.
ITIN = D.get('itinerary_source')
n_day = n_row = 0
if ITIN and os.path.exists(ITIN):
    doc = yaml.safe_load(open(ITIN, encoding='utf-8'))

    def plain(s):
        """본문은 HTML 조각이라 태그를 걷어내고 엑셀 셀에 넣습니다."""
        if s is None:
            return ''
        return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', '', str(s)))).strip()

    def headline(s):
        """제목의 <span class="tag"> 는 덧붙는 꼬리표라 구분자를 넣고 벗깁니다."""
        return plain(re.sub(r'<span class="tag[^"]*">', ' — ', str(s or '')))

    if '일정' in wb.sheetnames:
        del wb['일정']
    ws = wb.create_sheet('일정', 0)

    HEAD = ['날짜', '요일', '구간', '시각', '이동', '내용', '비고']
    WIDTH = [8, 5, 30, 7, 15, 54, 62]
    C_TITLE = Font(bold=True, size=14)
    C_HEAD = Font(bold=True, color='FFFFFF')
    FILL_HEAD = PatternFill('solid', fgColor='42606E')
    FILL_DAY = PatternFill('solid', fgColor='EDF1F3')
    FILL_MOVE = PatternFill('solid', fgColor='FAF0E6')
    THIN = Side(style='thin', color='D8DEE2')
    BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
    WRAP = Alignment(vertical='top', wrap_text=True)
    TOP = Alignment(vertical='top')

    ws.cell(1, 1).value = TITLES.get('일정', '일정')
    ws.cell(1, 1).font = C_TITLE
    ws.cell(2, 1).value = INTROS.get('일정', '')
    ws.cell(2, 1).alignment = TOP
    for i, (h, w) in enumerate(zip(HEAD, WIDTH), start=1):
        c = ws.cell(4, i)
        c.value, c.font, c.fill, c.border = h, C_HEAD, FILL_HEAD, BOX
        ws.column_dimensions[get_column_letter(i)].width = w

    r = 5

    def put(vals, fill=None, bold=False):
        global r
        for i, v in enumerate(vals, start=1):
            c = ws.cell(r, i)
            c.value = v
            c.alignment = WRAP
            c.border = BOX
            if fill:
                c.fill = fill
            if bold:
                c.font = Font(bold=True)
        r += 1

    for blk in doc.get('blocks') or []:
        if blk.get('type') == 'border':
            # 항공·국경 이동은 날짜 칸 없이 한 줄로 끼워 넣습니다
            put(['', '', '✈ 이동', '', '', plain(blk.get('title')),
                 plain(blk.get('note'))], fill=FILL_MOVE, bold=True)
            n_row += 1
            continue
        if blk.get('type') != 'day':
            continue
        n_day += 1
        date, dow = blk['date'].replace('.', '/'), blk.get('dow', '')
        put([date, dow, headline(blk.get('place')), '', '',
             plain(blk.get('sub')), ''], fill=FILL_DAY, bold=True)
        n_row += 1
        # 날짜·요일은 모든 행에 넣습니다 — 4행 필터로 하루만 뽑을 때 중간 행이 빠지면 안 됩니다
        for grp in blk.get('sched') or []:
            for row in grp.get('rows') or []:
                note = ' · '.join(plain(s) for s in (row.get('small') or []))
                tag = (row.get('tag') or {}).get('text')
                if tag:
                    note = ('[%s] ' % plain(tag)) + note if note else '[%s]' % plain(tag)
                put([date, dow, '', plain(row.get('t')), plain(row.get('bus')),
                     plain(row.get('text')), note])
                n_row += 1
        for f in blk.get('flags') or []:
            put([date, dow, '', '', '주의', plain(f), ''])
            n_row += 1

    ws.freeze_panes = 'A5'
    ws.auto_filter.ref = 'A4:G%d' % (r - 1)

try:
    wb.save(XLSX)
    print('생성 완료: %s' % XLSX)
except PermissionError:
    wb.save('_new_예산.xlsx')
    print('!! %s 가 Excel에서 열려 있습니다 → _new_예산.xlsx 로 저장했습니다.' % XLSX)

print('  교통 %d행 · 입장료 %d행 · 일자 %d행'
      % (len(D['transport']), len(D['tickets']), len(D['days'])))
if n_day:
    print('  일정 %d일 · %d행' % (n_day, n_row))
elif ITIN:
    print('  일정 시트 없음 — %s 를 찾지 못했습니다' % ITIN)
