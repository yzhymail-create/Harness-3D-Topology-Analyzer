#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""线束3D拓扑解析 - 图形界面.
双击(或通过启动bat)运行 -> 选择STEP文件 -> 表格生成在STEP所在文件夹.
"""
import os
import sys
import json
import queue
import threading
import traceback
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("线束3D拓扑解析")
        self.geometry("640x480")
        self.q = queue.Queue()
        self.result_paths = []

        tk.Label(self, text="从 CATIA 导出的 STEP(AP242) 解析线束拓扑",
                 font=("", 12, "bold")).pack(pady=10)
        tk.Label(self, text="输出: <模型名>_线束3D拓扑分析.xlsx / <模型名>_拓扑3D图.png\n"
                            "生成在 STEP 文件所在文件夹",
                 fg="dimgray", justify="left").pack()

        frm = tk.Frame(self); frm.pack(pady=8)
        tk.Label(frm, text="端点聚类容差(mm):").pack(side="left")
        self.tol_var = tk.StringVar(value="3.0")
        tk.Entry(frm, textvariable=self.tol_var, width=8).pack(side="left", padx=5)

        self.btn = tk.Button(self, text="选择 STEP 文件并分析", font=("", 11),
                             width=24, height=2, command=self.on_pick)
        self.btn.pack(pady=6)

        self.log = scrolledtext.ScrolledText(self, height=14, state="disabled")
        self.log.pack(fill="both", expand=True, padx=10, pady=5)

        self.open_btn = tk.Button(self, text="打开输出文件夹", state="disabled",
                                  command=self.on_open)
        self.open_btn.pack(pady=6)

        self.log_msg("就绪。正在加载几何内核(约需数秒)...")
        threading.Thread(target=self._preload, daemon=True).start()
        self.after(100, self._poll)

    def _preload(self):
        try:
            import harness_topology  # noqa
            self.q.put(("log", "几何内核加载完成，请选择 STEP 文件。"))
        except Exception as e:
            self.q.put(("log", f"内核加载失败: {e}"))

    def log_msg(self, s):
        self.log.configure(state="normal")
        self.log.insert("end", s + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def on_pick(self):
        p = filedialog.askopenfilename(
            title="选择线束 STEP 文件",
            filetypes=[("STEP", "*.stp *.step"), ("全部", "*.*")])
        if not p:
            return
        try:
            tol = float(self.tol_var.get())
        except ValueError:
            messagebox.showwarning("提示", "容差请输入数字")
            return
        self.btn.configure(state="disabled")
        self.open_btn.configure(state="disabled")
        self.log_msg(f"开始分析: {p}")
        threading.Thread(target=self._run, args=(p, tol), daemon=True).start()

    def _run(self, step_path, tol):
        try:
            import harness_topology, viz_topology, report_xlsx
            folder = os.path.dirname(step_path)
            base = os.path.splitext(os.path.basename(step_path))[0]
            xlsx = os.path.join(folder, f"{base}_线束3D拓扑分析.xlsx")
            png = os.path.join(folder, f"{base}_拓扑3D图.png")
            js = os.path.join(folder, f"{base}_topology.json")

            def prog(m): self.q.put(("log", m))
            r = harness_topology.analyze(step_path, tol, out_dir=folder, progress=prog)
            with open(js, "w") as f:
                json.dump(r, f, indent=1)
            self.q.put(("log", f"分支 {len(r['branches'])} 个, 节点 {len(r['nodes'])} 个"))
            self.q.put(("log", "生成 3D 拓扑图..."))
            viz_topology.make_plot(r, png)
            self.q.put(("log", "生成 Excel 报告..."))
            report_xlsx.make_report(r, xlsx)
            self.q.put(("done", [xlsx, png, js]))
        except Exception:
            self.q.put(("log", "失败:\n" + traceback.format_exc()))
            self.q.put(("fail", None))

    def _poll(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "log":
                    self.log_msg(payload)
                elif kind == "done":
                    self.result_paths = payload
                    self.log_msg("分析完成，输出文件:")
                    for p in payload:
                        self.log_msg("  " + p)
                    self.btn.configure(state="normal")
                    self.open_btn.configure(state="normal")
                    messagebox.showinfo("完成", "分析完成，表格已生成在模型所在文件夹。")
                elif kind == "fail":
                    self.btn.configure(state="normal")
                    messagebox.showerror("失败", "分析失败，详见日志。")
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def on_open(self):
        if self.result_paths:
            folder = os.path.dirname(self.result_paths[0])
            os.startfile(folder)


if __name__ == "__main__":
    App().mainloop()
