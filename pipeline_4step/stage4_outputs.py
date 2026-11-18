# -*- coding: utf-8 -*-
"""第 4 步：HTML 3D 可视化 + Excel 报表（纯数据，不碰 OCP、不读 STEP）。

HTML：单文件，内嵌 Three.js（与展示站同款 three.min.js +
OrbitControls.js），分支用 CatmullRom 样条 + TubeGeometry 扫管，
显示直径 = 真实直径 × 0.3（展示站同款压细，只做参考；长度/直径/
节点链接等工程参数以 Excel 与 topology.json 为准，不从简化几何重算）。
节点按类型着色，点击出信息窗。用户本地浏览器打开即可，不依赖联网。
Excel：汇总 / 分支 / 节点 / 线段 / 走线 / 接触关系 / 实体清单。
"""
import json
import os

THREE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "harness-showcase", "site", "threejs")

NODE_COLORS = {
    "connector": 0x2ecc71,   # 绿：连接器
    "clamp": 0xe67e22,       # 橙：卡扣
    "fork": 0x3498db,        # 蓝：分支点
    "joint": 0x9b59b6,       # 紫：接头
    "hanging": 0xe74c3c,     # 红：悬空端
    "tie": 0xf1c40f,         # 黄：扎带
}


def build_html(topology, entities, out_path, log):
    """生成单文件 3D HTML。"""
    three_js = ""
    orbit_js = ""
    for name, attr in (("three.min.js", "three_js"), ("OrbitControls.js", "orbit_js")):
        p = os.path.join(THREE_DIR, name)
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                if attr == "three_js":
                    three_js = f.read()
                else:
                    orbit_js = f.read()
    cdn_fallback = ""
    if not three_js:
        cdn_fallback = (
            '<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/0.152.2/three.min.js"></script>\n'
            '<script src="https://cdn.jsdelivr.net/npm/three@0.152.2/examples/js/controls/OrbitControls.js"></script>')
        log("[HTML] 警告：本地 three.min.js 未找到，改用 CDN（需联网）")

    branches = [{
        "key": b["key"], "name": b["occ"], "dia": b["dia"],
        "length": b["length"], "src": b["src"],
        "polyline": b["polyline"], "segs": b["segs"],
        "node0": b["node0"], "node1": b["node1"],
    } for b in topology["branches"]]
    nodes = [{
        "code": n["code"], "type": n["type"], "name": n["name_3d"],
        "xyz": n["xyz"], "degree": n["degree"],
        "segments": n["segments"], "entity": n["entity"],
    } for n in topology["nodes"]]
    data_json = json.dumps({"branches": branches, "nodes": nodes,
                            "file": topology["file"]}, ensure_ascii=False)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>线束3D拓扑 - {topology["file"]}</title>
