import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# -*- coding: utf-8 -*-
"""布局体检：有没有按钮被挤出窗口 / 高度不够。"""
import os, sys, types

stub = types.ModuleType("pynput"); m = types.ModuleType("pynput.mouse")
class Button: left = "left"; right = "right"
class Controller:
    def __init__(self): self.position = (0, 0)
    def press(self, b): pass
    def release(self, b): pass
m.Button = Button; m.Controller = Controller
stub.mouse = m
sys.modules["pynput"] = stub; sys.modules["pynput.mouse"] = m
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) or ".")
import mouse_clicker_v2 as mc
import tkinter as tk

root = tk.Tk()
app = mc.MouseClickerApp(root)
app.records_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "smoke_records.json")
root.update()
root.update_idletasks()

win_w, win_h = root.winfo_width(), root.winfo_height()
outer = root.winfo_children()[0]
req_w, req_h = outer.winfo_reqwidth(), outer.winfo_reqheight()
print("窗口: %dx%d   内容需要: %dx%d" % (win_w, win_h, req_w, req_h))
if req_w > win_w:
    print("!! 宽度不够，右侧会被挤掉 %d px" % (req_w - win_w))
if req_h > win_h:
    print("!! 高度不够，底部会被挤掉 %d px" % (req_h - win_h))

# 逐个检查每一行的按钮有没有超出窗口右边界
def walk(w, depth=0):
    for child in w.winfo_children():
        try:
            if child.winfo_ismapped():
                x = child.winfo_rootx() - root.winfo_rootx()
                right = x + child.winfo_width()
                if right > win_w + 1:
                    print("   溢出: %s %r 右边界 %d > 窗口 %d"
                          % (child.winfo_class(), child.cget("text")
                             if "text" in child.keys() else "", right, win_w))
        except Exception:
            pass
        walk(child, depth + 1)

walk(root)
print("--- 关键控件宽度 ---")
for name in ("tree", "start_btn", "record_combo"):
    w = getattr(app, name, None)
    if w is not None:
        print("  %-14s width=%d height=%d" % (name, w.winfo_width(), w.winfo_height()))
print("  帮助按钮文字:", app.help_btn.cget("text"))
print("  开始按钮文字:", app.start_btn.cget("text"))
print("  提示行:", app.hint_var.get())
print("  最小尺寸:", root.minsize())
print("  统计行:", app.stats_var.get())
print("  状态行:", app.status_var.get())
root.destroy()
if os.path.exists(app.records_file):
    os.remove(app.records_file)
