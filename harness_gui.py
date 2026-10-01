#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""线束3D拓扑分析 - 一键启动入口
双击运行 → 选择 STEP 文件 → 自动分析 + 生成报告 + 3D可视化
"""
import os, sys, threading, traceback

# 定位 harness_3d 包目录
APP_DIR = os.path.dirname(os.path.abspath(__file__))
HARNESS_DIR = os.path.join(APP_DIR, "harness_3d")
sys.path.insert(0, HARNESS_DIR)

import tkinter as tk
from tkinter import filedialog, scrolledtext

# ─── 主窗口 ───────────────────────────────────────────────

root = tk.Tk()
root.title("线束3D拓扑分析工具")
root.geometry("720x520")
root.resizable(True, True)
root.configure(bg="#f0f0f0")

# 居中显示
root.update_idletasks()
sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
x = (sw - 720) // 2
y = (sh - 520) // 2
root.geometry(f"720x520+{x}+{y}")

# ─── 顶部操作区 ───────────────────────────────────────────

top_frame = tk.Frame(root, bg="#f0f0f0", padx=12, pady=10)
top_frame.pack(fill=tk.X)

tk.Label(top_frame, text="STEP 文件:", font=("微软雅黑", 10), bg="#f0f0f0").pack(side=tk.LEFT)

file_var = tk.StringVar(value="")
file_entry = tk.Entry(top_frame, textvariable=file_var, font=("Consolas", 9),
                      state="readonly", readonlybackground="white", relief=tk.SOLID)
file_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 8))

def choose_and_run():
    path = filedialog.askopenfilename(
        title="选择 STEP 文件",
        filetypes=[("STEP 文件", "*.stp *.step *.STEP *.STP"), ("所有文件", "*.*")],
        initialdir=os.path.dirname(APP_DIR)
    )
    if path:
        file_var.set(path)
        run_analysis()

btn_run = tk.Button(top_frame, text="选择文件并分析", font=("微软雅黑", 10, "bold"),
                    bg="#4472C4", fg="white", activebackground="#3060B0",
                    relief=tk.FLAT, padx=16, pady=4, command=choose_and_run)
btn_run.pack(side=tk.RIGHT)

# ─── 容差设置 ─────────────────────────────────────────────

param_frame = tk.Frame(root, bg="#f0f0f0", padx=12)
param_frame.pack(fill=tk.X)

tk.Label(param_frame, text="节点容差(mm):", font=("微软雅黑", 9), bg="#f0f0f0").pack(side=tk.LEFT)
tol_var = tk.StringVar(value="3.0")
tol_spin = tk.Spinbox(param_frame, from_=0.5, to=20.0, increment=0.5,
                      textvariable=tol_var, width=6, font=("Consolas", 10))
tol_spin.pack(side=tk.LEFT, padx=(6, 20))

force_var = tk.BooleanVar(value=False)
tk.Checkbutton(param_frame, text="强制实体反推(不用线框)", variable=force_var,
               font=("微软雅黑", 9), bg="#f0f0f0").pack(side=tk.LEFT)

# ─── 日志输出区 ───────────────────────────────────────────

log_frame = tk.Frame(root, bg="#f0f0f0", padx=12, pady=6)
log_frame.pack(fill=tk.BOTH, expand=True)

log_text = scrolledtext.ScrolledText(log_frame, font=("Consolas", 9),
                                      bg="#1e1e1e", fg="#d4d4d4",
                                      insertbackground="white",
                                      relief=tk.FLAT, wrap=tk.WORD)
log_text.pack(fill=tk.BOTH, expand=True)

# 日志颜色标签
log_text.tag_config("info", foreground="#d4d4d4")
log_text.tag_config("ok", foreground="#6a9955")
log_text.tag_config("warn", foreground="#ce9178")
log_text.tag_config("err", foreground="#f44747")
log_text.tag_config("title", foreground="#569cd6", font=("Consolas", 10, "bold"))

def log(msg, tag="info"):
    log_text.insert(tk.END, msg + "\n", tag)
    log_text.see(tk.END)
    log_text.update_idletasks()

# ─── 底部状态栏 ───────────────────────────────────────────

status_var = tk.StringVar(value="就绪 — 请选择 STEP 文件开始分析")
status_bar = tk.Label(root, textvariable=status_var, font=("微软雅黑", 9),
                      bg="#e0e0e0", anchor=tk.W, padx=12)
status_bar.pack(fill=tk.X, side=tk.BOTTOM)

# ─── 分析逻辑 ─────────────────────────────────────────────

def run_analysis():
    step_path = file_var.get()
    if not step_path or not os.path.isfile(step_path):
        log("错误: 文件不存在", "err")
        return

    tol = float(tol_var.get())
    force = force_var.get()
    out_dir = os.path.dirname(step_path)
    basename = os.path.splitext(os.path.basename(step_path))[0]

    # 锁定按钮
    btn_run.config(state=tk.DISABLED, text="分析中...")
    status_var.set("正在分析...")

    log("=" * 56, "title")
    log(f"  线束3D拓扑分析", "title")
    log("=" * 56, "title")
    log(f"文件: {step_path}")
    log(f"容差: {tol}mm | 强制反推: {'是' if force else '否'}")
    log(f"输出: {out_dir}")
    log("")

    def worker():
        try:
            # 1) 拓扑分析
            log(">>> 第1步: 拓扑分析 (读取STEP + 接触分析)", "title")
            from harness_topology import analyze

            def progress(msg):
                # 区分日志级别
                if msg.startswith("警告"):
                    log(f"  {msg}", "warn")
                elif msg.startswith("接触") or msg.startswith("端部") or msg.startswith("搭接") \
                        or msg.startswith("接头") or msg.startswith("分类") or msg.startswith("共位") \
                        or msg.startswith("同体"):
                    log(f"  {msg}", "ok")
                else:
                    log(f"  {msg}")

            result = analyze(step_path, tol=tol, out_dir=out_dir,
                            progress=progress, force_reverse=force)
            n_b = len(result["branches"])
            n_s = len(result["segments"])
            n_n = len(result["nodes"])
            n_r = len(result["runs"])
            log("")
            log(f"  分支:{n_b}  线段:{n_s}  节点:{n_n}  走线:{n_r}", "ok")
            log(f"  -> topology.json 已保存", "ok")
            log("")

            # 2) Excel 报告
            log(">>> 第2步: 生成 Excel 报告", "title")
            from report_xlsx import make_report
            xlsx_path = os.path.join(out_dir, f"{basename}_拓扑报告.xlsx")
            make_report(result, xlsx_path)
            log(f"  -> {os.path.basename(xlsx_path)} 已保存", "ok")
            log("")

            # 3) 3D 可视化 (静态 PNG)
            log(">>> 第3步: 生成 3D 可视化", "title")
            from viz_topology import make_plot
            png_path = os.path.join(out_dir, f"{basename}_拓扑3D.png")
            make_plot(result, png_path)
            log(f"  -> {os.path.basename(png_path)} 已保存", "ok")
            log("")

            # 4) 交互式 3D 视图 (HTML)
            log(">>> 第4步: 生成交互式 3D 视图", "title")
            from viz_3d import make_interactive_3d
            html_path = os.path.join(out_dir, f"{basename}_3D视图.html")
            make_interactive_3d(result, html_path)
            log(f"  -> {os.path.basename(html_path)} 已保存", "ok")
            log("")

            # 完成
            log("=" * 56, "title")
            log("  分析完成!", "title")
            log("=" * 56, "title")
            log("")
            log(f"  输出文件:")
            log(f"    {basename}_拓扑报告.xlsx")
            log(f"    {basename}_拓扑3D.png")
            log(f"    {basename}_3D视图.html")
            log(f"    topology.json")

            def on_done():
                status_var.set(f"完成 — 输出在 {out_dir}")
                btn_run.config(state=tk.NORMAL, text="选择文件并分析")
                # 弹出完成提示
                from tkinter import messagebox
                if messagebox.askyesno("分析完成",
                    f"已生成:\n\n"
                    f"  • {basename}_拓扑报告.xlsx\n"
                    f"  • {basename}_拓扑3D.png\n"
                    f"  • {basename}_3D视图.html\n"
                    f"  • topology.json\n\n"
                    f"是否打开输出文件夹?"):
                    os.startfile(out_dir)

            root.after(0, on_done)

        except Exception as e:
            log(f"\n错误: {e}", "err")
            log(traceback.format_exc(), "err")
            def on_err():
                status_var.set("分析失败 — 请查看日志")
                btn_run.config(state=tk.NORMAL, text="选择文件并分析")
                from tkinter import messagebox
                messagebox.showerror("分析失败", f"错误:\n{e}")
            root.after(0, on_err)

    threading.Thread(target=worker, daemon=True).start()

btn_run.config(command=choose_and_run)

# ─── 启动 ─────────────────────────────────────────────────

log("欢迎使用线束3D拓扑分析工具", "title")
log("点击「选择文件并分析」按钮，选择 .stp / .step 文件即可开始。")
log("")

root.mainloop()
