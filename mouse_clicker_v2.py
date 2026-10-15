# -*- coding: utf-8 -*-
"""
鼠标编排师 —— 分组 · 多层级 · 嵌套循环连点器
__version__ = "1.0.0"

====================================================================
相比 v1（鼠标自动点击器 - 多位置模式）的改动
====================================================================
v1 的数据模型是「一个扁平的位置列表 + 一个全局循环次数」：

    positions = [ 点击A, 点击B, 拖动C ]      循环次数 = N

它能表达「整套动作循环 N 次」，但表达不了你要的：

    动作1、2、3 执行 100 次  →  然后动作4 循环  →  最后整体再循环

因为「动作1/2/3 一组重复 100 次」和「动作4 循环」是两个
重复次数不同的层级，扁平列表装不下。

v2 把位置列表升级成一棵「动作树」，每个节点都有自己的重复次数：

    sequence = [
        {kind:'group', name:'组A', repeat:100, children:[动作1, 动作2, 动作3]},
        {kind:'group', name:'组B', repeat:5,   children:[动作4]},
    ]
    loop_var = 0            # 整体循环（0 = 无限）—— 这就是「最后再全部循环」

执行引擎改成递归：组每循环一遍，就把它 children 里的节点按顺序执行一遍。
组里还能再放组，所以层级不限。

对应你的需求就是：
    组A(repeat=100) : 动作1 → 动作2 → 动作3     ← 执行 100 遍
    组B(repeat=0/5) : 动作4                     ← 循环
    整体循环次数    : 0(无限) 或 N              ← 全部再来一遍

====================================================================
兼容性
====================================================================
旧的 mouse_clicker_records.json 仍可直接加载：v1 的 positions
会被自动包装成一个 repeat=1 的动作组，设置项也照旧读取。
v1 每个点的 count（连点几下）现在存到节点的 count 字段，
实际点几下 = count * repeat，老数据的行为不变。

====================================================================
v2.1 这一轮的改动
====================================================================
1. 「编辑选中」不再连弹 3~6 个小输入框，改成一个窗口：
   类型 / 坐标 / 点击次数 / 循环遍数 / 时长 全在一屏，改完点确定一次生效。
   弹窗链只要中间有一个没拿到焦点，用户就只能改到第一个字段（X），
   这就是「编辑功能不全，只能改 x 轴」的根因。
2. 点击动作拆成两个字段：点击次数（连点几下）x 循环遍数（重复几遍）。
3. 编辑窗口里能直接把「点击」换成「拖动」，坐标自动带过去。
4. 编辑窗口里「取当前位置」= 3 秒倒计时后自动抓鼠标坐标（F9 也能取），
   编辑期间 F8/F9 会被暂停，避免误触。
5. 界面重排：动作列表占主要空间，统计行常驻显示「一轮多少次 / 约多久 / 整体几轮」。
6. 列表右键菜单 + 快捷键：Enter 编辑、Delete 删除、Ctrl+D 复制、Ctrl+↑↓ 移动。
7. 「移入组」改成列表选择（不用再记编号）。
8. 新增动作（手填坐标）、新增动作组；记录管理改成 保存 / 另存为 / 加载此记录 / 删除此记录。
9. 开始/停止按钮放大并配色，状态栏按状态变色。

====================================================================
v2.2 这一轮的改动
====================================================================
F8 / F9 变成**全局热键**：窗口没焦点、被别的程序挡住、缩到任务栏、
甚至正在后台跑点击的时候，按 F8/F9 一样生效。
实现方式：pynput 的低级键盘钩子（只旁观、不吞键、不影响别的软件），
回调在监听线程里只把键名丢进队列，主线程用 after 轮询取出后再操作
Tk（tkinter 不是线程安全的，不能跨线程直接碰控件）。
设置区有「全局热键」开关，勾掉就退回「只在窗口内有效」，
避免和别的软件的 F8/F9 撞车。
注意：对以管理员身份运行的窗口（如部分游戏 / 上位机）无效 ——
Windows 的 UIPI 会拦住普通权限的钩子，这种情况把本程序也用管理员
身份启动即可。

====================================================================
v2.3 这一轮的改动
====================================================================
1. 每个动作自己带鼠标按键（`button: left/right`）：
   设置区的「鼠标按键」变成「新动作的默认键」，录完之后在编辑窗口里还能单独改。
   老数据没写按键 -> 继续跟随设置区的默认键，行为不变。
2. 动作列表每行显示完整信息：`点击·左键 (700, 800)  连点3次  ×4遍  = 共点12次`，
   并把树列宽做成随窗口宽度自适应，长描述不再被截断成省略号。

依赖：pip install pynput
运行：python mouse_clicker_v2.py
打包：pyinstaller -F -w mouse_clicker_v2.py
====================================================================
"""

import copy
import json
import os
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

from pynput.mouse import Button, Controller

# ---------------------------------------------------------------- 数据模型

KIND_CLICK = "click"
KIND_DRAG = "drag"
KIND_GROUP = "group"

INFINITE = 0          # repeat == 0 表示无限循环

# 鼠标按键：动作可以自己带一个，不带就用设置区的默认键
BUTTON_NAMES = ("left", "right")
BUTTON_LABELS = {"left": "左键", "right": "右键"}


def norm_button(name):
    return name if name in BUTTON_LABELS else "left"


def button_text(node):
    """节点用的按键名。老数据没写按键 -> 跟随设置区的默认键。"""
    name = node.get("button") if isinstance(node, dict) else None
    return BUTTON_LABELS.get(name, "跟随设置")


def make_click(x, y, count=1, repeat=1, button="left"):
    """点击动作。

    count  —— 点击次数：每次「连点」几下（v1 里那个 count 就是这个）
    repeat —— 循环遍数：这个动作整体重复几遍
    button —— 鼠标按键："left" / "right"；传 None 表示跟随设置区的默认键
    实际点几下 = count * repeat
    """
    node = {"kind": KIND_CLICK, "x": int(x), "y": int(y),
            "count": max(1, int(count)), "repeat": max(1, int(repeat))}
    if button:
        node["button"] = norm_button(button)
    return node


def make_drag(start_x, start_y, end_x, end_y, duration=0.3, repeat=1, button="left"):
    node = {
        "kind": KIND_DRAG,
        "start_x": int(start_x), "start_y": int(start_y),
        "end_x": int(end_x), "end_y": int(end_y),
        "duration": max(0.0, float(duration)),
        "repeat": max(1, int(repeat)),
    }
    if button:
        node["button"] = norm_button(button)
    return node


def make_group(name="新动作组", repeat=1, children=None):
    return {
        "kind": KIND_GROUP,
        "name": str(name),
        "repeat": max(0, int(repeat)),
        "children": list(children) if children else [],
    }


def node_repeat(node):
    """这个节点整体重复几遍（组 = 循环遍数）。"""
    if node.get("kind") == KIND_GROUP:
        return max(0, int(node.get("repeat", 1)))
    return max(1, int(node.get("repeat", 1)))


def node_count(node):
    """点击动作里「每次连点几下」。兼容 v1 只写了 count 的老数据。"""
    if node.get("kind") != KIND_CLICK:
        return 1
    return max(1, int(node.get("count", 1)))


def node_total_clicks(node):
    """一个点击动作实际会点几下 = 点击次数 * 循环遍数。"""
    return node_count(node) * node_repeat(node)


def describe_node(node):
    """列表里那一行要显示的内容 —— 把一个动作说全：按键 + 坐标 + 次数 + 遍数。"""
    kind = node.get("kind")
    rep = node_repeat(node)
    rep_txt = "无限" if rep == INFINITE else "%d遍" % rep
    if kind == KIND_CLICK:
        cnt = node_count(node)
        parts = ["点击·%s" % button_text(node),
                 "(%s, %s)" % (node.get("x"), node.get("y")),
                 "连点%d次" % cnt if cnt > 1 else "单击"]
        if rep == INFINITE:
            parts.append("无限循环")
        else:
            parts.append("×%d遍" % rep)
            if cnt * rep > 1:
                parts.append("= 共点%d次" % node_total_clicks(node))
        return "  ".join(parts)
    if kind == KIND_DRAG:
        return "拖动·%s  (%s,%s) → (%s,%s)  持续%.2fs  ×%s" % (
            button_text(node),
            node.get("start_x"), node.get("start_y"),
            node.get("end_x"), node.get("end_y"),
            float(node.get("duration", 0.3)), rep_txt)
    if kind == KIND_GROUP:
        inside = count_actions(node.get("children", []))
        return "【组】%s    %s    (%d 个动作)" % (
            node.get("name", "未命名"),
            "无限循环" if rep == INFINITE else "循环 %d 遍" % rep, inside)
    return "未知节点"


def normalize_sequence(raw):
    """把任何历史格式的位置列表转成 v2 的动作树。"""
    if not isinstance(raw, list):
        return []
    out = []
    for p in raw:
        if not isinstance(p, dict):
            continue
        kind = p.get("kind") or p.get("type")
        if kind == KIND_GROUP:
            out.append(make_group(p.get("name", "未命名组"),
                                  p.get("repeat", 1),
                                  normalize_sequence(p.get("children", []))))
        elif kind == KIND_DRAG:
            out.append(make_drag(p.get("start_x", 0), p.get("start_y", 0),
                                 p.get("end_x", 0), p.get("end_y", 0),
                                 p.get("duration", 0.3),
                                 p.get("repeat", p.get("count", 1)),
                                 p.get("button")))
        elif kind == KIND_CLICK:
            # v1 只有 count（连点几下），v2 只有 repeat（循环几遍），两种都认。
            # 老数据没有 button -> 保持 None，继续跟随设置区的默认按键。
            out.append(make_click(p.get("x", 0), p.get("y", 0),
                                  p.get("count", 1), p.get("repeat", 1),
                                  p.get("button")))
    return out


def count_actions(nodes):
    """统计叶子动作总数（组本身不算）。"""
    total = 0
    for n in nodes:
        if n.get("kind") == KIND_GROUP:
            total += count_actions(n.get("children", []))
        else:
            total += 1
    return total


