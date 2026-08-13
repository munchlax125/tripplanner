# -*- coding: utf-8 -*-
"""새 지역의 오프라인 바탕그림을 만듭니다 — OpenStreetMap + Natural Earth 10m.

    python tools/make_basemap.py m20 --center 35.6812,139.7671 --width-km 4
    python tools/make_basemap.py m21 --center 41.0,44.7 --width-km 300 --detail region

결과물:
    src/basemaps/<id>.svg      — <g class="bm">…</g> 조각 (해안선·수계·도로·국경)
    src/basemaps/_proj.json    — 해당 id의 위경도→픽셀 변환식이 추가/갱신됩니다

만든 뒤에는 src/일정.yaml 의 map_points 에 같은 id로 지점을 넣고 `python build.py`.

주의
  · 첫 실행 때 Natural Earth GeoJSON 4종(약 25MB)을 tools/_cache/ 로 내려받습니다.
  · Overpass API를 쓰므로 만들 때만 인터넷이 필요합니다. 결과물은 완전한 오프라인입니다.
  · width-km 를 키우면 자동으로 도로 등급을 올려 잡습니다(--detail 로 직접 지정 가능).
"""
import argparse, json, math, os, sys, time, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from geolib import (clip_polygon, clip_line, stitch, land_rings,
                    d_line, d_poly, bbox_of, overlaps)

REPO = os.path.dirname(HERE)
DEST = os.path.join(REPO, "src", "basemaps")
CACHE = os.path.join(HERE, "_cache")
NE_BASE = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/"
NE_FILES = {"border": "ne_10m_admin_0_boundary_lines_land",
            "lakes":  "ne_10m_lakes",
            "rivers": "ne_10m_rivers_lake_centerlines",
            "coast":  "ne_10m_coastline"}

# 축척대별 도로 등급 — 넓은 지도에 이면도로까지 넣으면 새까매집니다
DETAIL = {
    "region": "motorway|trunk|primary",
    "wide":   "motorway|trunk|primary|secondary",
    "local":  "motorway|trunk|primary|secondary|tertiary",
    "town":   "motorway|trunk|primary|secondary|tertiary|unclassified|residential|"
              "motorway_link|trunk_link|primary_link",
    "city":   "motorway|trunk|primary|secondary|tertiary|unclassified|residential|living_street|"
              "pedestrian|motorway_link|trunk_link|primary_link|secondary_link|"
              "path|footway|steps|track|cycleway",
}
R1 = {"motorway", "trunk", "motorway_link", "trunk_link"}
R2 = {"primary", "primary_link"}
R3 = {"secondary", "tertiary", "secondary_link", "tertiary_link"}
R5 = {"path", "footway", "steps", "track", "cycleway"}

ENDPOINTS = ["https://overpass-api.de/api/interpreter",
             "https://overpass.kumi.systems/api/interpreter",
             "https://overpass.private.coffee/api/interpreter"]


def auto_detail(width_km):
    if width_km >= 250: return "region"
    if width_km >= 100: return "wide"
    if width_km >= 20:  return "local"
    if width_km >= 5:   return "town"
    return "city"


def fetch(url, path):
    if os.path.exists(path) and os.path.getsize(path) > 1000:
        return path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    print("  내려받는 중: %s" % os.path.basename(path), flush=True)
    urllib.request.urlretrieve(url, path)
    return path


def overpass(query, label):
    last = None
    for attempt in range(6):
        ep = ENDPOINTS[attempt % len(ENDPOINTS)]
        try:
            req = urllib.request.Request(
                ep, data=urllib.parse.urlencode({"data": query}).encode(),
                headers={"User-Agent": "tripplanner-basemap/1.0"})
            with urllib.request.urlopen(req, timeout=300) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:                       # 공용 서버라 혼잡하면 자주 밀립니다
            last = e
            print("  ! %s 시도 %d (%s): %s" % (label, attempt + 1, ep.split("/")[2], e), flush=True)
            time.sleep(8 + attempt * 7)
    raise SystemExit("Overpass 실패: %s (%s)" % (label, last))


