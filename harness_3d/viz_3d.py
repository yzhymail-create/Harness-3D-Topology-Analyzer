#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成可交互的 3D 拓扑视图 (Three.js + HTML) - 本地版"""
import json, os, sys, shutil

def make_interactive_3d(d, html_path):
    """读取 topology.json 生成可交互的 HTML 3D 视图."""
    branches = d["branches"]
    nodes = d["nodes"]
    segments = d["segments"]
    runs = d["runs"]
    
    # 计算包围盒
    all_pts = []
    for b in branches:
        all_pts.extend(b["polyline"])
    all_pts = [[float(x) for x in p] for p in all_pts]
    
    min_xyz = [min(p[i] for p in all_pts) for i in range(3)]
    max_xyz = [max(p[i] for p in all_pts) for i in range(3)]
    center = [(min_xyz[i] + max_xyz[i]) / 2 for i in range(3)]
    size = max(max_xyz[i] - min_xyz[i] for i in range(3))
    
    # 节点类型颜色
    node_colors = {
        "connector": "#e74c3c",
        "clamp": "#3498db",
        "tie": "#95a5a6",
        "fork": "#f39c12",
        "hanging": "#9b59b6",
        "joint": "#1abc9c"
    }
    
    # 走线颜色
    run_colors = [
        "#e74c3c", "#3498db", "#2ecc71", "#f39c12", "#9b59b6",
        "#1abc9c", "#e67e22", "#34495e", "#16a085", "#c0392b",
        "#2980b9", "#27ae60", "#f1c40f", "#8e44ad", "#d35400"
    ]
    
    # 类型中文名
    type_names = {
        "connector": "连接器", "clamp": "固定卡扣", "tie": "扎带",
        "fork": "分支点", "hanging": "悬空端", "joint": "连接点"
    }
    
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{d['file']} 线束拓扑 3D 视图</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: 'Microsoft YaHei', 'Segoe UI', sans-serif; overflow: hidden; background: #0a0a0a; }}
#canvas-container {{ width: 100vw; height: 100vh; position: relative; }}
#info-panel {{
    position: absolute; top: 20px; right: 20px; width: 340px;
    background: rgba(20,20,20,0.95); color: #fff; padding: 20px;
    border-radius: 10px; font-size: 14px; max-height: 85vh; overflow-y: auto;
    display: none; border: 1px solid #333; box-shadow: 0 4px 20px rgba(0,0,0,0.5);
}}
#info-panel h3 {{ margin-bottom: 15px; color: #3498db; border-bottom: 2px solid #3498db; padding-bottom: 10px; font-size: 16px; }}
#info-panel .row {{ margin: 10px 0; display: flex; justify-content: space-between; align-items: center; padding: 6px 0; border-bottom: 1px solid #222; }}
#info-panel .label {{ color: #888; font-size: 13px; }}
#info-panel .value {{ color: #fff; font-weight: bold; font-size: 13px; text-align: right; max-width: 60%; word-break: break-all; }}
#legend {{
    position: absolute; bottom: 20px; left: 20px;
    background: rgba(20,20,20,0.95); color: #fff; padding: 18px;
    border-radius: 10px; font-size: 13px; border: 1px solid #333;
}}
#legend h4 {{ margin-bottom: 12px; color: #3498db; font-size: 14px; }}
#legend .item {{ margin: 8px 0; display: flex; align-items: center; }}
#legend .dot {{ width: 14px; height: 14px; border-radius: 50%; margin-right: 10px; border: 2px solid rgba(255,255,255,0.3); }}
#controls {{
    position: absolute; top: 20px; left: 20px;
    background: rgba(20,20,20,0.95); color: #fff; padding: 18px;
    border-radius: 10px; font-size: 13px; border: 1px solid #333;
}}
#controls h4 {{ margin-bottom: 12px; color: #3498db; font-size: 14px; }}
#controls .btn {{
    display: block; width: 100%; margin: 8px 0; padding: 10px;
    background: #3498db; color: #fff; border: none; border-radius: 6px;
    cursor: pointer; font-size: 13px; transition: background 0.2s;
}}
#controls .btn:hover {{ background: #2980b9; }}
#stats {{
    position: absolute; top: 20px; left: 50%; transform: translateX(-50%);
    background: rgba(20,20,20,0.95); color: #fff; padding: 14px 28px;
    border-radius: 10px; font-size: 14px; border: 1px solid #333;
    display: flex; gap: 24px;
}}
#stats span {{ display: flex; align-items: center; gap: 6px; }}
#stats .num {{ color: #3498db; font-weight: bold; font-size: 20px; }}
#hint {{
    position: absolute; bottom: 20px; right: 20px;
    background: rgba(20,20,20,0.9); color: #888; padding: 12px 18px;
    border-radius: 8px; font-size: 12px; border: 1px solid #333;
}}
</style>
</head>
<body>
<div id="canvas-container"></div>