def estimate_sequence(nodes):
    """估算「整体跑一轮」的鼠标操作量。

    返回 (点击次数, 拖动次数, 是否含无限循环)。
    无限循环的组按跑 1 遍计入（否则估不出数），并置 inf=True。
    """
    clicks = drags = 0
    infinite = False
    for node in nodes:
        kind = node.get("kind")
        if kind == KIND_CLICK:
            clicks += node_total_clicks(node)
        elif kind == KIND_DRAG:
            drags += node_repeat(node)
        elif kind == KIND_GROUP:
            rep = node_repeat(node)
            sub_clicks, sub_drags, sub_inf = estimate_sequence(node.get("children", []))
            multiplier = 1 if rep == INFINITE else rep
            clicks += sub_clicks * multiplier
            drags += sub_drags * multiplier
            infinite = infinite or sub_inf or rep == INFINITE
    return clicks, drags, infinite


def estimate_seconds(clicks, drags, settings):
    """粗略估算一轮要跑多久：点击算一次移动延迟 + 一次间隔，拖动算一次间隔。"""
    per_click = float(settings.get("move_delay", 0.5)) + float(settings.get("interval", 0.1))
    per_drag = float(settings.get("interval", 0.1))
    return clicks * per_click + drags * per_drag


class ToolTip(object):
    """鼠标悬停提示（ttk 没有内置的）。"""

    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tip = None
        widget.bind("<Enter>", self.show, add="+")
        widget.bind("<Leave>", self.hide, add="+")
        widget.bind("<ButtonPress>", self.hide, add="+")

    def show(self, event=None):
        if self.tip is not None:
            return
        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry("+%d+%d" % (x, y))
        tk.Label(self.tip, text=self.text, background="#ffffe0",
                 relief="solid", borderwidth=1, font=("Microsoft YaHei UI", 9),
                 justify="left", padx=6, pady=3).pack()

    def hide(self, event=None):
        if self.tip is not None:
            self.tip.destroy()
            self.tip = None


# ---------------------------------------------------------------- 执行引擎

class RunStats(object):
    def __init__(self):
        self.clicks = 0          # 鼠标按键次数
        self.actions = 0         # 完成的叶子动作个数
        self.loops = 0           # 完成的整体轮数
        self.group_iters = 0     # 组内循环遍数


class ActionRunner(object):
    """把动作树跑起来的执行器。全部逻辑在一个后台线程里跑。

    递归执行，遇到 group 就把它 children 按 repeat 遍数反复执行。
    因为组可以套组，所以嵌套层级不受限制。
    """

    def __init__(self, app, sequence, settings, button):
        self.app = app
        self.sequence = sequence
        self.s = settings
        self.button = button          # 设置区里的默认键
        self.buttons = {"left": Button.left, "right": Button.right}
        self.stats = RunStats()
        self.mouse = app.mouse_controller

    def button_of(self, node):
        """这个动作用哪个键：节点自己带了就用它，否则用设置区的默认键。"""
        name = (node or {}).get("button")
        if name in self.buttons:
            return self.buttons[name]
        return self.button

    # -- 基础工具 ----------------------------------------------------
    def running(self):
        return self.app.is_running

    def sleep(self, seconds):
        """可被「停止」立刻打断的 sleep。"""
        if seconds <= 0:
            return
        end = time.time() + seconds
        remain = seconds
        while self.running() and remain > 0:
            time.sleep(remain if remain < 0.02 else 0.02)
            remain = end - time.time()

    def status(self, text):
        self.app.set_status(text)

    # -- 入口 --------------------------------------------------------
    def start_delay(self):
        delay = self.s["start_delay"]
        if delay <= 0:
            return
        left = delay
        while self.running() and left > 0:
            self.status("状态: %.1f 秒后开始..." % left)
            self.sleep(1)
            left -= 1

    def run(self):
        self.start_delay()
        if not self.running():
            return
        loop_count = self.s["loop"]
        infinite = (loop_count == INFINITE)
        while self.running():
            self.stats.loops += 1
            if infinite:
                head = "第 %d 轮循环（无限）" % self.stats.loops
            else:
                if self.stats.loops > loop_count:
                    self.stats.loops -= 1
                    break
                head = "第 %d/%d 轮循环" % (self.stats.loops, loop_count)
            self.status("%s - 开始执行..." % head)
            self.run_nodes(self.sequence, head, 0)

    # -- 递归执行 ----------------------------------------------------
    def run_nodes(self, nodes, head, depth):
        for idx, node in enumerate(nodes):
            if not self.running():
                return
            self.status("%s - 执行: %s" % (head, describe_node(node)))
            self.run_node(node, head, depth, idx + 1, len(nodes))

    def run_node(self, node, head, depth, index, siblings):
        kind = node.get("kind")
        rep = node_repeat(node)

        if kind == KIND_GROUP:
            n = 0
            children = node.get("children", [])
            while self.running() and (rep == INFINITE or n < rep):
                n += 1
                self.stats.group_iters += 1
                if rep == INFINITE:
                    self.status("%s - 【%s】第 %d 遍（无限）" % (head, node.get("name"), n))
                else:
                    self.status("%s - 【%s】第 %d/%d 遍" % (head, node.get("name"), n, rep))
                if not children:
                    self.sleep(0.05)
                    if rep == INFINITE:
                        break
                    continue
                self.run_nodes(children, head, depth + 1)
            return

        if kind == KIND_CLICK:
            count = node_count(node)          # 每次连点几下
            for n in range(rep):              # 循环几遍
                for i in range(count):
                    if not self.running():
                        return
                    x, y = node.get("x"), node.get("y")
                    if count == 1 and rep == 1:
                        self.status("%s - 点击 (%s, %s)" % (head, x, y))
                    elif count == 1:
                        self.status("%s - 点击 (%s, %s)  第 %d/%d 遍"
                                    % (head, x, y, n + 1, rep))
                    else:
                        self.status("%s - 点击 (%s, %s)  第 %d/%d 遍 · 连点 %d/%d"
                                    % (head, x, y, n + 1, rep, i + 1, count))
                    self.do_click(node)
            return

        if kind == KIND_DRAG:
            for i in range(rep):
                if not self.running():
                    return
                self.status("%s - 拖动 (%s,%s)->(%s,%s)  第 %d/%d 次"
                            % (head, node.get("start_x"), node.get("start_y"),
                               node.get("end_x"), node.get("end_y"), i + 1, rep))
                self.do_drag(node)
            return

    # -- 具体动作 ----------------------------------------------------
    def do_click(self, node):
        x, y = int(node["x"]), int(node["y"])
        btn = self.button_of(node)
        self.mouse.position = (x, y)
        self.sleep(self.s["move_delay"])
        if not self.running():
            return
        self.mouse.press(btn)
        self.mouse.release(btn)
        self.stats.clicks += 1
        self.stats.actions += 1
        self.sleep(self.s["interval"])

    def do_drag(self, node):
        sx, sy = int(node["start_x"]), int(node["start_y"])
        ex, ey = int(node["end_x"]), int(node["end_y"])
        duration = float(node.get("duration", 0.3))
        btn = self.button_of(node)

        self.mouse.position = (sx, sy)
        self.sleep(self.s["move_delay"])
        if not self.running():
            return

        steps = max(int(duration * 100), 1)
        step_delay = duration / steps if duration > 0 else 0

        self.mouse.press(btn)
        try:
            for step in range(steps + 1):
                if not self.running():
                    return
                t = step / float(steps)
                self.mouse.position = (int(sx + (ex - sx) * t),
                                       int(sy + (ey - sy) * t))
                self.sleep(step_delay)
        finally:
            self.mouse.release(btn)
        self.stats.clicks += 1
        self.stats.actions += 1


# ---------------------------------------------------------------- 界面

HELP_TEXT = (
    "• 记录位置：选择操作类型（点击 / 拖动），把鼠标移到目标位置，按 F9 或点「记录位置」\n"
    "• 鼠标左键 / 右键：每个动作各自带按键。设置区的「鼠标按键」是新动作的默认键，\n"
    "  录完之后双击某个动作还能单独改成另一个键（点击和拖动都一样）\n"
    "• 拖动操作：需要按 F9 两次，第一次记起始点，移到终点后第二次按 F9\n"
    "• 新增动作：不想动鼠标时，直接手填坐标加一个动作（坐标默认取当前鼠标位置）\n"
    "• 新建动作组：把一个组当成「一个动作」放进列表，组本身也有循环次数\n"
    "• 嵌套：动作组可以放进动作组里，层级不限\n"
    "• 选中组后再点「记录位置」，新动作会直接加到该组里面\n"
    "• 编辑（双击 / Enter）：弹一个窗口，类型、坐标、点击次数、循环遍数全在里面，改完点确定\n"
    "• 编辑窗口里的「取当前位置」：按下去有 3 秒倒计时，把鼠标移到目标点，自动记坐标\n"
    "• 编辑窗口里能直接把「点击」改成「拖动」（反过来也行），坐标会自动带过去\n"
    "• 复制 / 删除 / 上移 / 下移：列表上右键也有同样的菜单；Delete 删除，Ctrl+D 复制\n"
    "• 移入组 / 移出组：把动作在组和根层之间搬来搬去\n"
    "• 两种「次数」分清楚：点击次数 = 每次连点几下；循环遍数 = 这个动作重复几遍\n"
    "  （点击 (300,500) 连点 3 次、循环 100 遍 = 一共点 300 下；动作组用「循环遍数」）\n"
    "• 统计行：随时告诉你这一套跑一轮有多少下、大概多久、整体乘几轮之后一共多少次\n"
    "• 记录：保存 = 覆盖当前记录，另存为 = 存成新名字，已存记录下拉框可以直接加载/删除\n"
    "• 整体循环次数：整套动作重复几轮，0 = 无限。这就是「最后再全部循环」\n"
    "• F8 / F9 是全局热键：程序在后台、被别的窗口挡住、缩到任务栏都能按\n"
    "  F8 = 开始 / 停止，F9 = 记录位置（编辑窗口开着时 F9 = 取当前鼠标位置）\n"
    "  想只在窗口内生效（怕和别的软件撞车）就把设置区的「全局热键」勾掉\n"
    "  注意：对以管理员身份运行的窗口无效（Windows 会拦普通权限的钩子），\n"
    "  这种情况把本程序也用管理员身份启动即可\n"
)

