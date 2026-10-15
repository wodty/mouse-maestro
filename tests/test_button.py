import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# -*- coding: utf-8 -*-
"""鼠标按键（左键 / 右键）与动作列表显示 —— 测试。

覆盖：
  1. describe_node 把按键、坐标、次数、遍数都说全
  2. 老数据没有 button -> 显示「跟随设置」且不写入 button 字段
  3. 执行时按节点自己的按键；节点没写才用设置区的默认键
  4. 拖动动作也认自己的按键
  5. 编辑窗口能读 / 改按键
  6. 主界面记录新动作时带上当前设置区的按键
  7. 动作列表列宽随窗口自适应（不再截断描述）
"""
import os
import sys
import types

# ---- stub pynput：鼠标要能记录操作，键盘故意不给（顺便验证降级路径） ----
stub = types.ModuleType("pynput")
m = types.ModuleType("pynput.mouse")


class Button:
    left = "left"
    right = "right"


class Controller:
    def __init__(self):
        self.position = (0, 0)
        self.ops = []

    def press(self, b):
        self.ops.append(("press", b))

    def release(self, b):
        self.ops.append(("release", b))


m.Button = Button
m.Controller = Controller
stub.mouse = m
sys.modules["pynput"] = stub
sys.modules["pynput.mouse"] = m

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) or ".")
import mouse_clicker_v2 as mc
import tkinter as tk

fails = []


def check(cond, msg):
    print(("  [OK] " if cond else "  [FAIL] ") + msg)
    if not cond:
        fails.append(msg)


SETTINGS = {"interval": 0.0, "move_delay": 0.0, "start_delay": 0, "loop": 1}


class FakeApp:
    def __init__(self):
        self.is_running = True
        self.mouse_controller = Controller()

    def set_status(self, text, force=False):
        pass


# ---------- 1. 描述文字 ----------
print("[1] 动作描述把按键说全")
t = mc.describe_node(mc.make_click(700, 800, 3, 4, "right"))
print("   ", t)
check("点击·右键" in t, "带按键名")
check("(700, 800)" in t, "带坐标")
check("连点3次" in t and "×4遍" in t and "共点12次" in t, "带次数与遍数")

t2 = mc.describe_node(mc.make_click(10, 20))
print("   ", t2)
check("点击·左键" in t2 and "单击" in t2, "默认左键、单击写法完整")

t3 = mc.describe_node({"kind": "click", "x": 1, "y": 2, "count": 1, "repeat": 1})
print("   ", t3)
check("跟随设置" in t3, "老数据没按键 -> 显示跟随设置")

t4 = mc.describe_node(mc.make_drag(1, 2, 3, 4, 0.35, 2, "right"))
print("   ", t4)
check("拖动·右键" in t4 and "持续0.35s" in t4 and "×2遍" in t4, "拖动描述完整")

t5 = mc.describe_node(mc.make_group("组A", 100, [mc.make_click(1, 1)]))
print("   ", t5)
check("循环 100 遍" in t5 and "1 个动作" in t5, "动作组描述完整")

t6 = mc.describe_node(mc.make_group("组B", 0, []))
check("无限循环" in t6, "无限组描述正确")


# ---------- 2. normalize 保留按键 ----------
print("[2] 旧数据兼容")
seq = mc.normalize_sequence([
    {"kind": "click", "x": 1, "y": 1, "count": 1, "repeat": 1},
    {"kind": "click", "x": 2, "y": 2, "count": 1, "repeat": 1, "button": "right"},
    {"type": "drag", "start_x": 0, "start_y": 0, "end_x": 1, "end_y": 1},
])
check("button" not in seq[0], "老数据不凭空写入 button（继续跟随设置）")
check(seq[1]["button"] == "right", "已有 button 原样保留")
check("button" not in seq[2], "老拖动数据也不写入 button")


# ---------- 3. 执行时用节点按键 ----------
print("[3] 执行按键")
app = FakeApp()
r = mc.ActionRunner(app, [mc.make_click(1, 1, 1, 1, "right"),
                          mc.make_click(2, 2, 1, 1)], SETTINGS, Button.left)
r.run()
presses = [o[1] for o in app.mouse_controller.ops if o[0] == "press"]
print("   按下顺序:", presses)
check(presses == ["right", "left"], "自带右键的点右键，没写的回落到设置的左键")
check(r.stats.clicks == 2, "两次点击都算进统计")

