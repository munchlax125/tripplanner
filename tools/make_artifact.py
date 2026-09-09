# -*- coding: utf-8 -*-
"""빌드된 일정 HTML을 Claude 아티팩트용으로 바꿉니다.

    python tools/make_artifact.py            # <output> 옆에 _artifact.html 로 저장
    python tools/make_artifact.py 경로.html   # 저장 위치 지정

아티팩트는 게시할 때 <!doctype html><head>…</head><body> 껍데기를 덧씌우므로
문서 조각(<style> + 본문)만 넘겨야 합니다. 또 외부 호스트 요청이 전부 막히므로
웹폰트와 [실제 지도 불러오기](Leaflet·타일)를 걷어냅니다.
인라인 SVG 지도 17장과 '구글 지도로 열기' 링크는 그대로 동작합니다.
"""
import io, os, re, sys
import yaml

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(REPO)
sys.path.insert(0, REPO)
import outpath

doc = yaml.safe_load(open('src/일정.yaml', encoding='utf-8'))
SRC = outpath.resolve(doc, make=False)
if not SRC or not os.path.exists(SRC):
    sys.exit('먼저 python build.py 로 %s 를 만드세요.' % (SRC or '<output>'))

s = open(SRC, encoding='utf-8').read()

style = re.search(r'<style>.*?</style>', s, re.S)
body = re.search(r'</head>(.*?)</body>', s, re.S)
if not (style and body):
    sys.exit('예상한 구조가 아닙니다 — head.html 을 바꿨다면 이 스크립트도 고치세요.')
style, body = style.group(0), body.group(1)

# 외부 요청이 막히므로 지도 전환 버튼과 그 스크립트를 걷어냅니다
body = re.sub(r'<button type="button" class="maptog".*?</button>', '', body, flags=re.S)
body = re.sub(r'<script>.*?</script>', '', body, flags=re.S)
n_btn = len(re.findall(r'class="maptog"', s))

# 웹폰트도 막히니 시스템 글꼴로 떨어지게 둡니다 (레이아웃은 그대로)
out = sys.argv[1] if len(sys.argv) > 1 else os.path.splitext(SRC)[0] + '_artifact.html'
open(out, 'w', encoding='utf-8').write(style + '\n' + body.strip() + '\n')

print('생성 완료: %s  (%s bytes)' % (out, format(os.path.getsize(out), ',')))
print('  지도 전환 버튼 %d개 제거 · 인라인 지도 %d장 유지'
      % (n_btn, len(re.findall(r'class="mapsvg"', body))))
for bad in re.findall(r'<(?:!doctype|html|head|body)\b[^>]*>', out and open(out, encoding='utf-8').read(), re.I):
    print('  !! 남아 있는 껍데기 태그:', bad)
