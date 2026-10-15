import os, sys, types, time

# ---- stub pynput so we can import the module without a mouse ----
stub = types.ModuleType("pynput")
m = types.ModuleType("pynput.mouse")
class Button:
    left = "left"; right = "right"
class Controller:
    def __init__(self): self.position = (0, 0); self.ops = []
    def press(self, b): self.ops.append(("press", b, self.position))
    def release(self, b): self.ops.append(("release", b, self.position))
m.Button = Button; m.Controller = Controller
stub.mouse = m
sys.modules["pynput"] = stub
sys.modules["pynput.mouse"] = m

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) or ".")
import mouse_clicker_v2 as mc

print("[1] legacy format normalize")
legacy = [
    {"type": "click", "x": 1, "y": 2, "count": 3},
    {"type": "drag", "start_x": 0, "start_y": 0, "end_x": 9, "end_y": 9, "duration": 0.2},
]
seq = mc.normalize_sequence(legacy)
print("   ->", [mc.describe_node(n) for n in seq])
assert seq[0]["kind"] == "click" and seq[0]["count"] == 3 and seq[0]["repeat"] == 1
assert mc.node_total_clicks(seq[0]) == 3, "v1 的 count 应原样保留为点击次数"
assert seq[1]["kind"] == "drag"
print("   OK")

print("[2] 目标场景：动作123 执行100次 -> 动作4 循环 -> 整体循环")
click1 = mc.make_click(10, 10, 1)
click2 = mc.make_click(20, 20, 1)
click3 = mc.make_click(30, 30, 1)
click4 = mc.make_click(40, 40, 1)
groupA = mc.make_group("组A-123", 100, [click1, click2, click3])
groupB = mc.make_group("组B-动作4", 5, [click4])
sequence = [groupA, groupB]

class FakeApp:
    def __init__(self):
        self.is_running = True
        self.mouse_controller = Controller()
        self.log = []
    def set_status(self, text, force=False):
        pass

app = FakeApp()
settings = {"interval": 0.0, "move_delay": 0.0, "start_delay": 0, "loop": 2}
runner = mc.ActionRunner(app, sequence, settings, Button.left)
runner.run()

# 组A: 100 遍 x 3 个点击 = 300 次
# 组B: 5 遍 x 1 = 5 次
# 每轮 = 305, 共 2 轮 = 610
print("   clicks =", runner.stats.clicks, " actions =", runner.stats.actions,
      " loops =", runner.stats.loops)
assert runner.stats.clicks == 610, runner.stats.clicks
assert runner.stats.loops == 2
print("   OK: 610 次鼠标操作 = (3x100 + 5) x 2 轮")

print("[3] 停止可中断无限循环")
app2 = FakeApp()
inf = [mc.make_group("无限组", 0, [mc.make_click(1, 1, 1)])]
r2 = mc.ActionRunner(app2, inf, {"interval": 0.0, "move_delay": 0.0,
                                 "start_delay": 0, "loop": 0}, Button.left)
import threading
t = threading.Thread(target=r2.run)
t.start()
time.sleep(0.15)
app2.is_running = False
t.join(timeout=3)
print("   无限循环被停止, clicks =", r2.stats.clicks, "线程存活 =", t.is_alive())
assert not t.is_alive()

print("[4] 嵌套两组（三级层级）")
inner = mc.make_group("内层", 2, [mc.make_click(5, 5, 3)])
outer = mc.make_group("外层", 4, [inner, mc.make_click(6, 6, 1)])
app3 = FakeApp()
r3 = mc.ActionRunner(app3, [outer], {"interval": 0.0, "move_delay": 0.0,
                                     "start_delay": 0, "loop": 1}, Button.left)
r3.run()
# 每遍外层: 内层 2x3=6 次 + 1 次 = 7 ; 外层 4 遍 = 28
print("   clicks =", r3.stats.clicks)
assert r3.stats.clicks == 28, r3.stats.clicks
print("   OK: 嵌套层级正常")

print("[5] 拖动动作")
app4 = FakeApp()
seq4 = [mc.make_drag(0, 0, 100, 100, 0.05, 2)]
r4 = mc.ActionRunner(app4, seq4, {"interval": 0.0, "move_delay": 0.0,
                                  "start_delay": 0, "loop": 1}, Button.left)
r4.run()
presses = [o for o in app4.mouse_controller.ops if o[0] == "press"]
print("   drag 执行次数 =", len(presses), " actions =", r4.stats.actions)
assert len(presses) == 2
print("   OK")

print("[6] 点击次数 x 循环遍数")
app5 = FakeApp()
seq5 = [mc.make_click(7, 7, count=3, repeat=4)]      # 3 连点 x 4 遍 = 12
r5 = mc.ActionRunner(app5, seq5, {"interval": 0.0, "move_delay": 0.0,
                                  "start_delay": 0, "loop": 2}, Button.left)
r5.run()
print("   节点:", mc.describe_node(seq5[0]))
print("   clicks =", r5.stats.clicks, "(3 x 4 x 2 轮 = 24)")
assert mc.node_total_clicks(seq5[0]) == 12
assert r5.stats.clicks == 24, r5.stats.clicks
print("   OK: 点击次数 x 循环遍数 x 整体轮数 三层都生效")

print("[7] 预估操作次数 / 耗时")
clicks, drags, inf = mc.estimate_sequence([groupA, groupB])
print("   一轮: 点击 %d 次, 拖动 %d 次, 含无限组 = %s" % (clicks, drags, inf))
assert (clicks, drags, inf) == (305, 0, False), (clicks, drags, inf)
c2, d2, i2 = mc.estimate_sequence([mc.make_group("无限", 0, [mc.make_click(1, 1, 2)])])
assert i2 is True and c2 == 2, (c2, i2)
secs = mc.estimate_seconds(305, 0, {"interval": 0.1, "move_delay": 0.5})
print("   305 次点击 @ 间隔0.1+移动0.5 = 约 %.1f 秒 / 轮" % secs)
assert abs(secs - 305 * 0.6) < 1e-6
print("   OK")

print("\n全部通过")
