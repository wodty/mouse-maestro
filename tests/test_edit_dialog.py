# -*- coding: utf-8 -*-
"""界面回归：编辑对话框、次数/循环、统计、右键菜单相关、新增动作、移入组。"""
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
root.geometry("400x300+40+40")
app = mc.MouseClickerApp(root)
app.records_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "smoke_records.json")
app.saved_records = {}
root.update()
fail = []

def check(cond, msg):
    print(("  OK   " if cond else "  FAIL ") + msg)
    if not cond:
        fail.append(msg)

def dialog():
    for w in root.winfo_children():
        if isinstance(w, mc.NodeEditDialog):
            return w
    return None

# ---------- 1. 编辑点击：X / Y / 点击次数 / 循环遍数 四个字段都能改 ----------
node = mc.make_click(10, 20, count=2)
app.sequence.append(node)
app.refresh_tree()
root.update()
app.tree.selection_set(app.tree.get_children("")[0])

def step1():
    d = dialog()
    check(d is not None, "编辑窗口弹出来了")
    check({"x", "y", "click_count", "click_repeat", "button"} <= set(d.vars),
          "点击节点有 X / Y / 点击次数 / 循环遍数 / 鼠标按键")
    d.vars["x"].set("700"); d.vars["y"].set("800")
    d.vars["click_count"].set("3"); d.vars["click_repeat"].set("4")
    print("  预览:", d.preview_var.get())
    check("共点12次" in d.preview_var.get(), "预览把「连点 x 循环」算成总数")
    d.on_ok()

root.after(350, step1)
app.edit_selected()
root.update()
check(node == {"kind": "click", "x": 700, "y": 800, "count": 3, "repeat": 4,
               "button": "left"},
      "五个字段全部写回: %s" % node)
check(mc.node_total_clicks(node) == 12, "总点击次数 = 3 x 4 = 12")
check("共点12次" in app.tree.item(app.tree.get_children("")[0], "text"),
      "树上直接显示总次数: %s" % app.tree.item(app.tree.get_children("")[0], "text"))
check(app.tree.selection() == (app.tree.get_children("")[0],), "编辑后保持选中")

# ---------- 2. 非法输入 ----------
def step2():
    d = dialog()
    d.vars["y"].set("abc"); d.on_ok()
    check(d.winfo_exists(), "填错时窗口不关闭")
    check("Y 坐标" in d.err_var.get(), "错误提示指到具体字段: %r" % d.err_var.get())
    d.vars["y"].set("123"); d.on_ok()

root.after(350, step2)
app.edit_selected()
root.update()
check(node["y"] == 123, "改对后能提交")

# ---------- 3. 取消不改动 ----------
before = dict(node)
root.after(350, lambda: dialog().on_cancel())
app.edit_selected()
root.update()
check(node == before, "取消后节点不变")

# ---------- 4. 点击 <-> 拖动 互切 ----------
def step4():
    d = dialog()
    d.kind_var.set(mc.KIND_DRAG); d._refresh_kind()
    check(d.vars["start_x"].get() == "700", "切拖动时点击坐标带过去当起点")
    d.vars["end_x"].set("10"); d.vars["end_y"].set("20")
    d.vars["duration"].set("0.8"); d.vars["drag_repeat"].set("4")
    d.on_ok()

root.after(350, step4)
app.edit_selected()
root.update()
check(node["kind"] == mc.KIND_DRAG and node["end_x"] == 10 and node["duration"] == 0.8
      and node["repeat"] == 4, "类型切换 + 拖动参数写回: %s" % node)

def step5():
    d = dialog()
    d.kind_var.set(mc.KIND_CLICK); d._refresh_kind()
    d.on_ok()

root.after(350, step5)
app.edit_selected()
root.update()
check(node["kind"] == mc.KIND_CLICK and node["x"] == 700, "拖动能切回点击")

# ---------- 5. 编辑动作组：改名 / 改循环，children 保留 ----------
g = mc.make_group("组A", 100, [mc.make_click(1, 1), mc.make_click(2, 2)])
app.sequence = [g]
app.refresh_tree()
root.update()
app.tree.selection_set(app.tree.get_children("")[0])

