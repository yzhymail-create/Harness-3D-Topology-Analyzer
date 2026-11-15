# -*- coding: utf-8 -*-
"""把连接器/卡扣形状网格 + 通用弹窗逻辑注入 3D 拓扑 HTML。

通用规则（2026-11-15 18:09 用户定）：
- 只针对连接器和卡扣两种节点（n.type 为 connector 或 clamp）。
- meshes 目录里有以节点名命名的 JS 就展示，没有就默认不展示、不报错。
- 代码不写死任何节点名、节点编号、连接器名；匹配只按拓扑节点名 name_3d 查表。

用法: python inject_popup.py <floor.html> <meshes_dir> <output.html>
- meshes_dir 下每个 *.js 是 step_to_js.py 输出的 window.CONNECTOR_MESH = {...}，
  内部 name 必须等于拓扑节点名；注入时建成注册表 CONNECTOR_MESHES 按名查。
- 点击节点时：类型是连接器/卡扣且注册表里有同名网格 → 弹窗显示真实 3D 形状；
  否则不弹（并关闭已打开的窗口）。

弹窗行为：
- 常驻：鼠标移出不消失；点击弹窗之外任意处（主画布其他位置、页面空白处）才关闭；
  点弹窗内、点有网格的节点不关；× 按钮照常关闭。
- 切换到不同网格时复用 renderer/scene，dispose 旧 geometry 后重建并重新取景。
- 材质 DoubleSide（兜底：个别开壳面也能看见）。
"""
import sys, os, re, json, glob

floor_html = sys.argv[1]
meshes_dir = sys.argv[2]
out_html = sys.argv[3]

with open(floor_html, "r", encoding="utf-8") as f:
    html = f.read()

# 扫描 meshes 目录，建成注册表（key = 每个文件内部 data.name）
registry = {}
for js_path in sorted(glob.glob(os.path.join(meshes_dir, "*.js"))):
    with open(js_path, "r", encoding="utf-8") as f:
        content = f.read()
    m = re.search(r"window\.CONNECTOR_MESH = (\{.*\});\s*$", content, re.DOTALL)
    assert m, f"{js_path} 格式不对（应为 window.CONNECTOR_MESH = {{...}};）"
    data = json.loads(m.group(1))
    name = data.get("name")
    assert name, f"{js_path} 缺少 name 字段"
    if name in registry:
        print(f"警告：名字 {name} 重复，{js_path} 覆盖之前的文件")
    registry[name] = data
    print(f"网格：{name}（{os.path.basename(js_path)}，"
          f"{len(data['indices'])//3} 三角形）")
if not registry:
    print(f"警告：{meshes_dir} 下没有 *.js，弹窗注册表为空（点击任何节点都不弹窗）")

# 1. 注入弹窗 CSS（在 #panel 样式后）
popup_css = """
#meshPopup{position:fixed;right:12px;bottom:12px;width:360px;background:rgba(0,0,0,.85);
border:1px solid #555;border-radius:10px;color:#fff;z-index:10;display:none;overflow:hidden}
#meshPopup .mp-title{padding:8px 12px;font-size:14px;border-bottom:1px solid #444;display:flex;justify-content:space-between;align-items:center}
#meshPopup .mp-title b{font-weight:bold}
#meshPopup .mp-close{cursor:pointer;color:#aaa;font-size:18px;line-height:1}
#meshPopup .mp-close:hover{color:#fff}
#meshPopup canvas{display:block;width:100%;height:260px}
#meshPopup .mp-hint{padding:6px 12px;font-size:11px;color:#999;border-top:1px solid #333}
"""
anchor_css = "#panel .row{margin:3px 0;color:#ddd;word-break:break-all}"
assert anchor_css in html, "找不到 #panel CSS 锚点"
html = html.replace(anchor_css, anchor_css + popup_css, 1)

# 2. 注入弹窗 div（在 panel div 后）
popup_div = """
<div id="meshPopup"><div class="mp-title"><b id="mpName">连接器</b><span class="mp-close" onclick="hideMeshPopup()">×</span></div><div id="mpCanvas"></div><div class="mp-hint">拖动旋转 · 滚轮缩放 · 点击窗口外任意处关闭</div></div>
"""
anchor_div = '<div id="panel"></div>'
assert anchor_div in html, "找不到 panel div 锚点"
html = html.replace(anchor_div, anchor_div + popup_div, 1)

# 3. 注入网格注册表（在 var DATA 之前）
registry_js = "var CONNECTOR_MESHES = " + json.dumps(registry, ensure_ascii=False) + ";\n"
anchor_data = "var DATA = "
assert anchor_data in html, "找不到 DATA 锚点"
html = html.replace(anchor_data, registry_js + anchor_data, 1)

