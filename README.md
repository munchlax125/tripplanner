# 여행 일정·예산 생성기

YAML 두 개를 고치면 **인터넷 없이 열리는 HTML 일정표 한 장**과 **엑셀 예산표**가 나옵니다.
지도는 파일 안에 벡터로 그려져 있어 비행기·산속·로밍 없는 곳에서도 그대로 보입니다.

```bash
pip install pyyaml openpyxl

cp starter/일정.yaml src/일정.yaml     # 처음 한 번
cp starter/예산.yaml src/예산.yaml

python build.py        # src/일정.yaml  →  <output>.html
python build_xlsx.py   # src/예산.yaml  →  <output>.xlsx
```

> **`src/` 안의 YAML만 고치세요.** HTML·엑셀은 생성물이라 다시 빌드하면 덮어써지고, 저장소에도 올라가지 않습니다.

---

## 무엇이 나오나

**HTML 일정표** — 하루 한 칸씩 세로로 흐르는 단일 파일.

- 시각별 일정표, 교통수단 뱃지, 입장료 태그, 주의사항 박스
- 날짜별 **경로 지도** — 해안선·수계·도로·국경이 그려진 진짜 지도 위에 방문 순서 표시
- 관광지 이름에 **구글 지도 링크** — 누르면 그 장소의 영업시간·사진·리뷰가 바로 뜹니다
- 숙박 배분 막대, 항공편 목록, 사전 확인 목록
- 라이트/다크/인쇄 모드 대응
- **로드할 때 외부 요청이 없습니다.** 버튼을 눌렀을 때만 Leaflet 지도를 내려받습니다

**엑셀 예산표** — 환율·교통상세·입장료·일자별예산 4개 시트. 합계와 SUMIFS 참조 범위는 행 수에 맞춰 자동으로 다시 씁니다.

---

## 새 여행 만들기

### 1. 문서 머리와 출력 파일명

```yaml
output: 내여행.html                # (필수) 만들어질 파일 이름
doc_title: 도쿄 5박 6일             # 브라우저 탭 제목
eyebrow: 2026 · 간토
title: 도쿄<span class="sep">·</span>하코네
subtitle: 4월 3일 – 4월 8일 · 2인 · 나리타 IN · 하네다 OUT
standfirst: 한 문단짜리 요약. 이 일정이 왜 이렇게 짜였는지 씁니다.
```

### 2. 지역별 색

일정 전체가 나라·지역별 색으로 구분됩니다. **키 이름은 자유**이고, CSS는 여기서 자동 생성됩니다.

```yaml
colors:
  jp:                       # 다크 모드에서 밝은 색을 쓰려면 나눠서
    light: '#42606E'
    dark: '#8FB4C4'
  kr: '#C87518'             # 하나만 줘도 됩니다
legend:
  - {cls: jp, label: 일본}
nights:
  - {name: 도쿄, cls: jp, n: 3}
  - {name: 하코네, cls: jp, n: 2}
nights_total: 도쿄 3박 + 하코네 2박 = 5박
```

막대 길이는 `n`에서 자동 계산됩니다.

### 3. 하루 쓰기

```yaml
blocks:
  - type: day
    cls: day jp stay          # ← 두 번째 낱말이 colors 의 키입니다 (필수)
    date: '4.3'               #   stay 를 붙이면 그날 숙박 표시
    dow: 금
    place: 나리타 → 아사쿠사 <span class="tag">스카이라이너</span>
    sub: 도착일. 짐 풀고 저녁 산책만.
    sched:
      - label: null           # 'A안' 같은 분기 제목. 보통 null
        rows:
          - t: '15:10'
            bus: 스카이라이너   # 교통수단 알약 뱃지
            text: 우에노까지
            tag: {text: 2,570엔, hot: false}   # hot:true 면 빨강
            small:
              - 41분 · 30분 간격
              - 여러 줄 쓸 수 있습니다
    map:
      id: m01
      cap: 지도 아래 붙는 설명 한 줄
    flags:
      - <b>굵게</b> 쓸 수 있는 주의사항 박스. 여러 개 가능합니다.

  - type: border              # 도시·나라가 바뀌는 구간
    title: 4/5 — 도쿄 → 하코네
    note: 신주쿠에서 오다큐 로망스카 90분.
```

문단 제목은 `labels`로 바꾸고, 빈 문자열을 주면 그 제목이 사라집니다. `flights`·`nights`·`notes`가 없으면 그 구획 자체가 빠집니다.

**나라별 보기는 자동입니다.** 날짜 블록 `cls`의 두 번째 낱말(색 키)을 모아 위쪽에 탭을 만들고,
개요 화면에 나라 카드를 깔아 줍니다. 이름은 `legend`의 `label`, 박수와 도시는 `nights`에서 가져옵니다.
`type: border` 블록은 **도착하는 쪽 나라**에 붙습니다.