app2 = FakeApp()
r2 = mc.ActionRunner(app2, [{"kind": "click", "x": 3, "y": 3,
                             "count": 1, "repeat": 1}], SETTINGS, Button.right)
r2.run()
presses2 = [o[1] for o in app2.mouse_controller.ops if o[0] == "press"]
check(presses2 == ["right"], "默认键设成右键时，没写按键的动作点右键")


# ---------- 4. 拖动按键 ----------
print("[4] 拖动按键")
app3 = FakeApp()
r3 = mc.ActionRunner(app3, [mc.make_drag(0, 0, 5, 5, 0.01, 1, "right")],
                     SETTINGS, Button.left)
r3.run()
ops = app3.mouse_controller.ops
check([o[1] for o in ops if o[0] == "press"] == ["right"], "拖动按自己的右键按下")
check([o[1] for o in ops if o[0] == "release"] == ["right"], "拖动松开同一个键")


# ---------- 5. 编辑窗口 ----------
print("[5] 编辑窗口改按键")
root = tk.Tk()
appui = mc.MouseClickerApp(root)
root.update()
check(appui.hotkeys is None and appui._window_hotkeys_bound,
      "没有 keyboard 子模块时自动降级为窗口内热键")

driven = {}


def drive():
    wins = [w for w in root.winfo_children() if isinstance(w, mc.NodeEditDialog)]
    dlg = wins[0]
    driven["loaded"] = dlg.button_var.get()
    dlg.button_var.set("left")
    dlg.on_ok()


root.after(300, drive)
dlg = mc.NodeEditDialog(appui, mc.make_click(1, 1, 1, 1, "right"))
check(driven.get("loaded") == "right", "打开时读到节点自带的右键")
check(dlg.result is not None and dlg.result["button"] == "left",
      "改成左键后确定，结果里是 left")


def drive2():
    dlg2 = [w for w in root.winfo_children() if isinstance(w, mc.NodeEditDialog)][0]
    dlg2.button_var.set("right")
    dlg2.on_ok()


root.after(300, drive2)
dlg2 = mc.NodeEditDialog(appui, mc.make_drag(0, 0, 9, 9, 0.2, 1))
check(dlg2.result["button"] == "right", "拖动也能在编辑窗口里改成右键")
check(mc.describe_node(dlg2.result).startswith("拖动·右键"), "改完描述同步更新")


# ---------- 6. 主界面记录新动作 ----------
print("[6] 记录新动作时带上默认键")
appui.button_var.set("right")
appui.action_type_var.set(mc.KIND_CLICK)
appui.count_var.set("2")
appui.mouse_controller.position = (321, 654)
appui.record_position()
node = appui.sequence[-1]
print("   ", mc.describe_node(node))
check(node.get("button") == "right", "新记录的点击动作是右键")
check((node["x"], node["y"]) == (321, 654), "坐标跟着鼠标位置")

appui.button_var.set("left")
appui.mouse_controller.position = (11, 22)
appui.record_position()
check(appui.sequence[-1].get("button") == "left", "切回左键后新记录是左键")

appui.action_type_var.set(mc.KIND_DRAG)
appui.drag_duration_var.set("0.2")
appui.mouse_controller.position = (30, 40)
appui.record_position()          # 第一次 = 起点
appui.mouse_controller.position = (50, 60)
appui.record_position()          # 第二次 = 终点
drag_node = appui.sequence[-1]
check(drag_node["kind"] == mc.KIND_DRAG and drag_node.get("button") == "left",
      "拖动的按键也跟着设置")


# ---------- 7. 列宽自适应 ----------
print("[7] 动作列表列宽")
root.update()
w1 = appui.tree.column("#0")["width"]
print("   900 宽窗口下列宽 =", w1)
check(w1 > 400, "列宽足够放下完整描述（%d）" % w1)

root.geometry("1060x780")
root.update()
root.update_idletasks()
w2 = appui.tree.column("#0")["width"]
print("   1060 宽窗口下列宽 =", w2)
check(w2 > w1, "窗口变宽后列宽跟着变宽（%d -> %d）" % (w1, w2))

appui.shutdown()
root.destroy()

print("\n" + ("全部通过" if not fails else "失败 %d 项：%s" % (len(fails), fails)))
sys.exit(1 if fails else 0)