# 4. 注入弹窗逻辑（在 click 处理器之前）
popup_js = """
// ---- 连接器/卡扣形状弹窗（通用按名匹配） ----
var mpScene=null, mpCamera=null, mpRenderer=null, mpControls=null, mpMesh=null, mpCurrentName=null;
function showMeshPopup(name, mesh){
  var pop = document.getElementById('meshPopup');
  document.getElementById('mpName').textContent = name;
  pop.style.display='block';
  if (!mpRenderer){
    mpScene = new THREE.Scene();
    mpScene.background = new THREE.Color(0x1a1a1a);
    mpCamera = new THREE.PerspectiveCamera(45, 360/260, 0.1, 10000);
    mpRenderer = new THREE.WebGLRenderer({antialias:true});
    mpRenderer.setSize(360, 260);
    document.getElementById('mpCanvas').appendChild(mpRenderer.domElement);
    mpControls = new THREE.OrbitControls(mpCamera, mpRenderer.domElement);
    mpScene.add(new THREE.AmbientLight(0xffffff, 0.7));
    var dl2 = new THREE.DirectionalLight(0xffffff, 0.9);
    dl2.position.set(1,1,1); mpScene.add(dl2);
    (function mpLoop(){ requestAnimationFrame(mpLoop); if(pop.style.display==='block'){ mpControls.update(); mpRenderer.render(mpScene, mpCamera); } })();
  }
  if (mpCurrentName !== name){
    if (mpMesh){ mpScene.remove(mpMesh); mpMesh.geometry.dispose(); mpMesh.material.dispose(); }
    var geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.Float32BufferAttribute(mesh.positions, 3));
    geo.setIndex(mesh.indices);
    geo.computeVertexNormals();
    var mat = new THREE.MeshStandardMaterial({color:0x4a90d9, roughness:0.5, metalness:0.3, side:THREE.DoubleSide});
    mpMesh = new THREE.Mesh(geo, mat);
    mpScene.add(mpMesh);
    var bb = new THREE.Box3().setFromObject(mpMesh);
    var c = bb.getCenter(new THREE.Vector3());
    var s = bb.getSize(new THREE.Vector3()).length();
    mpControls.target.copy(c);
    mpCamera.position.set(c.x + s*0.7, c.y - s*0.7, c.z + s*0.7);
    mpCamera.near = s/1000; mpCamera.far = s*10; mpCamera.updateProjectionMatrix();
    mpCurrentName = name;
  }
}
function hideMeshPopup(){
  document.getElementById('meshPopup').style.display='none';
}
// 点击弹窗之外关闭：主画布上的点击由画布处理器管（点有网格的节点打开、点别处关闭）；
// 页面其他区域（信息面板、图例、空白处）的点击走这里。
document.addEventListener('click', function(ev){
  var pop = document.getElementById('meshPopup');
  if (pop.style.display !== 'block') return;
  if (pop.contains(ev.target)) return;
  if (ev.target === renderer.domElement) return;
  hideMeshPopup();
});
"""
anchor_click = "renderer.domElement.addEventListener('click'"
assert anchor_click in html, "找不到 click 锚点"
html = html.replace(anchor_click, popup_js + anchor_click, 1)

# 5. 修改 click 处理器：连接器/卡扣节点且注册表里有同名网格时弹形状窗口，否则不弹
old_node_block = """  if (u.kind === 'node') {
    var n = u.n;
    h = '<h4>'+n.code+'（'+n.type+'）</h4>'"""
new_node_block = """  if (u.kind === 'node') {
    var n = u.n;
    if ((n.type === 'connector' || n.type === 'clamp') && n.name && CONNECTOR_MESHES[n.name]) { showMeshPopup(n.name, CONNECTOR_MESHES[n.name]); }
    else { hideMeshPopup(); }
    h = '<h4>'+n.code+'（'+n.type+'）</h4>'"""
assert old_node_block in html, "找不到 node click 锚点"
html = html.replace(old_node_block, new_node_block, 1)

# 6. 主画布点空处 / 点分支时也关闭弹窗
old_nohit = "if (!hits.length) { panel.style.display='none'; return; }"
new_nohit = "if (!hits.length) { panel.style.display='none'; hideMeshPopup(); return; }"
assert old_nohit in html, "找不到 no-hit 锚点"
html = html.replace(old_nohit, new_nohit, 1)

old_branch = """  } else {
    var b = u.b;"""
new_branch = """  } else {
    hideMeshPopup();
    var b = u.b;"""
assert old_branch in html, "找不到 branch click 锚点"
html = html.replace(old_branch, new_branch, 1)

with open(out_html, "w", encoding="utf-8") as f:
    f.write(html)
print(f"输出: {out_html} ({os.path.getsize(out_html)/1024/1024:.1f} MB)")
print(f"注入完成：{len(registry)} 个网格注册表 + 通用弹窗逻辑")
