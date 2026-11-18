#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""线束拓扑 3D 可视化. make_plot(result, png_path)"""
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection


def ascii_label(s):
    return s.replace("测试", "T")


def make_plot(d, png_path):
    fig = plt.figure(figsize=(14, 10))
    ax = fig.add_subplot(111, projection="3d")
    cmap = plt.cm.tab10
    for i, b in enumerate(d["branches"]):
        p = np.array(b["polyline"])
        key = b.get("key", b["proto"])
        lab = key.replace("Multi-branchable", "B")
        if "#S" in lab and len(lab) > 16:
            lab = "S" + lab.split("#S")[-1]
        ax.plot(p[:, 0], p[:, 1], p[:, 2], color=cmap(i % 10), lw=2.5,
                label=f'{lab} {b["length"]}mm')
        ax.text(p[len(p)//2, 0], p[len(p)//2, 1], p[len(p)//2, 2],
                lab, fontsize=8, color=cmap(i % 10))
    for nd in d["nodes"]:
        x, y, z = nd["xyz"]
        lab = nd.get("code") or f'N{nd["id"]}'
        if nd["degree"] >= 2:
            ax.scatter([x], [y], [z], s=90, c="red", marker="D", depthshade=False, zorder=5)
            ax.text(x, y, z, f'  {lab}', fontsize=9, color="red", weight="bold")
        else:
            ax.scatter([x], [y], [z], s=45, c="black", marker="o", depthshade=False, zorder=5)
            ax.text(x, y, z, f'  {lab}', fontsize=8, color="black")
    for c in d["connectors"]:
        cx, cy, cz = c["center"]; dx, dy, dz = c["bbox"]
        x0, x1 = cx-dx/2, cx+dx/2; y0, y1 = cy-dy/2, cy+dy/2; z0, z1 = cz-dz/2, cz+dz/2
        verts = [[(x0,y0,z0),(x1,y0,z0),(x1,y1,z0),(x0,y1,z0)],
                 [(x0,y0,z1),(x1,y0,z1),(x1,y1,z1),(x0,y1,z1)],
                 [(x0,y0,z0),(x0,y0,z1),(x0,y1,z1),(x0,y1,z0)],
                 [(x1,y0,z0),(x1,y0,z1),(x1,y1,z1),(x1,y1,z0)],
                 [(x0,y0,z0),(x1,y0,z0),(x1,y0,z1),(x0,y0,z1)],
                 [(x0,y1,z0),(x1,y1,z0),(x1,y1,z1),(x0,y1,z1)]]
        ax.add_collection3d(Poly3DCollection(verts, facecolors=(0.6,0.6,0.6,0.25),
                                            edgecolors=(0.4,0.4,0.4,0.8), linewidths=0.6))
        ax.text(cx, cy, z1, f'{ascii_label(c["occ"].split("/")[-1])}\n({ascii_label(c["proto"])})',
                fontsize=7, color="dimgray", ha="center")
    ax.set_xlabel("X mm"); ax.set_ylabel("Y mm"); ax.set_zlabel("Z mm")
    ax.set_title(f'{d["file"]} harness topology  (red diamond=junction, black dot=terminal)')
    ax.legend(loc="upper left", fontsize=8)
    allp = np.vstack([np.array(b["polyline"]) for b in d["branches"]])
    mx = (allp.max(0)-allp.min(0)).max()/2; mid = (allp.max(0)+allp.min(0))/2
    ax.set_xlim(mid[0]-mx, mid[0]+mx); ax.set_ylim(mid[1]-mx, mid[1]+mx); ax.set_zlim(mid[2]-mx, mid[2]+mx)
    ax.view_init(elev=18, azim=-65)
    plt.tight_layout()
    plt.savefig(png_path, dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    import json, sys
    d = json.load(open(sys.argv[1] if len(sys.argv) > 1 else "topology.json"))
    make_plot(d, "topology_3d.png")
    print("saved topology_3d.png")