```yaml
labels:
  view_home: 개요          # 기본값
  view_all: 전체 일정      # 기본값
  regions: 나라별로 보기    # 개요 화면의 카드 제목
```

라디오 버튼과 `:checked`만 씁니다 — **자바스크립트가 없어도 동작하고, 인쇄하면 모든 나라가 그대로 나옵니다.**

### 4. 바탕그림 만들기 ★

**새 여행에서 가장 먼저 할 일입니다.** 지도는 지역별 바탕그림이 있어야 그려집니다.

```bash
python tools/make_basemap.py m01 --center 35.7100,139.7900 --width-km 6
python tools/make_basemap.py m00 --center 35.4,139.3 --width-km 120 --size 640x460
```

- `--center` 지도 중심 위경도, `--width-km` 가로 폭
- `--detail`은 폭에서 자동으로 정해집니다 — `region`(250km+, 고속·간선만) / `wide` / `local` / `town` / `city`(5km 미만, 보행로·계단까지)
- `src/basemaps/<id>.svg`가 만들어지고 `_proj.json`에 변환식이 등록됩니다

만들 때만 인터넷이 필요합니다(OpenStreetMap Overpass + Natural Earth). **결과물은 완전한 오프라인입니다.**

> 폭을 잡는 요령: 방문 지점이 다 들어가고 사방에 여백이 조금 남는 크기. 너무 크게 잡으면 지점들이 가운데 한 점으로 뭉칩니다.

### 5. 지도 지점 넣기

**`[이름, 위도, 경도]`** 목록만 넣으면 투영·축척·마커·라벨·경로선·순서 문구·구글지도 링크·[실제 지도 불러오기] 데이터가 전부 자동으로 만들어집니다.

```yaml
overview_map: m00        # 맨 위 전체 개요 지도 (없으면 개요 지도 없음)
map_points:
  m01:
    - [나리타 공항, 35.7720, 140.3929]
    - [우에노역, 35.7141, 139.7774]
    - [센소지, 35.7148, 139.7967]
```

- 같은 곳을 두 번 들르면 마커 하나에 `1·4`처럼 번호를 묶습니다
- 지점이 바탕그림을 벗어나면 자동으로 축소·이동합니다(축척 막대도 같이 조정)
- 라벨은 좌우·상하 충돌을 피해 자동 배치됩니다

지도 아래 **[구글 지도로 열기 ↗]** 는 이 지점들을 이어 경로로 엽니다. 경유지를 좌표로 넘기면
구글에서 핀이 전부 `42°39'43.9"N …` 같은 무명 카드로 뜨므로, `map_queries`에 검색어를 넣어
각 지점이 제대로 된 장소로 열리게 하세요. **없는 지점만 좌표로 넘어갑니다.**

```yaml
map_queries:
  게르게티 삼위일체 교회: Gergeti Trinity Church
  디두베 터미널: Didube Bus Station Tbilisi
  트빌리시: Tbilisi Georgia
```

`places`와 따로 두는 이유는, `places`는 본문 글자에도 밑줄 링크를 걸기 때문입니다 —
거기에 도시명을 넣으면 `트빌리시행`, `트빌리시 복귀` 같은 말마다 밑줄이 그어집니다.

### 6. 관광지 링크

일정 본문에 나오는 이름에 구글 지도 링크를 겁니다. **값은 좌표가 아니라 검색어**입니다 — 좌표로 열면 빈 핀만 찍히고 영업시간·사진이 안 뜨기 때문입니다.

```yaml
places:
  센소지: Senso-ji Temple Asakusa Tokyo
  하코네유모토: Hakone-Yumoto Station
```

- **현지/영문 표기 + 도시명**으로 두면 동명이인을 피할 수 있습니다
- 긴 이름부터 매칭합니다 — `우에노 공원`이 `우에노`에 먼저 먹히지 않습니다
- 한 행에 같은 이름은 한 번만 걸립니다
- **도시·역 이름은 넣지 마세요.** `도쿄행`, `도쿄 복귀`처럼 자주 나오는 낱말에 밑줄이 그어지면 지저분합니다. 찾아가야 할 곳만 넣으세요

표시는 점선 밑줄입니다(인쇄하면 사라집니다).

### 7. 예산