<div id="stats">
    <span>分支 <span class="num">{len(branches)}</span></span>
    <span>节点 <span class="num">{len(nodes)}</span></span>
    <span>线段 <span class="num">{len(segments)}</span></span>
    <span>走线 <span class="num">{len(runs)}</span></span>
</div>

<div id="controls">
    <h4>视图控制</h4>
    <button class="btn" onclick="resetCamera()">🔄 重置视角</button>
    <button class="btn" onclick="toggleLabels()">🏷️ 切换标签</button>
    <button class="btn" onclick="focusSelected()"> 聚焦选中</button>
</div>

<div id="legend">
    <h4>图例</h4>
    <div class="item"><div class="dot" style="background:#e74c3c"></div>连接器</div>
    <div class="item"><div class="dot" style="background:#3498db"></div>固定卡扣</div>
    <div class="item"><div class="dot" style="background:#f39c12"></div>分支点</div>
    <div class="item"><div class="dot" style="background:#9b59b6"></div>悬空端</div>
    <div class="item"><div class="dot" style="background:#1abc9c"></div>连接点</div>
    <div class="item"><div class="dot" style="background:#95a5a6"></div>扎带</div>
</div>

<div id="hint">
     左键旋转 | 滚轮缩放 | 右键平移 | 点击节点查看详情
</div>

<div id="info-panel">
    <h3 id="info-title">节点详情</h3>
    <div id="info-content"></div>
</div>

<script src="threejs/three.min.js"></script>
<script src="threejs/OrbitControls.js"></script>

<script>
const branches = {json.dumps(branches)};
const nodes = {json.dumps(nodes)};
const segments = {json.dumps(segments)};
const runs = {json.dumps(runs)};
const nodeColors = {json.dumps(node_colors)};
const runColors = {json.dumps(run_colors)};
const typeNames = {json.dumps(type_names)};
const center = {json.dumps(center)};
const size = {size};

let scene, camera, renderer, controls;
let nodeMeshes = [], branchLines = [], labelSprites = [];
let selectedNode = null, showLabels = true;

init();
animate();

function init() {{
    const container = document.getElementById('canvas-container');
    
    scene = new THREE.Scene();
    scene.background = new THREE.Color(0x0a0a0a);
    scene.fog = new THREE.Fog(0x0a0a0a, size * 2, size * 5);
    
    camera = new THREE.PerspectiveCamera(60, window.innerWidth / window.innerHeight, 0.1, size * 10);
    camera.position.set(center[0] + size * 0.9, center[1] + size * 0.7, center[2] + size * 1.3);
    
    renderer = new THREE.WebGLRenderer({{ antialias: true, alpha: false }});
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    container.appendChild(renderer.domElement);
    
    controls = new THREE.OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.target.set(center[0], center[1], center[2]);
    controls.update();
    
    // 灯光
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.7);
    scene.add(ambientLight);
    
    const dirLight1 = new THREE.DirectionalLight(0xffffff, 0.8);
    dirLight1.position.set(100, 200, 100);
    scene.add(dirLight1);
    
    const dirLight2 = new THREE.DirectionalLight(0x8888ff, 0.4);
    dirLight2.position.set(-100, -50, -100);
    scene.add(dirLight2);
    
    // 网格
    const gridHelper = new THREE.GridHelper(size * 2.5, 25, 0x333333, 0x1a1a1a);
    gridHelper.position.set(center[0], center[1] - size * 0.35, center[2]);
    scene.add(gridHelper);
    
    // 坐标轴
    const axesHelper = new THREE.AxesHelper(size * 0.5);
    axesHelper.position.set(center[0] - size * 0.5, center[1] - size * 0.35, center[2] - size * 0.5);
    scene.add(axesHelper);
    
    drawBranches();
    drawNodes();
    
    renderer.domElement.addEventListener('click', onMouseClick, false);
    window.addEventListener('resize', onWindowResize, false);
}}

