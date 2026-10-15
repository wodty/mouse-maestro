# -*- coding: utf-8 -*-
"""全局热键（F8 / F9）的行为测试。

覆盖：
  1. 钩子能否挂上（环境相关，只报告不断言）
  2. 长按去抖：按住 F8 不会疯狂触发
  3. 队列分发：按键经队列转到主线程执行
  4. 别的按键不被拦截入队
  5. 编辑窗口取点中，F9 走「取当前位置」而不是录一个新动作
  6. 编辑窗口锁定时 F8 不会启动点击
  7. 开关：关掉全局热键后回落窗口绑定，提示文字跟着变
  8. Tk 窗口绑定在关闭全局后确实生效
"""
import sys
import tkinter as tk

sys.path.insert(0, ".")
import mouse_clicker_v2 as mc

from pynput.keyboard import Key, KeyCode

fails = []


def check(cond, msg):
    print(("  [OK] " if cond else "  [FAIL] ") + msg)
    if not cond:
        fails.append(msg)


root = tk.Tk()
root.withdraw()
app = mc.MouseClickerApp(root)
root.update()

# ---------- 1. 挂载情况 ----------
print("[1] 全局钩子挂载")
global_ok = app.hotkeys is not None
print("  全局热键可用 =", global_ok,
      "" if global_ok else "  原因: %s" % app.hotkeys_error)
print("  提示文字 =", app.hint_var.get())
app.shutdown()            # 先摘掉，免得测试期间真实按键乱入
root.update()

# ---------- 2. 去抖 ----------
print("[2] 长按去抖")
sq = mc.GlobalHotkeys(app)
keys = mc.GlobalHotkeys.hotkey_keys()
on_press, on_release = sq.make_handlers(keys)

on_press(Key.f8)
on_press(Key.f8)          # 系统长按重复
on_press(Key.f8)
check(sq.queue.qsize() == 1, "按住 F8 只入队一次（实际 %d）" % sq.queue.qsize())

on_press(KeyCode.from_char("a"))     # 字母键
on_press(KeyCode.from_char("8"))     # 数字键
on_press(Key.space)                  # 功能键
on_press(Key.f7)
check(sq.queue.qsize() == 1, "字母/数字/空格/F7 都不会被拦截入队")

on_release(Key.f8)
on_press(Key.f8)
check(sq.queue.qsize() == 2, "松开后再按算第二次（实际 %d）" % sq.queue.qsize())

on_release(Key.f9)        # 没按过就松，不应有副作用
check(sq.queue.qsize() == 2, "多余 release 不影响状态")

# ---------- 3. 队列分发 ----------
print("[3] 分发到主线程")
calls = []
real_on_hotkey = app.on_hotkey
app.on_hotkey = lambda name: calls.append(name)
sq.queue.put("f9")
sq._drain()
check(calls == ["f8", "f8", "f9"], "队列按顺序分发（实际 %r）" % (calls,))
check(sq.queue.empty(), "分发后队列清空")
app.on_hotkey = real_on_hotkey

# ---------- 4. 编辑窗口取点 ----------
print("[4] 编辑窗口的 F9 = 取当前位置")
app._hotkey_lock = True
hits = []
app._f9_hook = lambda: hits.append(1)
app.record_position()
check(hits == [1], "取点中按 F9 会抓坐标")
check(mc.count_actions(app.sequence) == 0, "取点中按 F9 不会录出新动作")

app._f9_hook = None
app.record_position()
check(mc.count_actions(app.sequence) == 0, "编辑窗口开着时按 F9 不录动作")

# ---------- 5. 编辑窗口的 F8 ----------
print("[5] 编辑窗口的 F8")
app.on_hotkey("f8")
root.update()
check(app.is_running is False, "编辑窗口开着时 F8 不会启动点击")
check("已暂停" in app.status_var.get(), "状态栏给出提示（%s）" % app.status_var.get())
app._hotkey_lock = False

# ---------- 6. 开关 ----------
print("[6] 全局热键开关")
app.global_hotkey_var.set(False)
app.toggle_global_hotkeys()
root.update()
check(app.hotkeys is None, "关掉后不再持有全局钩子")
check(app._window_hotkeys_bound, "回落到窗口内绑定")
check("仅窗口内有效" in app.hint_var.get(), "提示文字说明只在窗口内（%s）" % app.hint_var.get())
check(bool(root.bind("<F8>")), "root 上确实绑了 F8")
check(bool(root.bind("<F9>")), "root 上确实绑了 F9")

app.global_hotkey_var.set(True)
app.toggle_global_hotkeys()
root.update()
if global_ok:
    check(app.hotkeys is not None, "重新开启后全局钩子回来了")
    check(not app._window_hotkeys_bound, "全局生效时不再重复绑窗口，避免一次按键跑两遍")
    check("全局热键" in app.hint_var.get(), "提示文字切回全局（%s）" % app.hint_var.get())
else:
    check(app._window_hotkeys_bound, "环境不支持全局时保持窗口绑定")

# ---------- 7. 退出清理 ----------
print("[7] 退出清理")
app.shutdown()
root.update()
check(app.hotkeys is None, "退出时钩子被摘掉")
check(sq.listener is None, "未启动的实例 stop 不报错")

root.destroy()
print("\n" + ("全部通过" if not fails else "失败 %d 项：%s" % (len(fails), fails)))
sys.exit(1 if fails else 0)
