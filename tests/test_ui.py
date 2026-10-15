import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

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
root.withdraw()
app = mc.MouseClickerApp(root)
app.records_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "smoke_records.json")
if os.path.exists(app.records_file):
    os.remove(app.records_file)

# 构造目标场景
gA = mc.make_group("组A-123", 100, [mc.make_click(1, 1), mc.make_click(2, 2), mc.make_click(3, 3)])
gB = mc.make_group("组B-动作4", 5, [mc.make_click(4, 4)])
app.sequence = [gA, gB]
app.refresh_tree()
root.update()
print("tree rows:", len(app.tree.get_children("")))
print("desc of first:", app.tree.item(app.tree.get_children("")[0], "text"))
kids = app.tree.get_children(app.tree.get_children("")[0])
print("group children rows:", len(kids))
assert len(kids) == 3

# 选中组A，再记录一个动作（用假的鼠标位置），应插进组里
app.mouse_controller.position = (77, 88)
app.tree.selection_set(app.tree.get_children("")[0])
app.count_var.set("2")
app.record_position()
app.refresh_tree(); root.update()
kids = app.tree.get_children(app.tree.get_children("")[0])
print("after insert into groupA:", len(kids))
assert len(kids) == 4

# 连续记录：选中项仍是组A，应继续往组A里加
app.record_position()
app.refresh_tree(); root.update()
kids = app.tree.get_children(app.tree.get_children("")[0])
print("after 2nd insert (selection kept):", len(kids))
assert len(kids) == 5

# find_container / move / delete
found = app.find_container(gB)
print("find gB ->", found[0] is app.sequence, found[1])
assert found[1] == 1

# 选中组B（根层第2项）后上移
app.tree.selection_set(app.tree.get_children("")[1])
app.move_selected(-1)
assert app.find_container(gB)[1] == 0

# 移出组：选组A里的第一个动作，把它搬回根层
assert app.tree.item(app.tree.get_children("")[1], "text").startswith("【组】组A")
inner = app.tree.get_children(app.tree.get_children("")[1])
app.tree.selection_set(inner[0])
app.move_out_group()
app.refresh_tree(); root.update()
print("root rows after move_out:", len(app.tree.get_children("")))
assert len(app.tree.get_children("")) == 3

# 保存 / 加载记录
app.saved_records = {}
name = "测试记录"
app.saved_records[name] = {"sequence": app.sequence, "settings": app.current_settings()}
app.save_records()
app.sequence = []
app.load_records()
app.load_record(name)
app.refresh_tree(); root.update()
print("reloaded root rows:", len(app.tree.get_children("")))
print("reloaded action count:", mc.count_actions(app.sequence))

# 状态栏节流
for i in range(50):
    app.set_status("状态: 测试 %d" % i)
root.update()
print("status ok:", app.status_var.get())

os.remove(app.records_file)
root.destroy()
print("\nUI 冒烟测试通过")
