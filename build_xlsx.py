# -*- coding: utf-8 -*-
"""
src/예산.yaml  ->  <output>.xlsx   (파일명은 예산.yaml 의 output 키 · 템플릿 서식 재사용)

수식·서식은 그대로 두고 데이터 행만 다시 씁니다.
    python build_xlsx.py
"""
import io, sys, os
from copy import copy
import yaml, openpyxl

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

try:
    wb.save(XLSX)
    print('생성 완료: %s' % XLSX)
except PermissionError:
    wb.save('_new_예산.xlsx')
    print('!! %s 가 Excel에서 열려 있습니다 → _new_예산.xlsx 로 저장했습니다.' % XLSX)

print('  교통 %d행 · 입장료 %d행 · 일자 %d행'
      % (len(D['transport']), len(D['tickets']), len(D['days'])))
