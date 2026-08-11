# -*- coding: utf-8 -*-
"""
src/예산.yaml  ->  여행예산_상하이반영.xlsx  (기존 파일을 템플릿으로 재사용)

수식·서식은 그대로 두고 데이터 행만 다시 씁니다.
    python build_xlsx.py
"""
import io, sys, os
from copy import copy
import yaml, openpyxl

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.chdir(os.path.dirname(os.path.abspath(__file__)))

XLSX = '여행예산_상하이반영.xlsx'
TPL = 'src/예산_템플릿.xlsx'
D = yaml.safe_load(open('src/예산.yaml', encoding='utf-8'))
RATE_ROW = {'GEL': 4, 'AMD': 5, 'EUR': 6, 'AED': 7, 'CNY': 8}

wb = openpyxl.load_workbook(TPL)


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
ws = wb['환율']
for k, r in [('GEL', 4), ('AMD', 5), ('EUR', 6), ('AED', 7), ('CNY', 8)]:
    ws.cell(r, 2).value = D['rates'][k]
ws['B9'].value = D['people']
for i, v in enumerate(D['flights']):
    ws.cell(10 + i, 2).value = v['krw']
    ws.cell(10 + i, 1).value = v['name']
ws['B14'].value = D['total_budget']

# ── 교통상세 ──
ws = wb['교통상세']
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
for i, n in enumerate(D['transport_notes']):
    ws.cell(last + 3 + i, 1).value = n
TR_LAST = last

# ── 입장료 ──
ws = wb['입장료']
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
ws.cell(EN_LAST + 3, 1).value = D['ticket_note']

# ── 일자별예산 ──
ws = wb['일자별예산']
START = 5
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
for i, n in enumerate(D['budget_notes']):
    ws.cell(LAST + 10 + i, 1).value = n

try:
    wb.save(XLSX)
    print('생성 완료: %s' % XLSX)
except PermissionError:
    wb.save('_new_예산.xlsx')
    print('!! %s 가 Excel에서 열려 있습니다 → _new_예산.xlsx 로 저장했습니다.' % XLSX)

print('  교통 %d행 · 입장료 %d행 · 일자 %d행'
      % (len(D['transport']), len(D['tickets']), len(D['days'])))