def load_ne(path):
    data = json.load(open(path, encoding="utf-8"))
    out = []
    for f in data["features"]:
        g = f.get("geometry")
        if not g:
            continue
        t, c = g["type"], g["coordinates"]
        parts = ([c] if t == "LineString" else c if t in ("MultiLineString", "Polygon") else
                 [r for poly in c for r in poly] if t == "MultiPolygon" else [])
        for p in parts:
            p = [(q[0], q[1]) for q in p if len(q) >= 2]
            if len(p) > 1:
                out.append((bbox_of(p), p))
    return out


def build(mid, lat, lon, width_km, W, H, detail):
    pxkm = W / width_km
    s = pxkm * 111.32                                # 위도 1도당 픽셀
    cosf = math.cos(math.radians(lat))
    a, c = s * cosf, -s                              # x = a*lon + b,  y = c*lat + d
    b, d = W / 2 - a * lon, H / 2 - c * lat
    prj1 = lambda lo, la: (a * lo + b, c * la + d)
    rect = (-4.0, -4.0, W + 4.0, H + 4.0)
    hlon, hlat = (W / 2 + 12) / a, (H / 2 + 12) / s
    gbox = (lon - hlon, lat - hlat, lon + hlon, lat + hlat)

    bb = "%.5f,%.5f,%.5f,%.5f" % (gbox[1] - .01, gbox[0] - .01, gbox[3] + .01, gbox[2] + .01)
    q = ("[out:json][timeout:300];("
         'way["highway"~"^(%s)$"](%s);'
         'way["waterway"~"^(river|canal|stream)$"](%s);'
         'way["natural"="water"](%s);'
         'way["natural"="coastline"](%s);'
         'relation["natural"="water"](%s);'
         ");out geom;" % (DETAIL[detail], bb, bb, bb, bb, bb))
    print("  Overpass %s (%s)" % (bb, detail), flush=True)
    osm = overpass(q, mid)

    roads = {1: [], 2: [], 3: [], 4: [], 5: []}
    riv, water_rings, coast = [], [], []
    for e in osm["elements"]:
        tags = e.get("tags") or {}
        if e["type"] == "way":
            geom = e.get("geometry")
            if not geom:
                continue
            pts = [(g["lon"], g["lat"]) for g in geom if g]
            if len(pts) < 2:
                continue
            hw = tags.get("highway")
            if hw:
                roads[1 if hw in R1 else 2 if hw in R2 else
                      3 if hw in R3 else 5 if hw in R5 else 4].append(pts)
            elif tags.get("natural") == "coastline":
                coast.append(pts)
            elif tags.get("natural") == "water" or tags.get("waterway") == "riverbank":
                if len(pts) > 3:
                    water_rings.append(pts)
            elif tags.get("waterway") in ("river", "canal", "stream"):
                riv.append(pts)
        elif e["type"] == "relation" and tags.get("natural") == "water":
            grp = {"outer": [], "inner": []}
            for m in e.get("members", []):
                g = m.get("geometry")
                if not g:
                    continue
                pts = [(q2["lon"], q2["lat"]) for q2 in g if q2]
                if len(pts) > 1:
                    grp["inner" if m.get("role") == "inner" else "outer"].append(pts)
            for lst in grp.values():
                for ring in stitch(lst):
                    if len(ring) > 3:
                        water_rings.append(ring)

    ne = {k: load_ne(fetch(NE_BASE + v + ".geojson", os.path.join(CACHE, v + ".geojson")))
          for k, v in NE_FILES.items()}
    for bb2, pts in ne["lakes"]:
        if overlaps(bb2, gbox):
            water_rings.append(pts)
    if detail in ("region", "wide"):                 # 넓은 지도는 OSM 대신 NE 수계·해안선
        for key, dst in (("rivers", riv), ("coast", coast)):
            for bb2, pts in ne[key]:
                if overlaps(bb2, gbox):
                    dst.append(pts)

    P = lambda seq: [prj1(lo, la) for lo, la in seq]
    tol = 0.30
    road_d = {}
    for k in (5, 4, 3, 2, 1):
        ch = []
        for w in (stitch(roads[k]) if roads[k] else []):
            ch += clip_line(P(w), rect)
        road_d[k] = d_line(ch, tol)
    rc = []
    for w in (stitch(riv) if riv else []):
        rc += clip_line(P(w), rect)
    riv_d = d_line(rc, tol)
    wr = []
    for ring in water_rings:
        cp = clip_polygon(P(ring), rect)
        if len(cp) > 2:
            wr.append(cp)
    water_d = d_poly(wr, tol)

    cc = []
    for w in (stitch(coast) if coast else []):
        cc += clip_line(P(w), rect)
    coast_d, sea_d = d_line(cc, tol), ""
    if cc:
        # OSM 해안선은 진행 방향 왼쪽이 육지입니다. 화면 좌표에서도 그대로라
        # 육지 링을 닫아 만든 뒤 evenodd 로 "화면 − 육지" = 바다를 칠합니다.
        rings = land_rings(cc, rect)
        if rings:
            sea_d = "M0,0 %d,0 %d,%d 0,%d Z" % (W, W, H, H) + d_poly(rings, tol)
    bc = []
    for bb2, pts in ne["border"]:
        if overlaps(bb2, gbox):
            bc += clip_line(P(pts), rect)
    bord_d = d_line(bc, tol)

    g = ['<g class="bm" aria-hidden="true">']
    if sea_d:   g.append('<path class="bm-sea" fill-rule="evenodd" d="%s"/>' % sea_d)
    if water_d: g.append('<path class="bm-water" d="%s"/>' % water_d)
    if riv_d:   g.append('<path class="bm-riv" d="%s"/>' % riv_d)
    if coast_d: g.append('<path class="bm-coast" d="%s"/>' % coast_d)
    for k in (5, 4, 3, 2, 1):
        if road_d[k]:
            g.append('<path class="bm-r%d" d="%s"/>' % (k, road_d[k]))
    if bord_d:  g.append('<path class="bm-bord" d="%s"/>' % bord_d)
    g.append("</g>")

    os.makedirs(DEST, exist_ok=True)
    svg = "".join(g)
    open(os.path.join(DEST, mid + ".svg"), "w", encoding="utf-8").write(svg)
    entry = dict(basemap=mid + ".svg", W=W, H=H, a=a, b=b, c=c, d=d,
                 pxkm=round(pxkm, 3), scale_km=0.0, scale_y=H - 15, fit_err=0.0)
    pp = os.path.join(DEST, "_proj.json")
    proj = json.load(open(pp, encoding="utf-8")) if os.path.exists(pp) else {}
    proj[mid] = entry
    json.dump(proj, open(pp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print("  → src/basemaps/%s.svg  %.1f KB · %.2f px/km · 도로 %s%s%s%s"
          % (mid, len(svg) / 1024, pxkm, [k for k in (1, 2, 3, 4, 5) if road_d[k]],
             " · 수면" if water_d else "", " · 바다" if sea_d else "",
             " · 국경" if bord_d else ""))
    print("  → _proj.json 에 %s 등록" % mid)


def main():
    ap = argparse.ArgumentParser(description="오프라인 벡터 바탕그림 생성기")
    ap.add_argument("id", help="지도 id (예: m20). map_points 의 키와 같아야 합니다")
    ap.add_argument("--center", required=True, metavar="LAT,LON", help="지도 중심 위경도")
    ap.add_argument("--width-km", type=float, required=True, help="지도 가로 폭(km)")
    ap.add_argument("--size", default="640x300", metavar="WxH", help="캔버스 크기 (기본 640x300)")
    ap.add_argument("--detail", choices=sorted(DETAIL), help="도로 등급 (기본: 폭에서 자동)")
    args = ap.parse_args()

    lat, lon = (float(v) for v in args.center.split(","))
    W, H = (int(v) for v in args.size.lower().split("x"))
    detail = args.detail or auto_detail(args.width_km)
    print("%s: 중심 %.5f,%.5f · 폭 %gkm · %dx%d · %s" % (args.id, lat, lon, args.width_km, W, H, detail))
    build(args.id, lat, lon, args.width_km, W, H, detail)


if __name__ == "__main__":
    main()