```yaml
output: 내여행_예산.xlsx
rates: {JPY: 9.1}                 # 1단위당 원화
rate_rows: {JPY: 4}               # 템플릿 '환율' 시트의 행 번호
rate_labels: {JPY: 일본 엔 (JPY) → 원}
sheet_titles: {입장료: 입장료}       # 시트 제목·설명도 여기서
people: 2
total_budget: 2000000
flights:
  - {name: 인천→나리타 왕복, krw: 420000}
transport:
  - {date: 4/3, seg: 나리타 → 우에노, mode: 스카이라이너, kind: 시외,
     amt: 2570, cur: JPY, pub: '○', note: 41분}
tickets:
  - {date: 4/3, place: 센소지, amt: 0, cur: JPY, note: 무료}
days:
  - {date: 4/3, dow: 금, desc: 도쿄 — 아사쿠사, food: 30000, stay: 60000, cafe: 6000}
```

- `kind`는 `시외`/`시내` — 일자별 집계 기준입니다
- `pub`은 `○` 대중교통 / `△` 부분 / `✕` 택시 필수
- `days`의 `date`는 `transport`·`tickets`의 `date`와 **글자가 정확히 같아야** 집계됩니다
- 통화가 5개를 넘으면 `src/예산_템플릿.xlsx`의 환율 시트에 행을 먼저 만들고 `rate_rows`를 맞추세요

---

## 파일 구조

```
src/
  일정.yaml            ← 일정 본문 · 지도 지점 · 관광지 링크표
  예산.yaml            ← 환율 · 교통 · 입장료 · 일자별 예산
  head.html            ← <head> + CSS (디자인)
  script.html          ← [실제 지도 불러오기] 버튼 스크립트
  예산_템플릿.xlsx       ← 엑셀 서식·수식 원본
  basemaps/
    <id>.svg           ← 오프라인 바탕그림
    _proj.json         ← 지도별 위경도→픽셀 변환식

starter/               ← 새 여행 시작용 최소 예시
tools/
  make_basemap.py      ← 새 지역 바탕그림 생성기
  geolib.py            ← 클리핑·단순화·해안선 처리

build.py               ← HTML 생성기
build_xlsx.py          ← 엑셀 생성기
```

---

## 지도가 어떻게 그려지나

**등장방형 투영**입니다. 위경도에서 픽셀로 가는 변환이 1차식 네 개(`a b c d`)로 끝납니다.

```
x = a·경도 + b
y = c·위도 + d        (a = c·cos(중심위도) 로 가로세로 비율을 맞춥니다)
```

이 값이 `_proj.json`에 지도별로 들어 있고, 바탕그림 SVG는 **같은 변환으로 미리 그려둔 벡터**입니다. 그래서 지점을 옮겨도 바탕그림과 절대 어긋나지 않습니다. 지점이 화면을 벗어나면 바탕그림과 지점에 **같은 `translate`+`scale`을 걸어** 함께 축소합니다.

레이어는 뒤에서부터 바다 → 수면 → 하천 → 해안선 → 도로(작은 것부터) → 국경 순입니다.

**데이터 출처** — 도로·수계·해안선은 OpenStreetMap, 국경·호수·하천(광역)·해안선(광역)은 Natural Earth 10m.

---

## 검증

```bash
python build.py
python -c "import re,xml.etree.ElementTree as ET;import sys;s=open(sys.argv[1],encoding='utf-8').read();\
print([(t,len(re.findall('<%s[ >]'%t,s)),len(re.findall('</%s>'%t,s))) for t in ('div','ul','li','svg','p','span','a')]);\
[ET.fromstring(v) for v in re.findall(r'<svg .*?</svg>',s,re.S)];print('SVG OK')" 내여행.html
```

열린 태그 수와 닫힌 태그 수가 같고 `SVG OK`가 나오면 정상입니다.

엑셀은 **열어두면 저장이 막힙니다.** 빌드 전에 Excel을 닫으세요(닫혀 있지 않으면 `_new_예산.xlsx`로 대신 저장됩니다).

---

## 알려진 제약

| 항목 | 내용 |
|---|---|
| 바탕그림 범위 | 자동 맞춤은 **축소만** 합니다. 지점이 바탕그림 바깥이면 여백만 늘어나니 새로 만드세요 |
| Overpass | 공용 서버라 504·429가 잦습니다. 생성기가 3개 서버를 6번까지 자동 재시도합니다 |
| 웹폰트 | `head.html`이 구글 폰트를 부릅니다. 오프라인이면 시스템 폰트로 대체되고 레이아웃은 유지됩니다 |
| 엑셀 캐시값 | openpyxl이 계산값을 비우므로 Excel에서 열면 자동 재계산됩니다 |
| 숙박비 | `예산.yaml`의 `days[].stay`에 원화 정액으로 들어갑니다(환율 연동 아님) |
| 겹치는 지점 | 인라인 SVG는 `1·4`로 묶지만, [실제 지도]에서는 마커가 따로 찍혀 겹칩니다 |