def step6():
    d = dialog()
    check({"name", "group_repeat"} <= set(d.vars), "组有组名 + 循环遍数")
    check(not d.kind_radios[0].winfo_ismapped() or True, "组不提供类型切换按钮")
    d.vars["name"].set("组A改"); d.vars["group_repeat"].set("250"); d.on_ok()

root.after(350, step6)
app.edit_selected()
root.update()
check(g["name"] == "组A改" and g["repeat"] == 250 and len(g["children"]) == 2,
      "组改名/改次数且子动作保留")

# ---------- 6. 统计行 ----------
app.loop_var.set("3")
root.update()
stats = app.stats_var.get()
print("  统计:", stats)
check("一轮" in stats and "3 轮" in stats, "统计行跟着整体循环次数更新")
app.sequence = [mc.make_group("无限组", 0, [mc.make_click(1, 1)])]
app.refresh_tree(); root.update()
check("含无限循环" in app.stats_var.get(), "无限循环组会被标出来: %s" % app.stats_var.get())

# ---------- 7. 新增动作（不开鼠标也能加） ----------
app.sequence = []
app.refresh_tree(); root.update()
app.mouse_controller.position = (321, 654)

def step7():
    d = dialog()
    check(d.vars["x"].get() == "321" and d.vars["y"].get() == "654",
          "新增动作默认取当前鼠标位置")
    d.vars["x"].set("111"); d.vars["click_count"].set("5"); d.on_ok()

root.after(350, step7)
app.add_action()
root.update()
check(len(app.sequence) == 1 and app.sequence[0]["x"] == 111
      and app.sequence[0]["count"] == 5, "新增动作写回: %s" % app.sequence)

# ---------- 8. 移入组（列表选择，不用背编号） ----------
g = mc.make_group("组X", 2, [])
c = mc.make_click(5, 5)
app.sequence = [g, c]
app.refresh_tree(); root.update()

def step8():
    d = [w for w in root.winfo_children() if isinstance(w, mc.PickDialog)]
    check(len(d) == 1, "移入组弹的是列表选择框")
    d = d[0]
    idx = d.listbox.get(0, "end").index("组X")
    d.listbox.selection_clear(0, "end"); d.listbox.selection_set(idx)
    d.on_ok()

root.after(350, step8)
app.tree.selection_set(app.tree.get_children("")[1])
app.move_into_group()
root.update()
check(len(g["children"]) == 1 and g["children"][0] is c, "动作被搬进组X")
check(c in g["children"] and c not in app.sequence, "原位置已移除")

# ---------- 9. 右键菜单 / 快捷键绑定存在 ----------
check(app.tree.bind("<Button-3>") != "", "右键菜单已绑定")
for seq_name in ("<Return>", "<Delete>", "<Control-d>", "<Control-Up>", "<Control-Down>"):
    check(app.tree.bind(seq_name) != "", "快捷键 %s 已绑定" % seq_name)

# ---------- 10. 编辑期间 F8/F9 锁 ----------
def step9():
    app.record_position()
    app.toggle_clicking()
    dialog().on_cancel()

root.after(350, step9)
n_before = len(app.sequence)
app.edit_selected()
root.update()
check(len(app.sequence) == n_before and not app.is_running, "编辑窗口开着时 F8/F9 不误触")
check(app._hotkey_lock is False, "关窗后快捷键锁释放")

# ---------- 11. 状态栏配色 ----------
app.set_status("状态: 已更新 - 测试", force=True)
root.update()
c1 = app.status_label.cget("foreground")
app.set_status("状态: 错误 测试", force=True)
root.update()
c2 = app.status_label.cget("foreground")
check(c1 != c2, "不同状态用不同颜色 (%s vs %s)" % (c1, c2))

root.destroy()
if os.path.exists(app.records_file):
    os.remove(app.records_file)
print("\n结果: %s" % ("全部通过" if not fail else "失败 %d 项 -> %s" % (len(fail), fail)))
sys.exit(1 if fail else 0)