function drawBranches() {{
    branches.forEach((b, i) => {{
        const pts = b.polyline.map(p => new THREE.Vector3(p[0], p[1], p[2]));
        if (pts.length < 2) return;
        
        const geometry = new THREE.BufferGeometry().setFromPoints(pts);
        const color = runColors[i % runColors.length];
        const material = new THREE.LineBasicMaterial({{ 
            color: color, 
            linewidth: 2,
            transparent: true,
            opacity: 0.85
        }});
        const line = new THREE.Line(geometry, material);
        line.userData = {{ type: 'branch', data: b, color: color }};
        scene.add(line);
        branchLines.push(line);
        
        // 添加管状效果（用粗线）
        const curve = new THREE.CatmullRomCurve3(pts);
        const tubeGeo = new THREE.TubeGeometry(
            curve,
            Math.max(20, pts.length),
            b.dia ? b.dia / 2 * 0.3 : 1.5,
            8,
            false
        );
        const tubeMat = new THREE.MeshPhongMaterial({{
            color: color,
            transparent: true,
            opacity: 0.3,
            shininess: 100
        }});
        const tube = new THREE.Mesh(tubeGeo, tubeMat);
        tube.userData = {{ type: 'branch', data: b }};
        scene.add(tube);
    }});
}}

function drawNodes() {{
    nodes.forEach((nd, i) => {{
        const pos = new THREE.Vector3(nd.xyz[0], nd.xyz[1], nd.xyz[2]);
        const color = nodeColors[nd.type] || '#888888';
        const radius = nd.type === 'fork' ? 4 : (nd.type === 'connector' ? 3.5 : 2.5);
        
        const geometry = new THREE.SphereGeometry(radius, 20, 20);
        const material = new THREE.MeshPhongMaterial({{ 
            color: color, 
            emissive: color, 
            emissiveIntensity: 0.4,
            shininess: 100
        }});
        const mesh = new THREE.Mesh(geometry, material);
        mesh.position.copy(pos);
        mesh.userData = {{ type: 'node', data: nd }};
        scene.add(mesh);
        nodeMeshes.push(mesh);
        
        // 标签（用 Sprite）
        const labelCanvas = document.createElement('canvas');
        const ctx = labelCanvas.getContext('2d');
        labelCanvas.width = 256;
        labelCanvas.height = 64;
        ctx.fillStyle = 'rgba(0,0,0,0.7)';
        ctx.fillRect(4, 4, 248, 56);
        ctx.fillStyle = color;
        ctx.font = 'bold 28px Microsoft YaHei';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(nd.code, 128, 32);
        
        const texture = new THREE.CanvasTexture(labelCanvas);
        const spriteMat = new THREE.SpriteMaterial({{ 
            map: texture, 
            transparent: true,
            depthTest: false
        }});
        const sprite = new THREE.Sprite(spriteMat);
        sprite.position.copy(pos);
        sprite.position.y += radius + 8;
        sprite.scale.set(20, 5, 1);
        scene.add(sprite);
        labelSprites.push(sprite);
    }});
}}

function onMouseClick(event) {{
    const mouse = new THREE.Vector2();
    mouse.x = (event.clientX / window.innerWidth) * 2 - 1;
    mouse.y = -(event.clientY / window.innerHeight) * 2 + 1;
    
    const raycaster = new THREE.Raycaster();
    raycaster.setFromCamera(mouse, camera);
    
    const intersects = raycaster.intersectObjects(nodeMeshes);
    if (intersects.length > 0) {{
        const mesh = intersects[0].object;
        selectNode(mesh.userData.data);
        
        // 高亮选中
        nodeMeshes.forEach(m => {{
            m.material.emissiveIntensity = 0.4;
        }});
        mesh.material.emissiveIntensity = 1.0;
    }} else {{
        hideInfo();
        nodeMeshes.forEach(m => {{
            m.material.emissiveIntensity = 0.4;
        }});
    }}
}}