<style>
body{{margin:0;overflow:hidden;background:#111;font-family:sans-serif}}
#info{{position:fixed;top:12px;left:12px;color:#fff;background:rgba(0,0,0,.65);
padding:10px 14px;border-radius:8px;font-size:13px;max-width:320px;z-index:5}}
#info h3{{margin:0 0 6px;font-size:15px}}
#info .row{{margin:2px 0;color:#ddd}}
#legend{{position:fixed;bottom:12px;left:12px;color:#fff;background:rgba(0,0,0,.65);
padding:8px 12px;border-radius:8px;font-size:12px;z-index:5}}
#legend span{{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px}}
#panel{{position:fixed;top:12px;right:12px;color:#fff;background:rgba(0,0,0,.75);
padding:12px 14px;border-radius:8px;font-size:13px;max-width:300px;z-index:5;display:none}}
#panel h4{{margin:0 0 8px}}
#panel .row{{margin:3px 0;color:#ddd;word-break:break-all}}
</style></head><body>
<div id="info"><h3>线束3D拓扑</h3>
<div class="row">文件：{topology["file"]}</div>
<div class="row">分支 {len(branches)} · 节点 {len(nodes)} · 线段 {len(topology["segments"])} · 走线 {len(topology["runs"])}</div>
<div class="row">拖动旋转 · 滚轮缩放 · 点击节点/分支查看</div>
<div class="row" style="color:#999">显示管径为真实值×0.3（只做参考）</div></div>
<div id="legend"><span style="background:#2ecc71"></span>连接器
<span style="background:#e67e22"></span>卡扣
<span style="background:#3498db"></span>分支点
<span style="background:#9b59b6"></span>接头
<span style="background:#e74c3c"></span>悬空端</div>
<div id="panel"></div>
{cdn_fallback}
<script>{three_js}</script>
<script>{orbit_js}</script>
<script>
var DATA = {data_json};
var scene = new THREE.Scene();
scene.background = new THREE.Color(0x111111);
var camera = new THREE.PerspectiveCamera(50, innerWidth/innerHeight, 0.1, 100000);
var renderer = new THREE.WebGLRenderer({{antialias:true}});
renderer.setSize(innerWidth, innerHeight);
document.body.appendChild(renderer.domElement);
var controls = new THREE.OrbitControls(camera, renderer.domElement);
var center = new THREE.Vector3(), bbox = new THREE.Box3();
var tubeMat = new THREE.MeshStandardMaterial({{color:0x8f9bb3, roughness:0.6, metalness:0.2}});
var pickables = [];
DATA.branches.forEach(function(b){{
  if (!b.polyline || b.polyline.length < 2) return;
  var pts = b.polyline.map(function(p){{ return new THREE.Vector3(p[0], p[1], p[2]); }});
  var curve = new THREE.CatmullRomCurve3(pts);
  var r = Math.max((b.dia || 10) / 2 * 0.3, 0.8);
  var geo = new THREE.TubeGeometry(curve, Math.max(pts.length * 2, 8), r, 8, false);
  var mesh = new THREE.Mesh(geo, tubeMat);
  mesh.userData = {{kind:'branch', b:b}};
  scene.add(mesh); pickables.push(mesh);
  pts.forEach(function(p){{ bbox.expandByPoint(p); }});
}});
var nodeGeo = new THREE.SphereGeometry(6, 12, 12);
var colors = {{connector:0x2ecc71, clamp:0xe67e22, fork:0x3498db, joint:0x9b59b6, hanging:0xe74c3c, tie:0xf1c40f}};
DATA.nodes.forEach(function(n){{
  var mat = new THREE.MeshStandardMaterial({{color: colors[n.type] || 0xffffff, roughness:0.4}});
  var m = new THREE.Mesh(nodeGeo, mat);
  m.position.set(n.xyz[0], n.xyz[1], n.xyz[2]);
  m.userData = {{kind:'node', n:n}};
  scene.add(m); pickables.push(m);
  bbox.expandByPoint(m.position);
}});
bbox.getCenter(center);
controls.target.copy(center);
var size = bbox.getSize(new THREE.Vector3()).length();
camera.position.set(center.x + size*0.6, center.y - size*0.8, center.z + size*0.6);
camera.near = size/1000; camera.far = size*10; camera.updateProjectionMatrix();
scene.add(new THREE.AmbientLight(0xffffff, 0.7));
var dl = new THREE.DirectionalLight(0xffffff, 0.8);
dl.position.set(1,1,1); scene.add(dl);
var ray = new THREE.Raycaster(), mouse = new THREE.Vector2();
var panel = document.getElementById('panel');
renderer.domElement.addEventListener('click', function(ev){{
  mouse.x = (ev.clientX/innerWidth)*2-1;
  mouse.y = -(ev.clientY/innerHeight)*2+1;
  ray.setFromCamera(mouse, camera);
  var hits = ray.intersectObjects(pickables, false);
  if (!hits.length) {{ panel.style.display='none'; return; }}
  var u = hits[0].object.userData, h = '';
  if (u.kind === 'node') {{
    var n = u.n;
    h = '<h4>'+n.code+'（'+n.type+'）</h4>'
      + '<div class="row">名称：'+(n.name||'（无实体名）')+'</div>'
      + '<div class="row">坐标：['+n.xyz.map(function(v){{return v.toFixed(1)}}).join(', ')+']</div>'
      + '<div class="row">度数：'+n.degree+'</div>'
      + '<div class="row">相连线段：'+n.segments.join(', ')+'</div>';
  }} else {{
    var b = u.b;
    h = '<h4>分支</h4>'
      + '<div class="row">名称：'+(b.name||b.key)+'</div>'
      + '<div class="row">长度：'+b.length.toFixed(1)+'mm · 直径：'+(b.dia||'-')+'mm</div>'
      + '<div class="row">中线来源：'+(b.src==='wireframe'?'线框':'实体反推')+'</div>'
      + '<div class="row">端点节点：'+b.node0+' — '+b.node1+'</div>'
      + '<div class="row">线段：'+b.segs.join(', ')+'</div>';
  }}
  panel.innerHTML = h; panel.style.display='block';
}});
addEventListener('resize', function(){{
  camera.aspect = innerWidth/innerHeight; camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight);
}});
(function loop(){{ requestAnimationFrame(loop); controls.update(); renderer.render(scene, camera); }})();
</script></body></html>
"""
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    log(f"[HTML] 输出 {out_path} ({os.path.getsize(out_path)/1024:.0f} KB)")


def build_excel(topology, entities, relations, out_path, log, reference=None):
    """生成 Excel 报表（汇总 / 分支 / 节点 / 线段 / 走线 / 接触关系 / 实体清单）。"""
    from collections import Counter
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    wb = Workbook()
    bold = Font(bold=True)
    head_fill = PatternFill("solid", fgColor="DDEBF7")

    def sheet(title, headers, rows):
        ws = wb.create_sheet(title)
        ws.append(headers)
        for c in ws[1]:
            c.font = bold
            c.fill = head_fill
        for r in rows:
            ws.append(r)
        widths = [max(len(str(v)) if v is not None else 0 for v in col) + 2
                  for col in zip(*([headers] + rows))] if rows else [12] * len(headers)
        for i, w in enumerate(widths, 1):
            ws.column_dimensions[chr(64 + i) if i <= 26 else "Z"].width = min(w, 60)
        return ws

    nodes = topology["nodes"]
    ntype = Counter(n["type"] for n in nodes)
    branches = topology["branches"]
    ecount = entities["counts"]

    # 汇总
    ws = wb.active
    ws.title = "汇总"
    summary = [
        ("文件", topology["file"]),
        ("生成时间", entities.get("generated", "")),
        ("STEP 具名 BREP 实体", ecount["brep"]),
        ("TransferOne 失败", ecount["transfer_fail"]),
        ("管状实体（恰好2平面端面）", ecount["tube_solids"]),
        ("中线反推失败（进设备候选）", ecount["spine_failed"]),
        ("中线重叠去重", ecount["deduped"]),
        ("分支", len(branches)),
        ("设备候选（非管实体）", ecount["devices"]),
        ("节点总数", len(nodes)),
        ("  连接器节点", ntype.get("connector", 0)),
        ("  卡扣节点", ntype.get("clamp", 0)),
        ("  分支点", ntype.get("fork", 0)),
        ("  接头点", ntype.get("joint", 0)),
        ("  悬空端", ntype.get("hanging", 0)),
        ("线段", len(topology["segments"])),
        ("走线", len(topology["runs"])),
        ("搭接 taps", len(relations["taps"])),
        ("端-端 end_ends", len(relations["end_ends"])),
        ("端部接触 terminals", len(relations["terminals"])),
        ("中部站位 tie_stations", len(relations["tie_stations"])),
    ]
    if reference:
        summary.append(("--- 与参考值对比 ---", ""))
        for k, ref in reference.items():
            got = {"管": len(branches), "节点": len(nodes),
                   "连接器": ntype.get("connector", 0),
                   "卡扣": ntype.get("clamp", 0),
                   "分支点": ntype.get("fork", 0),
                   "接头": ntype.get("joint", 0),
                   "悬空": ntype.get("hanging", 0)}.get(k)
            summary.append((f"参考{k}（参考 {ref} / 本次 {got} / 差 {got-ref if got is not None else ''}）", ""))
    for row in summary:
        ws.append(list(row))
    ws["A1"].font = bold
    ws.column_dimensions["A"].width = 42
    ws.column_dimensions["B"].width = 24

    # 分支
    bmap = {b["key"]: b for b in branches}
    sheet("分支", ["分支", "真名", "S号", "长度mm", "直径mm", "中线来源",
                   "端点节点0", "端点节点1", "线段"],
          [[b["key"], b["occ"],
            next((e["tag"] for e in entities["branches"] if e["key"] == b["key"]), ""),
            b["length"], b["dia"], "线框" if b["src"] == "wireframe" else "实体反推",
            b["node0"], b["node1"], ",".join(b["segs"])] for b in branches])

    # 节点
    sheet("节点", ["节点", "类型", "真名", "X", "Y", "Z", "度数", "相连线段"],
          [[nd["code"], nd["type"], nd["name_3d"], nd["xyz"][0], nd["xyz"][1],
            nd["xyz"][2], nd["degree"], ",".join(nd["segments"])] for nd in nodes])

    # 线段
    sheet("线段", ["线段", "分支", "起点节点", "终点节点", "长度mm", "直径mm", "所属走线"],
          [[s["seg"], s["branch"], s["na"], s["nb"], s["length"], s["dia"], s["run"]]
           for s in topology["segments"]])

    # 走线
    sheet("走线", ["走线", "起点节点", "终点节点", "线段数", "总长mm", "线段"],
          [[r["run"], r["na"], r["nb"], len(r["segs"]), r["length"], ",".join(r["segs"])]
           for r in topology["runs"]])

    # 接触关系
    erows = []
    for t in relations["terminals"]:
        b = branches[t["branch"]]
        erows.append(["端部接触", b["key"], f"端{t['end']}",
                      t["tag"], "", round(t["dist"], 2)])
    for t in relations["tie_stations"]:
        b = branches[t["branch"]]
        erows.append(["中部固定", b["key"], f"站位{t['s']:.1f}mm",
                      t["tag"], "", round(t["dev"], 2)])
    for t in relations["taps"]:
        erows.append(["搭接", branches[t["main"]]["key"], f"站位{t['s']:.1f}mm",
                      branches[t["tap"]]["key"], f"端{t['tap_end']}",
                      round(t["dev"], 2)])
    for (i, ei, j, ej) in relations["end_ends"]:
        erows.append(["端-端", branches[i]["key"], f"端{ei}",
                      branches[j]["key"], f"端{ej}", ""])
    sheet("接触关系", ["类型", "分支/实体A", "端/站位", "分支/实体B", "端", "距离/偏差mm"], erows)

    # 实体清单
    erows = []
    for b in entities["branches"]:
        erows.append([b["tag"], b["name"], "管", round(b["vol"], 1) if b.get("vol") else "",
                      ",".join(f"{x:.1f}" for x in b["bbox_c"][:3]), b["step_id"] or ""])
    for d in entities["devices"]:
        erows.append([d["tag"], d["name"], "设备",
                      round(d["vol"], 1) if d.get("vol") else "",
                      ",".join(f"{x:.1f}" for x in d["bbox_c"][:3]), d["step_id"] or ""])
    sheet("实体清单", ["S号", "真名", "类型", "体积mm³", "包围盒中心", "STEP #id"], erows)

    wb.save(out_path)
    log(f"[Excel] 输出 {out_path} ({os.path.getsize(out_path)/1024:.0f} KB)")