TAG_COLORS = {
    KIND_GROUP: "#2c3e50",
    KIND_CLICK: "#1e6f5c",
    KIND_DRAG: "#8e44ad",
}


# ---------------------------------------------------------------- 辅助

def parse_int(text, name, minvalue=None):
    """把输入框里的文字转成整数，出错时抛出带中文说明的 ValueError。"""
    text = str(text).strip()
    if not text:
        raise ValueError("「%s」不能为空" % name)
    try:
        value = int(float(text)) if ("." in text) else int(text)
    except ValueError:
        raise ValueError("「%s」要填整数，现在是 %r" % (name, text))
    if minvalue is not None and value < minvalue:
        raise ValueError("「%s」不能小于 %d" % (name, minvalue))
    return value


def parse_float(text, name, minvalue=None):
    text = str(text).strip()
    if not text:
        raise ValueError("「%s」不能为空" % name)
    try:
        value = float(text)
    except ValueError:
        raise ValueError("「%s」要填数字，现在是 %r" % (name, text))
    if minvalue is not None and value < minvalue:
        raise ValueError("「%s」不能小于 %s" % (name, minvalue))
    return value


def place_over(dialog, parent):
    """把对话框摆到父窗口中间偏上的位置，别挡住鼠标常去的地方。"""
    try:
        dialog.update_idletasks()
        w = max(dialog.winfo_width(), dialog.winfo_reqwidth())
        h = max(dialog.winfo_height(), dialog.winfo_reqheight())
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        x = max(0, px + (pw - w) // 2)
        y = max(0, py + max(40, (ph - h) // 3))
        dialog.geometry("+%d+%d" % (x, y))
    except tk.TclError:
        pass


# ---------------------------------------------------------------- 编辑对话框

class PickDialog(tk.Toplevel):
    """从列表里挑一项（用来代替「输入编号」那种要背编号的弹窗）。"""

    def __init__(self, app, title, prompt, items, initial=0):
        tk.Toplevel.__init__(self, app.root)
        self.result = None
        self.title(title)
        self.transient(app.root)
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self.on_cancel)

        pad = ttk.Frame(self, padding=10)
        pad.pack(fill="both", expand=True)
        ttk.Label(pad, text=prompt).pack(anchor="w")
        wrap = ttk.Frame(pad)
        wrap.pack(fill="both", expand=True, pady=(6, 0))
        self.listbox = tk.Listbox(wrap, height=min(12, max(4, len(items))), width=34,
                                  activestyle="none", font=("Microsoft YaHei UI", 9))
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=sb.set)
        self.listbox.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        for text, _ in items:
            self.listbox.insert("end", text)
        if items:
            self.listbox.selection_set(min(initial, len(items) - 1))
            self.listbox.see(min(initial, len(items) - 1))
            self.listbox.activate(min(initial, len(items) - 1))
        self.items = items
        self.listbox.bind("<Double-1>", lambda e: self.on_ok())
        self.bind("<Return>", lambda e: self.on_ok())
        self.bind("<Escape>", lambda e: self.on_cancel())

        bar = ttk.Frame(pad)
        bar.pack(fill="x", pady=(8, 0))
        ttk.Button(bar, text="确定", width=10, command=self.on_ok).pack(side="right")
        ttk.Button(bar, text="取消", width=10, command=self.on_cancel).pack(side="right", padx=6)
        ttk.Label(bar, text="双击 = 确定", style="Hint.TLabel").pack(side="left")

        place_over(self, app.root)
        self.wait_visibility()
        try:
            self.grab_set()
        except tk.TclError:
            pass
        self.listbox.focus_set()
        self.wait_window(self)

    def on_ok(self):
        sel = self.listbox.curselection()
        if sel:
            self.result = self.items[sel[0]][1]
        self.destroy()

    def on_cancel(self):
        self.result = None
        self.destroy()


class NodeEditDialog(tk.Toplevel):
    """「编辑选中」用的单窗口对话框 —— 所有字段一次列全，就地改。

    老写法是连着弹 3~6 个 simpledialog（每个只问一个值：先 X、再 Y、再次数……）。
    只要中间任何一个没弹到最前面、或者焦点跑掉，用户看到的就是
    「点了编辑，只改到了 X」——就成了「功能不全」。
    这里改成：一屏把类型 / 坐标 / 次数 / 时长全列出来，改完点「确定」一次性生效。
    node=None 表示新建动作组。
    """

    def __init__(self, app, node=None, dialog_title=None):
        tk.Toplevel.__init__(self, app.root)
        self.app = app
        self.is_new = node is None
        self.node = node if node is not None else make_group("动作组", 100, [])
        self.result = None                  # 确定后放回最终节点，取消则为 None
        self.vars = {}
        self.frames = {}
        self.kind_radios = []
        self._capture_keys = None
        self._countdown_job = None

        self.kind_var = tk.StringVar(value=self.node.get("kind", KIND_CLICK))
        self.button_var = tk.StringVar(value=norm_button(self.node.get("button")))
        self.preview_var = tk.StringVar(value="")
        self.info_var = tk.StringVar(value="")
        self.err_var = tk.StringVar(value="")

        self.title(dialog_title or ("新建动作组" if self.is_new else "编辑选中"))
        self.transient(app.root)
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self.on_cancel)

        self._build()
        self._load(self.node)
        self._refresh_kind()

        for var in self.vars.values():
            var.trace_add("write", self._on_change)

        place_over(self, app.root)
        self.wait_visibility()
        try:
            self.grab_set()
        except tk.TclError:
            pass
        app._hotkey_lock = True             # 编辑期间暂停 F8/F9，防止误触
        self.focus_force()
        self.wait_window(self)
        app._hotkey_lock = False
        app._f9_hook = None

    # ---------------------------------------------------------- 构建界面

    def _field(self, parent, row, label, key, hint=None, width=9):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="e",
                                           padx=(0, 6), pady=3)
        var = tk.StringVar()
        self.vars[key] = var
        entry = ttk.Entry(parent, textvariable=var, width=width, justify="right")
        entry.grid(row=row, column=1, sticky="w", pady=3)
        if hint:
            ttk.Label(parent, text=hint, foreground="#7f8c8d").grid(
                row=row, column=2, sticky="w", padx=(8, 0))
        return entry

    def _button_field(self, parent, row):
        """鼠标按键单选：每个动作可以自己指定左键 / 右键。"""
        ttk.Label(parent, text="鼠标按键:").grid(row=row, column=0, sticky="e",
                                                padx=(0, 6), pady=3)
        box = ttk.Frame(parent)
        box.grid(row=row, column=1, columnspan=2, sticky="w", pady=3)
        for text, value in (("左键", "left"), ("右键", "right")):
            ttk.Radiobutton(box, text=text, value=value,
                            variable=self.button_var).pack(side="left", padx=(0, 10))
        return box

    def _build(self):
        pad = ttk.Frame(self, padding=10)
        pad.pack(fill="both", expand=True)

        head = ttk.Frame(pad)
        head.pack(fill="x")
        ttk.Label(head, text="类型：").pack(side="left")
        for text, value in (("点击", KIND_CLICK), ("拖动", KIND_DRAG)):
            rb = ttk.Radiobutton(head, text=text, value=value,
                                 variable=self.kind_var, command=self._refresh_kind)
            self.kind_radios.append(rb)
        self.kind_label = ttk.Label(head, text="动作组　（不能改成点击/拖动）",
                                    foreground="#2c3e50")

        body = ttk.Frame(pad)
        body.pack(fill="x")
        self.body = body

        # 按键也进 vars，改一下预览行马上就跟着变
        self.vars["button"] = self.button_var

        # ---- 点击 ----
        f = ttk.LabelFrame(body, text="点击参数", padding=8)
        self.frames[KIND_CLICK] = f
        self._field(f, 0, "X 坐标:", "x")
        self._field(f, 1, "Y 坐标:", "y")
        self._field(f, 2, "点击次数:", "click_count", hint="每次连点几下")
        self._field(f, 3, "循环遍数:", "click_repeat", hint="整个动作重复几遍")
        self._button_field(f, 4)
        ttk.Button(f, text="取当前鼠标位置（3 秒后）",
                   command=lambda: self.start_capture("click")).grid(
            row=5, column=0, columnspan=3, sticky="w", pady=(6, 0))

        # ---- 拖动 ----
        f = ttk.LabelFrame(body, text="拖动参数", padding=8)
        self.frames[KIND_DRAG] = f
        self._field(f, 0, "起始 X:", "start_x")
        self._field(f, 1, "起始 Y:", "start_y")
        self._field(f, 2, "结束 X:", "end_x")
        self._field(f, 3, "结束 Y:", "end_y")
        self._field(f, 4, "持续时间:", "duration", hint="秒")
        self._field(f, 5, "循环遍数:", "drag_repeat", hint="整个拖动重复几遍")
        self._button_field(f, 6)
        btn = ttk.Frame(f)
        btn.grid(row=7, column=0, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Button(btn, text="取起点（3 秒后）",
                   command=lambda: self.start_capture("start")).pack(side="left")
        ttk.Button(btn, text="取终点（3 秒后）",
                   command=lambda: self.start_capture("end")).pack(side="left", padx=6)

        # ---- 动作组 ----
        f = ttk.LabelFrame(body, text="动作组参数", padding=8)
        self.frames[KIND_GROUP] = f
        name_entry = self._field(f, 0, "组名:", "name", width=18)
        name_entry.configure(justify="left")
        self._field(f, 1, "循环遍数:", "group_repeat", hint="0 = 无限循环")
        ttk.Label(f, text="0 = 无限循环：它后面的动作不会再执行，直到手动停止。",
                  foreground="#7f8c8d", wraplength=300, justify="left").grid(
            row=2, column=0, columnspan=3, sticky="w", pady=(6, 0))

        # ---- 预览 / 提示 ----
        ttk.Separator(pad).pack(fill="x", pady=(8, 4))
        ttk.Label(pad, textvariable=self.preview_var, foreground="#2c3e50").pack(anchor="w")
        ttk.Label(pad, textvariable=self.info_var, foreground="#1e6f5c").pack(anchor="w")
        ttk.Label(pad, textvariable=self.err_var, foreground="#c0392b").pack(anchor="w")

        bar = ttk.Frame(pad)
        bar.pack(fill="x", pady=(8, 0))
        ttk.Button(bar, text="确定", width=10, command=self.on_ok).pack(side="right")
        ttk.Button(bar, text="取消", width=10, command=self.on_cancel).pack(side="right", padx=6)
        ttk.Label(bar, text="Enter 确定 / Esc 取消 / F9 取当前位置（全局热键）",
                  foreground="#95a5a6").pack(side="left")

        self.bind("<Return>", lambda e: self.on_ok())
        self.bind("<Escape>", lambda e: self.on_cancel())
        self.bind("<F9>", lambda e: self.grab_position())

    # ---------------------------------------------------------- 数据往返

    def _load(self, node):
        kind = node.get("kind", KIND_CLICK)
        self.kind_var.set(kind)
        repeat = node_repeat(node)
        self.button_var.set(norm_button(node.get("button")))
        if kind == KIND_GROUP:
            self.vars["name"].set(node.get("name", "动作组"))
            self.vars["group_repeat"].set(str(repeat))
            return
        if kind == KIND_CLICK:
            sx, sy = node.get("x", 0), node.get("y", 0)
            ex, ey = sx, sy
            dur = 0.3
        else:
            sx, sy = node.get("start_x", 0), node.get("start_y", 0)
            ex, ey = node.get("end_x", 0), node.get("end_y", 0)
            dur = node.get("duration", 0.3)
        # 点击和拖动的字段互相填好，切换类型时不会丢数据
        self.vars["x"].set(str(sx))
        self.vars["y"].set(str(sy))
        self.vars["click_count"].set(str(node_count(node)))
        self.vars["click_repeat"].set(str(repeat))
        self.vars["start_x"].set(str(sx))
        self.vars["start_y"].set(str(sy))
        self.vars["end_x"].set(str(ex))
        self.vars["end_y"].set(str(ey))
        self.vars["duration"].set(("%g" % float(dur)))
        self.vars["drag_repeat"].set(str(repeat))

    def _collect(self):
        """校验并把当前输入收成一个节点 dict。"""
        kind = self.kind_var.get()
        if kind == KIND_GROUP:
            name = self.vars["name"].get().strip() or "动作组"
            repeat = parse_int(self.vars["group_repeat"].get(), "循环遍数", 0)
            return make_group(name, repeat, [])
        if kind == KIND_CLICK:
            return make_click(parse_int(self.vars["x"].get(), "X 坐标"),
                              parse_int(self.vars["y"].get(), "Y 坐标"),
                              parse_int(self.vars["click_count"].get(), "点击次数", 1),
                              parse_int(self.vars["click_repeat"].get(), "循环遍数", 1),
                              self.button_var.get())
        return make_drag(parse_int(self.vars["start_x"].get(), "起始 X"),
                         parse_int(self.vars["start_y"].get(), "起始 Y"),
                         parse_int(self.vars["end_x"].get(), "结束 X"),
                         parse_int(self.vars["end_y"].get(), "结束 Y"),
                         parse_float(self.vars["duration"].get(), "持续时间", 0.0),
                         parse_int(self.vars["drag_repeat"].get(), "循环遍数", 1),
                         self.button_var.get())

    def _refresh_kind(self):
        kind = self.kind_var.get()
        for frame in self.frames.values():
            frame.pack_forget()
        self.frames[kind].pack(fill="x", pady=(4, 0))
        if kind == KIND_GROUP:
            for rb in self.kind_radios:
                rb.pack_forget()
            self.kind_label.pack(side="left")
        else:
            self.kind_label.pack_forget()
            for rb in self.kind_radios:
                rb.pack(side="left", padx=(0, 8))
        self._refresh_preview()

    def _on_change(self, *_):
        self.err_var.set("")
        self._refresh_preview()

    def _refresh_preview(self, *_):
        try:
            node = self._collect()
        except ValueError:
            self.preview_var.set("预览: —（把数值填完整）")
            return
        if node.get("kind") == KIND_GROUP and self.node.get("kind") == KIND_GROUP:
            node["children"] = self.node.get("children", [])
        self.preview_var.set("预览: " + describe_node(node))

    # ---------------------------------------------------------- 取鼠标位置

    def start_capture(self, which, seconds=3):
        if self._capture_keys is not None:
            return
        self._capture_keys = {"click": ("x", "y"),
                              "start": ("start_x", "start_y"),
                              "end": ("end_x", "end_y")}[which]
        self.info_var.set("")
        self.withdraw()                      # 让开屏幕，能看见目标点
        self.app._hotkey_lock = False        # 倒计时期间 F9 也能手动取点
        self.app._f9_hook = self.grab_position
        self._tick(seconds)

    def _tick(self, left):
        if left <= 0:
            self.grab_position()
            return
        self.app.set_status("状态: %d 秒后记录鼠标位置，请把鼠标移到目标点..." % left)
        self._countdown_job = self.after(1000, lambda: self._tick(left - 1))

    def grab_position(self):
        if self._countdown_job is not None:
            try:
                self.after_cancel(self._countdown_job)
            except Exception:
                pass
            self._countdown_job = None
        keys = self._capture_keys
        if keys is None:
            return
        self._capture_keys = None
        self.app._f9_hook = None
        self.app._hotkey_lock = True
        try:
            x, y = self.app.mouse_controller.position
        except Exception as exc:
            x = y = 0
            self.err_var.set("取鼠标位置失败: %s" % exc)
        x, y = int(x), int(y)
        if keys == ("x", "y"):
            for key, value in (("x", x), ("y", y), ("start_x", x), ("start_y", y)):
                self.vars[key].set(str(value))
        elif keys == ("start_x", "start_y"):
            for key, value in (("start_x", x), ("start_y", y), ("x", x), ("y", y)):
                self.vars[key].set(str(value))
        else:
            self.vars["end_x"].set(str(x))
            self.vars["end_y"].set(str(y))
        self.deiconify()
        self.lift()
        self.focus_force()
        try:
            self.grab_set()
        except tk.TclError:
            pass
        if x or y:
            self.info_var.set("已取到鼠标位置 (%d, %d)" % (x, y))
        self.app.set_status("状态: 已取到鼠标位置 (%d, %d)" % (x, y), force=True)

    # ---------------------------------------------------------- 确定 / 取消

    def on_ok(self):
        try:
            new = self._collect()
        except ValueError as exc:
            self.err_var.set(str(exc))
            return
        node = self.node
        if new.get("kind") == KIND_GROUP:
            new["children"] = node.get("children", [])
        node.clear()
        node.update(new)
        # kind 放到最前面，存盘后看 json 更清楚
        ordered = {"kind": node.pop("kind")}
        ordered.update(node)
        node.clear()
        node.update(ordered)
        self.result = node
        self._close()

    def on_cancel(self):
        self.result = None
        self._close()

    def _close(self):
        if self._countdown_job is not None:
            try:
                self.after_cancel(self._countdown_job)
            except Exception:
                pass
            self._countdown_job = None
        self._capture_keys = None
        self.app._f9_hook = None
        self.app._hotkey_lock = False
        self.destroy()


class GlobalHotkeys(object):
    """全局热键：焦点在任何窗口时 F8 / F9 都能用。

    pynput 的键盘钩子是「旁观」式的 —— 不吞键，也不改变别的程序的行为。
    但 on_press 跑在监听线程里，tkinter 不是线程安全的，所以回调里
    只往队列丢一个键名，由主线程 after 轮询取出来再执行。
    """

    POLL_MS = 40      # 主线程多久去队列里取一次

    def __init__(self, app):
        self.app = app
        self.queue = queue.Queue()
        self.listener = None
        self.ok = False
        self.error = ""
        self._down = set()        # 已按下未松开的键，用来滤掉长按自动重复
        self._job = None

    # ------------------------------------------------------------ 生命周期

    def start(self):
        """挂上钩子，返回是否真的生效。

        pynput 的钩子是在自己的线程里安装的，装失败不会从 start() 抛出，
        所以用 wait() 等它报告 ready —— 失败时会原样抛回来。
        """
        try:
            from pynput import keyboard
            keys = self.hotkey_keys()
        except Exception as exc:                     # pynput 缺失/异常
            self.error = str(exc)
            return False

        on_press, on_release = self.make_handlers(keys)

        try:
            self.listener = keyboard.Listener(on_press=on_press,
                                              on_release=on_release)
            self.listener.daemon = True
            self.listener.start()
            self.listener.wait()                     # 钩子没挂上会在这里抛
        except Exception as exc:
            self.error = str(exc)
            self.stop()
            return False

        self.ok = True
        self._pump()
        return True

    @staticmethod
    def hotkey_keys():
        from pynput.keyboard import Key
        return {Key.f8: "f8", Key.f9: "f9"}

    def make_handlers(self, keys):
        """构造 pynput 的按键回调（单独拿出来是为了能直接测）。"""
        def on_press(key):
            name = keys.get(key)
            if name is None:
                return                               # 其它按键一律不管
            if key in self._down:                    # 长按产生的重复 keydown
                return
            self._down.add(key)
            self.queue.put(name)

        def on_release(key):
            self._down.discard(key)

        return on_press, on_release

    def stop(self):
        if self._job is not None:
            try:
                self.app.root.after_cancel(self._job)
            except Exception:
                pass
            self._job = None
        if self.listener is not None:
            try:
                self.listener.stop()
            except Exception:
                pass
            self.listener = None
        self.ok = False
        self._down.clear()

    # ------------------------------------------------------------ 事件泵

    def _pump(self):
        self._drain()
        self._job = self.app.root.after(self.POLL_MS, self._pump)

    def _drain(self):
        """把队列里攒下的按键交给主线程执行（测试里直接调它）。"""
        while True:
            try:
                name = self.queue.get_nowait()
            except queue.Empty:
                return
            try:
                self.app.on_hotkey(name)
            except Exception as exc:
                self.app.set_status("状态: 热键处理出错 - %s" % exc, force=True)


class MouseClickerApp(object):
    def __init__(self, root):
        self.root = root
        root.title("鼠标编排师 - 分组 · 嵌套循环 · 全局热键")
        root.resizable(True, True)
        root.minsize(820, 640)
        # 居中偏上，别挡住桌面中间的操作区
        width, height = 900, 780
        try:
            sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
            width = min(width, sw - 80)
            height = min(height, sh - 120)
            x = max(0, (sw - width) // 2)
            y = max(0, (sh - height) // 3)
            root.geometry("%dx%d+%d+%d" % (width, height, x, y))
        except tk.TclError:
            root.geometry("%dx%d" % (width, height))

        self.mouse_controller = Controller()

        # 运行状态
        self.is_running = False
        self.click_thread = None
        self._status_cache = ""
        self._status_time = 0.0

        # 动作树：sequence 是根层的动作列表
        self.sequence = []
        self._iid_map = {}        # treeview iid -> node

        # 拖动记录中间态
        self.drag_start = None

        # 编辑对话框打开期间，暂停 F8/F9，避免误触；_f9_hook 用于「取当前位置」
        self._hotkey_lock = False
        self._f9_hook = None

        # 全局热键（F8/F9 在任何窗口上都能用）
        self.hotkeys = None
        self.hotkeys_error = ""
        self._window_hotkeys_bound = False

        self.current_record_name = None
        self.saved_records = {}
        self.records_file = os.path.join(
            os.path.dirname(os.path.abspath(sys.argv[0])),
            "mouse_clicker_records.json")

        self.load_records()
        self.create_ui()
        self.refresh_tree()
        self.setup_hotkeys()
        self.fit_min_size()

    def fit_min_size(self):
        """最小尺寸跟着内容走 —— 免得把窗口缩小到按钮被挤没。

        提示文字会随「全局热键」开关变长变短，所以要等它定下来再量。
        上限压在屏幕高度以内，小屏上也不至于比屏幕还高。
        """
        try:
            self.root.update_idletasks()
            kids = self.root.winfo_children()
            if not kids:
                return
            need_w = kids[0].winfo_reqwidth() + 16
            need_h = kids[0].winfo_reqheight() + 16
            screen_h = self.root.winfo_screenheight()
            need_h = min(need_h, max(520, screen_h - 110))
            self.root.minsize(need_w, need_h)
        except Exception:
            pass

    # ============================================================ UI

    def create_ui(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(".", font=("Microsoft YaHei UI", 9))
        style.configure("Start.TButton", font=("Microsoft YaHei UI", 11, "bold"),
                        padding=(18, 8), foreground="#ffffff", background="#27ae60")
        style.map("Start.TButton",
                  background=[("active", "#1e8f4e"), ("pressed", "#1e8f4e")])
        style.configure("Stop.TButton", font=("Microsoft YaHei UI", 11, "bold"),
                        padding=(18, 8), foreground="#ffffff", background="#c0392b")
        style.map("Stop.TButton",
                  background=[("active", "#a5321f"), ("pressed", "#a5321f")])
        style.configure("Hint.TLabel", foreground="#95a5a6")
        style.configure("Stat.TLabel", foreground="#34495e")

        outer = ttk.Frame(self.root, padding=8)
        outer.pack(fill="both", expand=True)

        # ---------------- 记录管理 ----------------
        rec = ttk.LabelFrame(outer, text="记录", padding=6)
        rec.pack(fill="x")

        top = ttk.Frame(rec)
        top.pack(fill="x")
        self.current_record_var = tk.StringVar(value="当前记录: 未命名")
        ttk.Label(top, textvariable=self.current_record_var).pack(side="left")
        b = ttk.Button(top, text="另存为", width=8, command=self.save_record_as)
        b.pack(side="right", padx=2)
        ToolTip(b, "把当前动作列表存成一个新名字")
        b = ttk.Button(top, text="保存", width=8, command=self.save_record)
        b.pack(side="right", padx=2)
        ToolTip(b, "覆盖保存当前记录（没名字时会让你起一个）")

        bot = ttk.Frame(rec)
        bot.pack(fill="x", pady=(6, 0))
        ttk.Label(bot, text="已存记录:").pack(side="left")
        self.record_combo = ttk.Combobox(bot, state="readonly", width=26)
        self.record_combo.pack(side="left", padx=4)
        self.record_combo.bind("<<ComboboxSelected>>", self.on_record_selected)
        b = ttk.Button(bot, text="加载此记录", command=self.use_selected_record)
        b.pack(side="left", padx=2)
        ToolTip(b, "把下拉框里选中的记录读进来（会覆盖当前动作列表）")
        b = ttk.Button(bot, text="删除此记录", command=self.delete_selected_record)
        b.pack(side="left", padx=2)
        ToolTip(b, "删除下拉框里选中的记录")

        # ---------------- 动作列表 ----------------
        box = ttk.LabelFrame(outer, text="动作列表（支持动作组 / 嵌套循环）", padding=6)
        box.pack(fill="both", expand=True, pady=(8, 0))

        r1 = ttk.Frame(box)
        r1.pack(fill="x")
        ttk.Label(r1, text="操作类型:").pack(side="left")
        self.action_type_var = tk.StringVar(value=KIND_CLICK)
        ttk.Radiobutton(r1, text="点击", value=KIND_CLICK, variable=self.action_type_var,
                        command=self.on_action_type_change).pack(side="left", padx=2)
        ttk.Radiobutton(r1, text="拖动", value=KIND_DRAG, variable=self.action_type_var,
                        command=self.on_action_type_change).pack(side="left", padx=2)
        ttk.Label(r1, text="  点击次数:").pack(side="left")
        self.count_var = tk.StringVar(value="1")
        ttk.Entry(r1, textvariable=self.count_var, width=5, justify="right").pack(side="left")
        ttk.Label(r1, text="次").pack(side="left")
        ttk.Label(r1, text="  拖动时长:").pack(side="left")
        self.drag_duration_var = tk.StringVar(value="0.3")
        ttk.Entry(r1, textvariable=self.drag_duration_var, width=5, justify="right").pack(side="left")
        ttk.Label(r1, text="秒").pack(side="left")
        b = ttk.Button(r1, text="记录位置 (F9)", command=self.record_position)
        b.pack(side="right")
        ToolTip(b, "把鼠标移到目标点再按：点击模式记 1 次，拖动模式按 2 次（起点/终点）")

        r2 = ttk.Frame(box)
        r2.pack(fill="x", pady=(6, 0))
        for text, cmd, tip in (
                ("新增动作", self.add_action, "不移动鼠标，直接手填坐标加一个动作"),
                ("新建动作组", self.add_group, "建一个带循环次数的组，之后记录的动作会进到组里"),
                ("编辑 (Enter)", self.edit_selected, "改类型 / 坐标 / 点击次数 / 循环遍数（双击也行）"),
                ("复制", self.duplicate_selected, "复制一份插到后面"),
                ("删除 (Del)", self.delete_selected, "删除选中项"),
                ("清空", self.clear_all, "清空当前动作列表")):
            b = ttk.Button(r2, text=text, command=cmd)
            b.pack(side="left", padx=2)
            ToolTip(b, tip)

        r3 = ttk.Frame(box)
        r3.pack(fill="x", pady=(6, 0))
        for text, cmd, tip in (
                ("↑ 上移", lambda: self.move_selected(-1), "往上挪一位（Ctrl+↑）"),
                ("↓ 下移", lambda: self.move_selected(1), "往下挪一位（Ctrl+↓）"),
                ("移入组", self.move_into_group, "把这个动作搬进某个组里"),
                ("移出组", self.move_out_group, "把动作从组里搬回上一层"),
                ("组 +1 遍", lambda: self.bump_group_repeat(1), "选中动作组循环次数 +1"),
                ("组 -1 遍", lambda: self.bump_group_repeat(-1), "选中动作组循环次数 -1")):
            b = ttk.Button(r3, text=text, command=cmd)
            b.pack(side="left", padx=2)
            ToolTip(b, tip)

        self.stats_var = tk.StringVar(value="统计: —")
        ttk.Label(box, textvariable=self.stats_var, style="Stat.TLabel").pack(
            anchor="w", pady=(6, 0))
        ttk.Label(box, text="提示: 双击编辑 · 右键出菜单 · Delete 删除 · 选中组后记录会录进组里",
                  style="Hint.TLabel").pack(anchor="w")

        wrap = ttk.Frame(box)
        wrap.pack(fill="both", expand=True, pady=(4, 0))
        self.tree = ttk.Treeview(wrap, show="tree", selectmode="browse", height=10)
        vsb = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        # 树只有一列，默认列宽很短，稍长一点的描述就被截成「点击·左键 (700,…」
        # 这里让列宽跟着可用宽度走，保证每行都完整显示
        self.tree.column("#0", width=760, minwidth=240, stretch=True)
        wrap.bind("<Configure>", self.on_tree_area_resize)
        for kind, color in TAG_COLORS.items():
            self.tree.tag_configure(kind, foreground=color)
        self.tree.tag_configure("running", background="#fdf3d7")
        self.tree.bind("<Double-1>", self.on_tree_double_click)
        self.tree.bind("<Return>", lambda e: self.edit_selected())
        self.tree.bind("<Delete>", lambda e: self.delete_selected())
        self.tree.bind("<Control-d>", lambda e: self.duplicate_selected())
        self.tree.bind("<Control-Up>", lambda e: self.move_selected(-1))
        self.tree.bind("<Control-Down>", lambda e: self.move_selected(1))
        self.tree.bind("<Button-3>", self.popup_menu)

        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label="编辑 / 查看 (Enter)", command=self.edit_selected)
        self.menu.add_command(label="复制", command=self.duplicate_selected)
        self.menu.add_command(label="删除 (Del)", command=self.delete_selected)
        self.menu.add_separator()
        self.menu.add_command(label="上移", command=lambda: self.move_selected(-1))
        self.menu.add_command(label="下移", command=lambda: self.move_selected(1))
        self.menu.add_separator()
        self.menu.add_command(label="移入组...", command=self.move_into_group)
        self.menu.add_command(label="移出组", command=self.move_out_group)
        self.menu.add_separator()
        self.menu.add_command(label="组循环 +1 遍", command=lambda: self.bump_group_repeat(1))
        self.menu.add_command(label="组循环 -1 遍", command=lambda: self.bump_group_repeat(-1))

        # ---------------- 运行设置 ----------------
        st = ttk.LabelFrame(outer, text="设置", padding=6)
        st.pack(fill="x", pady=(8, 0))

        g1 = ttk.Frame(st)
        g1.pack(fill="x")
        ttk.Label(g1, text="点击间隔:").pack(side="left")
        self.interval_var = tk.StringVar(value="0.1")
        ttk.Entry(g1, textvariable=self.interval_var, width=5, justify="right").pack(side="left")
        ttk.Label(g1, text="秒").pack(side="left")

        ttk.Label(g1, text="  移动延迟:").pack(side="left")
        self.move_delay_var = tk.StringVar(value="0.5")
        ttk.Entry(g1, textvariable=self.move_delay_var, width=5, justify="right").pack(side="left")
        ttk.Label(g1, text="秒").pack(side="left")

        self.button_var = tk.StringVar(value="left")
        ttk.Label(g1, text="  鼠标按键:").pack(side="left")
        rb_l = ttk.Radiobutton(g1, text="左键", value="left", variable=self.button_var)
        rb_l.pack(side="left")
        rb_r = ttk.Radiobutton(g1, text="右键", value="right", variable=self.button_var)
        rb_r.pack(side="left")
        ttk.Label(g1, text="（新动作默认键）",
                  style="Hint.TLabel").pack(side="left", padx=(6, 0))
        ToolTip(rb_l, "按 F9 记录新动作时用这个键\n"
                      "已经录好的动作想换键：双击它，在编辑窗口里改")
        ToolTip(rb_r, "按 F9 记录新动作时用这个键\n"
                      "已经录好的动作想换键：双击它，在编辑窗口里改")

        g2 = ttk.Frame(st)
        g2.pack(fill="x", pady=(6, 0))
        ttk.Label(g2, text="整体循环次数:").pack(side="left")
        self.loop_var = tk.StringVar(value="0")
        ttk.Entry(g2, textvariable=self.loop_var, width=5, justify="right").pack(side="left")
        ttk.Label(g2, text="(0=无限)").pack(side="left")

        ttk.Label(g2, text="  启动延迟:").pack(side="left")
        self.delay_var = tk.StringVar(value="3")
        ttk.Entry(g2, textvariable=self.delay_var, width=5, justify="right").pack(side="left")
        ttk.Label(g2, text="秒（留时间把鼠标挪开）").pack(side="left")

        # ---------------- 运行 / 状态 ----------------
        bar = ttk.Frame(outer)
        bar.pack(fill="x", pady=(8, 0))
        self.start_btn = ttk.Button(bar, text="开始点击 (F8)", style="Start.TButton",
                                    command=self.toggle_clicking)
        self.start_btn.pack(side="left")
        ToolTip(self.start_btn, "开始后按 F8 也能停；启动延迟里留了时间把鼠标挪开")
        self.status_var = tk.StringVar(value="状态: 就绪（先记录位置，再按 F8）")
        self.status_label = ttk.Label(bar, textvariable=self.status_var, foreground="#2c3e50")
        self.status_label.pack(side="left", padx=10)

        self.global_hotkey_var = tk.BooleanVar(value=True)
        self.global_hotkey_chk = ttk.Checkbutton(
            bar, text="全局热键", variable=self.global_hotkey_var,
            command=self.toggle_global_hotkeys)
        self.global_hotkey_chk.pack(side="right")
        ToolTip(self.global_hotkey_chk,
                "勾上：切到别的窗口、程序最小化时，F8/F9 一样能按\n"
                "取消：F8/F9 只在点着这个窗口时有效（避免和别的软件冲突）")

        self.hint_var = tk.StringVar(value="")
        self.hint_label = ttk.Label(outer, textvariable=self.hint_var,
                                    style="Hint.TLabel")
        self.hint_label.pack(anchor="w", pady=(4, 0))

        # ---------------- 使用说明 ----------------
        self.help_visible = False
        self.help_btn = ttk.Button(outer, text="使用说明（点开 / 收起）",
                                   command=self.toggle_help)
        self.help_btn.pack(fill="x", pady=(8, 0))
        self.help_frame = tk.Frame(outer, bg="#ecf0f1")
        self.help_label = tk.Label(self.help_frame, text=HELP_TEXT, bg="#ecf0f1",
                                   fg="#2c3e50", justify="left", anchor="w",
                                   font=("Microsoft YaHei UI", 9), padx=8, pady=6)
        self.help_label.pack(fill="x")

        # 设置项一动，统计就跟着刷新
        for var in (self.loop_var, self.interval_var, self.move_delay_var):
            var.trace_add("write", lambda *_: self.update_stats())

    def toggle_help(self):
        if self.help_visible:
            self.help_frame.pack_forget()
            self.help_visible = False
        else:
            self.help_frame.pack(fill="x", after=self.help_btn)
            self.help_visible = True

    def on_action_type_change(self):
        if self.action_type_var.get() == KIND_CLICK:
            self.drag_start = None
            self.set_status("状态: 已切换到点击模式，未完成的拖动记录已清除")

    def on_tree_area_resize(self, event):
        """动作列表宽度变了就跟着调列宽，保证描述不被截断。"""
        try:
            self.tree.column("#0", width=max(240, event.width - 24))
        except tk.TclError:
            pass

    def on_tree_double_click(self, event):
        """双击行 = 编辑；双击空白处不做任何事。"""
        if self.tree.identify_row(event.y):
            self.edit_selected()
        return "break"

    def popup_menu(self, event):
        row = self.tree.identify_row(event.y)
        if not row:
            return "break"
        self.tree.selection_set(row)
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()
        return "break"

    # ============================================================ 树操作

    def refresh_tree(self, select=None):
        """重建树，并尽量保持选中状态（select 可指定要选中的节点）。"""
        if select is None:
            _, select = self.selected_node()

        self.tree.delete(*self.tree.get_children())
        self._iid_map = {}

        def rec(nodes, parent):
            for n in nodes:
                iid = self.tree.insert(parent, "end", text=describe_node(n),
                                       tags=(n.get("kind"),))
                self._iid_map[iid] = n
                if n.get("kind") == KIND_GROUP:
                    self.tree.item(iid, open=True)
                    rec(n.get("children", []), iid)

        rec(self.sequence, "")

        if select is not None:
            iid = self._iid_of(select)
            if iid:
                self.tree.selection_set(iid)
                self.tree.see(iid)

        self.update_stats()
        if count_actions(self.sequence) == 0:
            self.set_status("状态: 就绪（先记录位置，或者「新增动作 / 新建动作组」）")

    def update_stats(self):
        """刷新「这一套跑起来有多少下、大概多久」。"""
        try:
            clicks, drags, infinite = estimate_sequence(self.sequence)
            loop = int(self.loop_var.get())
        except (ValueError, tk.TclError):
            self.stats_var.set("统计: —")
            return
        try:
            settings = {"interval": float(self.interval_var.get() or 0),
                        "move_delay": float(self.move_delay_var.get() or 0)}
        except ValueError:
            settings = {}
        one_round = clicks + drags
        if one_round == 0:
            self.stats_var.set("统计: 还没有动作 —— 按 F9 记录位置，或点「新增动作 / 新建动作组」")
            return
        if drags == 0:
            parts = ["一轮 %d 次点击" % clicks]
        elif clicks == 0:
            parts = ["一轮 %d 次拖动" % drags]
        else:
            parts = ["一轮 %d 次操作（点击 %d / 拖动 %d）" % (one_round, clicks, drags)]
        seconds = estimate_seconds(clicks, drags, settings)
        if seconds:
            parts.append("约 %.1f 秒" % seconds)
        if infinite:
            parts.append("含无限循环")
        if loop == INFINITE:
            parts.append("整体无限循环")
        elif loop > 1:
            parts.append("整体 %d 轮 → 共约 %d 次" % (loop, one_round * loop))
        self.stats_var.set("统计: " + "，".join(parts))

    def selected_node(self):
        sel = self.tree.selection()
        if not sel:
            return None, None
        return sel[0], self._iid_map.get(sel[0])

    def find_container(self, target):
        """返回 (container_list, index, parent_group_node 或 None)。递归找节点在树里的位置。"""
        def rec(nodes, parent_node):
            for i, n in enumerate(nodes):
                if n is target:
                    return nodes, i, parent_node
                if n.get("kind") == KIND_GROUP:
                    r = rec(n.get("children", []), n)
                    if r:
                        return r
            return None

        return rec(self.sequence, None)

    def group_choices(self, exclude=None):
        """列出所有可选的组（含根层）。返回 [(显示名, iid)]"""
        out = [("（根层 / 不在任何组里）", "")]

        def rec(nodes, prefix):
            for n in nodes:
                if n.get("kind") == KIND_GROUP:
                    iid = self._iid_of(n)
                    if iid and n is not exclude:
                        out.append((prefix + n.get("name", "未命名组"), iid))
                        rec(n.get("children", []), prefix + "    ")

        rec(self.sequence, "")
        return out

    def _iid_of(self, node):
        for iid, n in self._iid_map.items():
            if n is node:
                return iid
        return None

    def node_by_iid(self, iid):
        return self._iid_map.get(iid)

    def insert_node(self, node):
        """把新节点插到合适的位置，返回 (位置说明, 刷新后应该选中的节点)。

        规则：
        - 当前选中一个「动作组」 -> 新动作放进该组末尾，并保持选中该组，
          这样可以连续按 F9 往同一个组里录动作。
        - 当前选中一个普通动作 -> 新动作插到它后面（同级），并选中新动作。
        - 什么都没选中 -> 追加到根层末尾，并选中新动作。
        """
        iid, sel = self.selected_node()
        if sel is None:
            self.sequence.append(node)
            return "根层末尾", node
        if sel.get("kind") == KIND_GROUP:
            sel.setdefault("children", []).append(node)
            return "组 '%s' 内" % sel.get("name"), sel
        found = self.find_container(sel)
        if found:
            container, idx, parent = found
            container.insert(idx + 1, node)
            return "同级（紧跟选中项）", node
        self.sequence.append(node)
        return "根层末尾", node

    # ============================================================ 增删改

    def record_position(self):
        if self._f9_hook is not None:
            # 编辑窗口正在「取当前位置」：F9 当作抓坐标用，不新建动作
            self._f9_hook()
            return
        if self._hotkey_lock:
            return                       # 编辑窗口开着，避免误录
        try:
            if self.action_type_var.get() == KIND_CLICK:
                repeat = int(self.count_var.get())
                if repeat < 1:
                    messagebox.showwarning("提示", "每个位置的点击次数至少为 1")
                    return
                x, y = self.mouse_controller.position
                node = make_click(x, y, count=repeat,
                                  button=self.button_var.get())
                where, keep = self.insert_node(node)
                self.refresh_tree(select=keep)
                self.set_status("状态: 已记录点击位置 (%d, %d) 连点%d次，插入到 %s"
                                % (x, y, repeat, where))
            else:
                if self.drag_start is None:
                    x, y = self.mouse_controller.position
                    self.drag_start = (int(x), int(y))
                    self.set_status("状态: 已记录拖动起始位置 (%d, %d)，"
                                    "请移到结束位置后再按 F9" % (x, y))
                    return
                duration = float(self.drag_duration_var.get())
                if duration < 0:
                    messagebox.showwarning("提示", "拖动持续时间不能为负数")
                    return
                sx, sy = self.drag_start
                ex, ey = self.mouse_controller.position
                node = make_drag(sx, sy, ex, ey, duration,
                                 button=self.button_var.get())
                where, keep = self.insert_node(node)
                self.drag_start = None
                self.refresh_tree(select=keep)
                self.set_status("状态: 已记录拖动 (%d, %d) -> (%d, %d)，插入到 %s"
                                % (sx, sy, ex, ey, where))
        except ValueError:
            messagebox.showerror("错误", "请输入有效的数值")
        except Exception as exc:
            messagebox.showerror("错误", "记录位置失败: %s" % exc)

    def add_group(self):
        dlg = NodeEditDialog(self, None)
        node = dlg.result
        if node is None:
            return
        repeat = node_repeat(node)
        where, keep = self.insert_node(node)
        self.refresh_tree(select=keep)
        self.set_status("状态: 已新建动作组 '%s'（循环 %s），插入到 %s；"
                        "接下来按 F9 记录的动作会加进这个组"
                        % (node["name"], "无限" if repeat == INFINITE else "%d 遍" % repeat,
                           where))

    def add_action(self):
        """不移动鼠标，直接手填坐标新增一个动作（坐标可以稍后在窗口里改）。"""
        kind = self.action_type_var.get()
        x, y = self.mouse_controller.position
        try:
            if kind == KIND_CLICK:
                node = make_click(x, y, count=parse_int(self.count_var.get(), "点击次数", 1),
                                  button=self.button_var.get())
                dialog_title = "新增点击动作"
            else:
                node = make_drag(x, y, x, y, parse_float(self.drag_duration_var.get(),
                                                         "拖动时长", 0.0),
                                 button=self.button_var.get())
                dialog_title = "新增拖动动作"
        except ValueError as exc:
            messagebox.showerror("错误", str(exc))
            return
        dlg = NodeEditDialog(self, node, dialog_title)
        if dlg.result is None:
            return
        where, keep = self.insert_node(dlg.result)
        self.refresh_tree(select=keep)
        self.set_status("状态: 已新增 %s（插入到 %s）" % (describe_node(dlg.result), where))

    def edit_selected(self):
        iid, node = self.selected_node()
        if node is None:
            messagebox.showinfo("提示", "请先选中一个动作")
            return
        dlg = NodeEditDialog(self, node)
        if dlg.result is None:
            self.set_status("状态: 已取消编辑")
            return
        self.refresh_tree(select=node)       # 改完保持选中，方便接着改
        self.set_status("状态: 已更新 - %s" % describe_node(node))

    def duplicate_selected(self):
        iid, node = self.selected_node()
        if node is None:
            messagebox.showinfo("提示", "请先选中一个动作")
            return
        found = self.find_container(node)
        if not found:
            return
        container, idx, parent = found
        copy_node = normalize_sequence([copy.deepcopy(node)])[0]
        container.insert(idx + 1, copy_node)
        self.refresh_tree(select=copy_node)
        self.set_status("状态: 已复制一份 - %s" % describe_node(copy_node))

    def delete_selected(self):
        iid, node = self.selected_node()
        if node is None:
            messagebox.showinfo("提示", "请先选中一个动作")
            return
        found = self.find_container(node)
        if not found:
            return
        container, idx, parent = found
        container.pop(idx)
        self.refresh_tree()
        left = count_actions(self.sequence)
        self.set_status("状态: 已删除，剩余 %d 个动作" % left)

    def clear_all(self):
        if not self.sequence:
            return
        if messagebox.askyesno("确认", "确定要清空所有动作吗？"):
            self.sequence = []
            self.drag_start = None
            self.refresh_tree()
            self.set_status("状态: 已清空所有动作")

    def move_selected(self, delta):
        iid, node = self.selected_node()
        if node is None:
            return
        found = self.find_container(node)
        if not found:
            return
        container, idx, parent = found
        new = idx + delta
        if new < 0 or new >= len(container):
            return
        container[idx], container[new] = container[new], container[idx]
        self.refresh_tree()
        new_iid = self._iid_of(node)
        if new_iid:
            self.tree.selection_set(new_iid)
            self.tree.see(new_iid)

    def move_into_group(self):
        iid, node = self.selected_node()
        if node is None:
            messagebox.showinfo("提示", "请先选中一个动作")
            return
        forbid = node if node.get("kind") == KIND_GROUP else None
        choices = self.group_choices(exclude=forbid)
        if len(choices) <= 1:
            messagebox.showinfo("提示", "还没有可以放入的动作组，请先「新建动作组」")
            return
        found = self.find_container(node)
        current_iid = ""
        if found and found[2] is not None:
            current_iid = self._iid_of(found[2]) or ""
        initial = 0
        for i, (_, value) in enumerate(choices):
            if value == current_iid:
                initial = i
        dlg = PickDialog(self, "移入组", "把「%s」放进哪个组？" % describe_node(node),
                         choices, initial=initial)
        if dlg.result is None:
            return
        if dlg.result == current_iid:
            self.set_status("状态: 已经在那个组里了")
            return
        if found:
            found[0].pop(found[1])
        if dlg.result == "":
            self.sequence.append(node)
        else:
            tgt = self.node_by_iid(dlg.result)
            if tgt is not None:
                tgt.setdefault("children", []).append(node)
            else:
                self.sequence.append(node)
        self.refresh_tree(select=node)
        label = "根层"
        for text, value in choices:
            if value == dlg.result:
                label = text.strip()
                break
        self.set_status("状态: 已移动到 '%s'" % label)

    def move_out_group(self):
        iid, node = self.selected_node()
        if node is None:
            return
        found = self.find_container(node)
        if not found:
            return
        container, idx, parent = found
        if parent is None:
            messagebox.showinfo("提示", "该动作已经在根层了")
            return
        container.pop(idx)
        self.sequence.append(node)
        self.refresh_tree()
        self.set_status("状态: 已移出组，放到根层末尾")

    def bump_group_repeat(self, delta):
        iid, node = self.selected_node()
        if node is None or node.get("kind") != KIND_GROUP:
            messagebox.showinfo("提示", "请先选中一个动作组")
            return
        cur = node_repeat(node)
        new = max(0, cur + delta)
        node["repeat"] = new
        self.refresh_tree()
        self.set_status("状态: 组 '%s' 循环次数 -> %s"
                        % (node.get("name"), "无限" if new == 0 else "%d 遍" % new))

    # ============================================================ 记录存取

    def load_records(self):
        if not os.path.exists(self.records_file):
            return
        try:
            with open(self.records_file, "r", encoding="utf-8") as fp:
                self.saved_records = json.load(fp)
        except Exception as exc:
            print("加载记录失败: %s" % exc)
            self.saved_records = {}

    def save_records(self):
        try:
            with open(self.records_file, "w", encoding="utf-8") as fp:
                json.dump(self.saved_records, fp, ensure_ascii=False, indent=2)
        except Exception as exc:
            messagebox.showerror("错误", "保存记录失败: %s" % exc)

    def current_settings(self):
        return {
            "interval": self.interval_var.get(),
            "move_delay": self.move_delay_var.get(),
            "drag_duration": self.drag_duration_var.get(),
            "button": self.button_var.get(),
            "delay": self.delay_var.get(),
            "loop": self.loop_var.get(),
        }

    def store_record(self, name):
        """把当前动作树 + 设置写进某个记录名下。"""
        # 同时写 sequence（新）和 positions（兼容旧版读取）
        self.saved_records[name] = {
            "sequence": copy.deepcopy(self.sequence),
            "positions": copy.deepcopy(self.sequence),
            "settings": self.current_settings(),
        }
        self.save_records()
        self.current_record_name = name
        self.current_record_var.set("当前记录: %s（%d 个动作）"
                                    % (name, count_actions(self.sequence)))
        self.update_record_combo()
        self.record_combo.set(name)
        self.set_status("状态: 已保存记录 '%s'" % name)

    def save_record(self):
        """覆盖保存；还没有名字时先起一个。"""
        if not self.sequence:
            messagebox.showinfo("提示", "当前没有任何动作，没有东西可保存")
            return
        name = self.current_record_name
        if not name:
            return self.save_record_as()
        self.store_record(name)

    def save_record_as(self):
        if not self.sequence:
            messagebox.showinfo("提示", "当前没有任何动作，没有东西可保存")
            return
        default = self.current_record_name or "记录1"
        name = simpledialog.askstring("另存为", "记录名称:", initialvalue=default,
                                      parent=self.root)
        if not name:
            return
        name = name.strip()
        if name in self.saved_records and name != self.current_record_name:
            if not messagebox.askyesno("确认", "记录 '%s' 已存在，是否覆盖？" % name):
                return
        self.store_record(name)

    def delete_selected_record(self):
        name = self.record_combo.get() or self.current_record_name
        if not name or name not in self.saved_records:
            messagebox.showinfo("提示", "先在「已存记录」里选一个要删的记录")
            return
        if not messagebox.askyesno("确认", "删除记录 '%s'？此操作不能撤销。" % name):
            return
        del self.saved_records[name]
        self.save_records()
        if self.current_record_name == name:
            self.current_record_name = None
            self.current_record_var.set("当前记录: 未命名")
        self.update_record_combo()
        self.set_status("状态: 记录 '%s' 已删除" % name)

    def update_record_combo(self):
        names = sorted(self.saved_records.keys())
        self.record_combo["values"] = names
        if names and self.record_combo.get() not in names:
            self.record_combo.set(names[0])

    def on_record_selected(self, event=None):
        name = self.record_combo.get()
        if name:
            data = self.saved_records.get(name, {})
            seq = data.get("sequence") or data.get("positions") or []
            self.set_status("状态: 已选中记录 '%s'（%d 个动作），点「加载此记录」读进来"
                            % (name, count_actions(normalize_sequence(seq))))

    def use_selected_record(self):
        name = self.record_combo.get()
        if not name:
            messagebox.showinfo("提示", "先在「已存记录」里选一个")
            return
        if self.sequence and not messagebox.askyesno(
                "确认", "加载记录 '%s' 会替换当前动作列表，继续？" % name):
            return
        self.load_record(name)

    def load_record(self, name):
        if name not in self.saved_records:
            messagebox.showerror("错误", "记录 '%s' 不存在" % name)
            return
        data = self.saved_records[name]
        seq = data.get("sequence") or data.get("positions") or []
        self.sequence = normalize_sequence(seq)
        st = data.get("settings", {})
        if st:
            self.interval_var.set(str(st.get("interval", self.interval_var.get())))
            self.move_delay_var.set(str(st.get("move_delay", self.move_delay_var.get())))
            self.drag_duration_var.set(str(st.get("drag_duration", self.drag_duration_var.get())))
            self.button_var.set(st.get("button", self.button_var.get()))
            self.delay_var.set(str(st.get("delay", self.delay_var.get())))
            self.loop_var.set(str(st.get("loop", self.loop_var.get())))
        self.current_record_name = name
        self.current_record_var.set("当前记录: %s（%d 个动作）"
                                    % (name, count_actions(self.sequence)))
        self.record_combo.set(name)
        self.refresh_tree()
        self.set_status("状态: 已加载记录 '%s'，共 %d 个动作"
                        % (name, count_actions(self.sequence)))

    # ============================================================ 运行

    def validate_inputs(self):
        if not self.sequence:
            messagebox.showerror("错误", "请先至少记录一个动作或新建一个动作组！")
            return None
        try:
            interval = float(self.interval_var.get())
            if interval < 0.01:
                messagebox.showerror("错误", "点击间隔不能小于 0.01 秒")
                return None
        except ValueError:
            messagebox.showerror("错误", "请输入有效的点击间隔（正数，最小 0.01 秒）")
            return None
        try:
            move_delay = float(self.move_delay_var.get())
            if move_delay < 0:
                messagebox.showerror("错误", "位置移动延迟不能为负数")
                return None
        except ValueError:
            messagebox.showerror("错误", "请输入有效的位置移动延迟（非负数）")
            return None
        try:
            start_delay = float(self.delay_var.get())
            if start_delay < 0:
                messagebox.showerror("错误", "启动延迟不能为负数")
                return None
        except ValueError:
            messagebox.showerror("错误", "请输入有效的启动延迟（非负数）")
            return None
        try:
            loop = int(self.loop_var.get())
            if loop < 0:
                messagebox.showerror("错误", "循环次数不能为负数")
                return None
        except ValueError:
            messagebox.showerror("错误", "请输入有效的循环次数（非负整数，0 表示无限循环）")
            return None
        if self.action_type_var.get() == KIND_DRAG and self.drag_start is not None:
            messagebox.showerror("错误", "你有一个未完成的拖动记录，请先按 F9 完成或切换回点击模式")
            return None

        # 无限循环的组如果后面还有动作，提醒一下
        def warn_infinite(nodes):
            for i, n in enumerate(nodes):
                if n.get("kind") == KIND_GROUP:
                    if node_repeat(n) == INFINITE and i < len(nodes) - 1:
                        return n
                    r = warn_infinite(n.get("children", []))
                    if r:
                        return r
            return None

        bad = warn_infinite(self.sequence)
        if bad is not None:
            if not messagebox.askyesno("提示",
                                       "动作组 '%s' 设为无限循环，它后面的动作不会被执行。\n"
                                       "确定要继续吗？" % bad.get("name", "")):
                return None

        return {"interval": interval, "move_delay": move_delay,
                "start_delay": start_delay, "loop": loop}

    # ============================================================ 全局热键

    def setup_hotkeys(self):
        """挂全局键盘钩子；挂不上就退回「只在自己窗口里有效」。"""
        if self.hotkeys is not None:
            return
        if not self.global_hotkey_var.get():
            self._bind_window_hotkeys()
            self.set_hint("F8 开始/停止 · F9 记录位置（仅窗口内有效）")
            return
        hk = GlobalHotkeys(self)
        if hk.start():
            self.hotkeys = hk
            self.hotkeys_error = ""
            self._unbind_window_hotkeys()      # 交给全局钩子，免得同一次按键走两遍
            self.set_hint("F8 开始/停止 · F9 记录位置（全局热键，后台也有效）")
        else:
            self.hotkeys_error = hk.error
            self._bind_window_hotkeys()
            self.set_hint("F8 开始/停止 · F9 记录位置（仅窗口内有效）")
            self.set_status("状态: 全局热键启用失败 - %s" % hk.error, force=True)

    def on_hotkey(self, name):
        """热键入口（始终在主线程执行）。"""
        if name == "f8":
            self.toggle_clicking()
        elif name == "f9":
            self.record_position()

    def toggle_global_hotkeys(self):
        want = bool(self.global_hotkey_var.get())
        if self.hotkeys is not None:
            self.hotkeys.stop()
            self.hotkeys = None
        if want:
            self.setup_hotkeys()
            if self.hotkeys is not None:
                self.set_status("状态: 全局热键已启用（切到别的窗口也能按 F8/F9）",
                                force=True)
        else:
            self._bind_window_hotkeys()
            self.set_hint("F8 开始/停止 · F9 记录位置（仅窗口内有效）")
            self.set_status("状态: 全局热键已关闭，F8/F9 只在窗口内有效", force=True)

    # 全局钩子用不了时的兜底：只在窗口有焦点时响应
    def _bind_window_hotkeys(self):
        if self._window_hotkeys_bound:
            return
        self.root.bind("<F8>", lambda e: self.on_hotkey("f8"))
        self.root.bind("<F9>", lambda e: self.on_hotkey("f9"))
        self._window_hotkeys_bound = True

    def _unbind_window_hotkeys(self):
        if not self._window_hotkeys_bound:
            return
        self.root.unbind("<F8>")
        self.root.unbind("<F9>")
        self._window_hotkeys_bound = False

    def set_hint(self, text):
        try:
            self.hint_var.set("提示: " + text)
        except Exception:
            pass

    def shutdown(self):
        """退出前把键盘钩子摘干净。"""
        if self.hotkeys is not None:
            self.hotkeys.stop()
            self.hotkeys = None

    def toggle_clicking(self):
        if self._hotkey_lock:
            self.set_status("状态: 编辑窗口打开中，F8/F9 已暂停", force=True)
            return
        if self.is_running:
            self.stop_clicking()
        else:
            self.start_clicking()

    def start_clicking(self):
        settings = self.validate_inputs()
        if settings is None:
            return
        button = Button.left if self.button_var.get() == "left" else Button.right
        self.is_running = True
        self.start_btn.configure(text="停止点击 (F8)", style="Stop.TButton")
        self.set_status("状态: 准备中...", force=True)
        runner = ActionRunner(self, copy.deepcopy(self.sequence), settings, button)
        self.click_thread = threading.Thread(target=self._run_wrapper, args=(runner,), daemon=True)
        self.click_thread.start()

    def _run_wrapper(self, runner):
        try:
            runner.run()
        except Exception as exc:
            self.set_status("状态: 发生错误 - %s" % exc, force=True)
        finally:
            self.finish_run(runner)

    def stop_clicking(self):
        self.is_running = False
        self.set_status("状态: 已停止", force=True)

    def finish_run(self, runner):
        self.is_running = False
        st = runner.stats
        try:
            if st.loops and st.loops >= (runner.s["loop"] or 0) and runner.s["loop"] != INFINITE:
                text = ("状态: 完成！共 %d 轮循环，%d 个动作，鼠标操作 %d 次"
                        % (st.loops, st.actions, st.clicks))
            else:
                text = ("状态: 已停止！共 %d 轮循环，%d 个动作，鼠标操作 %d 次"
                        % (st.loops, st.actions, st.clicks))
        except Exception:
            text = "状态: 已结束"
        self.set_status(text, force=True)
        try:
            self.root.after(0, lambda: self.start_btn.configure(
                text="开始点击 (F8)", style="Start.TButton"))
        except Exception:
            pass

    # ============================================================ 状态栏

    def set_status(self, text, force=False):
        """后台线程调用安全；做节流，避免刷爆 Tk 事件队列。"""
        now = time.time()
        if not force:
            if text == self._status_cache and now - self._status_time < 0.2:
                return
            if now - self._status_time < 0.03:
                return
        self._status_cache = text
        self._status_time = now
        if "错误" in text or "失败" in text or "已停止" in text:
            color = "#c0392b"
        elif "完成" in text:
            color = "#27ae60"
        elif "已记录" in text or "已更新" in text or "已新增" in text or "取到" in text:
            color = "#1e6f5c"
        else:
            color = "#2c3e50"

        def apply():
            try:
                self.status_var.set(text)
                self.status_label.configure(foreground=color)
            except tk.TclError:
                pass

        try:
            self.root.after(0, apply)
        except Exception:
            pass


def main():
    root = tk.Tk()
    app = MouseClickerApp(root)
    try:
        root.mainloop()
    finally:
        app.shutdown()      # 摘掉键盘钩子，别让进程拖着不退


if __name__ == "__main__":
    main()