function selectNode(nd) {{
    selectedNode = nd;
    const panel = document.getElementById('info-panel');
    const title = document.getElementById('info-title');
    const content = document.getElementById('info-content');
    
    title.textContent = `节点 ${{nd.code}}`;
    
    let html = `
        <div class="row"><span class="label">类型</span><span class="value" style="color:${{nodeColors[nd.type]}}">${{typeNames[nd.type] || nd.type}}</span></div>
        <div class="row"><span class="label">坐标</span><span class="value">(${{nd.xyz[0].toFixed(1)}}, ${{nd.xyz[1].toFixed(1)}}, ${{nd.xyz[2].toFixed(1)}})</span></div>
        <div class="row"><span class="label">度数</span><span class="value">${{nd.degree}}</span></div>
        <div class="row"><span class="label">相连线段</span><span class="value">${{nd.segments.join(', ') || '无'}}</span></div>
    `;
    
    if (nd.name_3d) {{
        html += `<div class="row"><span class="label">3D 名称</span><span class="value">${{nd.name_3d}}</span></div>`;
    }}
    
    if (nd.entity) {{
        html += `<div class="row"><span class="label">实体</span><span class="value">${{nd.entity}}</span></div>`;
    }}
    
    if (nd.nearest) {{
        html += `<div class="row"><span class="label">最近零件</span><span class="value">${{nd.nearest.proto}} (${{nd.nearest.dist}}mm)</span></div>`;
    }}
    
    content.innerHTML = html;
    panel.style.display = 'block';
}}

function hideInfo() {{
    document.getElementById('info-panel').style.display = 'none';
    selectedNode = null;
}}

function resetCamera() {{
    camera.position.set(center[0] + size * 0.9, center[1] + size * 0.7, center[2] + size * 1.3);
    controls.target.set(center[0], center[1], center[2]);
    controls.update();
}}

function toggleLabels() {{
    showLabels = !showLabels;
    labelSprites.forEach(s => s.visible = showLabels);
}}

function focusSelected() {{
    if (selectedNode) {{
        const pos = new THREE.Vector3(selectedNode.xyz[0], selectedNode.xyz[1], selectedNode.xyz[2]);
        controls.target.copy(pos);
        const offset = new THREE.Vector3(size * 0.15, size * 0.15, size * 0.15);
        camera.position.copy(pos).add(offset);
        controls.update();
    }}
}}

function onWindowResize() {{
    camera.aspect = window.innerWidth / window.innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(window.innerWidth, window.innerHeight);
}}

function animate() {{
    requestAnimationFrame(animate);
    controls.update();
    renderer.render(scene, camera);
}}

// 暴露到全局
window.resetCamera = resetCamera;
window.toggleLabels = toggleLabels;
window.focusSelected = focusSelected;
</script>
</body>
</html>"""
    
    # 确保 threejs 目录存在
    html_dir = os.path.dirname(html_path)
    threejs_dir = os.path.join(html_dir, 'threejs')
    os.makedirs(threejs_dir, exist_ok=True)
    
    # 复制 Three.js 文件到输出目录
    src_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'threejs')
    if os.path.exists(src_dir):
        for f in ['three.min.js', 'OrbitControls.js']:
            src = os.path.join(src_dir, f)
            dst = os.path.join(threejs_dir, f)
            if os.path.exists(src) and not os.path.exists(dst):
                shutil.copy2(src, dst)
    
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html)


if __name__ == "__main__":
    json_path = sys.argv[1] if len(sys.argv) > 1 else "topology.json"
    html_path = json_path.replace('.json', '_3d.html')
    d = json.load(open(json_path, encoding='utf-8'))
    make_interactive_3d(d, html_path)
    print(f"saved {html_path}")
