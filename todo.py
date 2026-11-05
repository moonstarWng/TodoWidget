# -*- coding: utf-8 -*-
"""桌面待办清单 —— 托盘常驻 + 贴桌面的轻量 Todo 小组件

用法:
    pyw -3 todo.py            # 启动(无黑框)
    py -3 todo.py --console   # 带控制台启动, 便于看报错

交互:
    点左边的框         勾选/取消勾选 (组会自动连带所有子项)
    双击文字            弹出便签, 记点相关的东西
    拖动行              调整顺序; 拖到组的中间 = 变成它的子项
    F2 / 右键          改名
    Insert              新建任务
    Ctrl+Insert         新建子任务
    Delete              删除
    空格                勾选当前行
    右键                更多操作
    右下角 ⚙            设置配色

两种形态(托盘右键切换):
    贴到桌面   无边框, 不占任务栏, 失去焦点后沉到桌面底层
    普通窗口   带标题栏, 出现在任务栏, 可最大化
"""

import ctypes
import ctypes.wintypes
import json
import os
import re
import sys
import threading
import time
import uuid
import webbrowser
from datetime import datetime

import tkinter as tk
from tkinter import font as tkfont
from tkinter import messagebox, ttk

try:
    import pystray
    from PIL import Image, ImageChops, ImageDraw, ImageTk

    HAS_TRAY = True
except Exception:  # 没装 pystray/pillow 也能跑, 只是没有托盘
    HAS_TRAY = False

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(APP_DIR, "todo_data.json")
CONF_FILE = os.path.join(APP_DIR, "todo_config.json")

# ---------- 配色(可切换) ----------
THEMES = {
    "dark": dict(
        bg="#17181d", bg_alt="#1e2027", head="#131418", border="#2b2e38",
        group_bg="#202330", hover="#2c3242", fg="#e8e9ee", fg_dim="#8b8d99",
        fg_faint="#555863", accent="#5b9cff", done="#5c6070",
        group="#ffffff", sel="#2d4c7d"),
    "light": dict(
        bg="#f7f8fa", bg_alt="#eceef2", head="#ffffff", border="#dcdfe6",
        group_bg="#eaeef7", hover="#e2e8f5", fg="#23252b", fg_dim="#6c7181",
        fg_faint="#a2a8b4", accent="#3b7cf6", done="#a3a7b3",
        group="#15171c", sel="#cfddfb"),
    "forest": dict(
        bg="#131a17", bg_alt="#18211d", head="#0e1512", border="#26332c",
        group_bg="#1b2621", hover="#22322a", fg="#e6efe9", fg_dim="#89a294",
        fg_faint="#4f6157", accent="#43c08a", done="#5a6b62",
        group="#ffffff", sel="#1f4636"),
    "sand": dict(
        bg="#1d1a16", bg_alt="#26221c", head="#161310", border="#3a342b",
        group_bg="#262119", hover="#302a20", fg="#f0e9de", fg_dim="#a2978a",
        fg_faint="#6a6053", accent="#e0a458", done="#6b6257",
        group="#fff8ee", sel="#4a3a24"),
}

THEME_NAMES = (("dark", "深色"), ("light", "浅色"),
               ("forest", "墨绿"), ("sand", "暖沙"))

C_BG = "#17181d"
C_BG_ALT = "#1e2027"
C_HEAD = "#131418"
C_BORDER = "#2b2e38"
C_GROUP_BG = "#202330"
C_HOVER = "#2c3242"
C_FG = "#e8e9ee"
C_FG_DIM = "#8b8d99"
C_FG_FAINT = "#555863"
C_ACCENT = "#5b9cff"
C_DONE = "#5c6070"
C_GROUP = "#ffffff"
C_SEL = "#2d4c7d"
C_GHOST_BG = "#2f5fa8"

# ---------- 便签配色(有意跟主窗体区分开: 米黄纸) ----------
NOTE_BG = "#f7ebc9"
NOTE_HEAD = "#ecdcae"
NOTE_FG = "#33302a"
NOTE_DIM = "#857a5f"
NOTE_EDGE = "#c9b481"
NOTE_CODE = "#ead9a9"
NOTE_MARK = "#a8863f"
NOTE_LINK = "#1a56a8"

LINK_RE = re.compile(r"(?:https?://|www\.)[^\s<>\"'\u3000]+")
LINK_TAIL = ".,;:!?)]}\u3002\uff0c\u3001\uff09\u300b"


class MonitorInfo(ctypes.Structure):
    """win32 的 MONITORINFO, 用来算便签该摆在哪个屏幕中间"""

    _fields_ = [
        ("cbSize", ctypes.c_ulong),
        ("rcMonitor", ctypes.wintypes.RECT),
        ("rcWork", ctypes.wintypes.RECT),
        ("dwFlags", ctypes.c_ulong),
    ]


def set_theme(name, accent=None):
    """切换配色, 同时更新本模块的颜色常量"""
    global C_BG, C_BG_ALT, C_HEAD, C_BORDER, C_GROUP_BG, C_HOVER
    global C_FG, C_FG_DIM, C_FG_FAINT, C_ACCENT, C_DONE, C_GROUP, C_SEL
    global C_GHOST_BG

    theme = THEMES.get(name)
    if theme is None:
        theme = THEMES["dark"]

    C_BG = theme["bg"]
    C_BG_ALT = theme["bg_alt"]
    C_HEAD = theme["head"]
    C_BORDER = theme["border"]
    C_GROUP_BG = theme["group_bg"]
    C_HOVER = theme["hover"]
    C_FG = theme["fg"]
    C_FG_DIM = theme["fg_dim"]
    C_FG_FAINT = theme["fg_faint"]
    C_DONE = theme["done"]
    C_GROUP = theme["group"]
    C_SEL = theme["sel"]

    if accent:
        C_ACCENT = accent
    else:
        C_ACCENT = theme["accent"]
    C_GHOST_BG = C_ACCENT


set_theme("dark")

BOX_OFF = "\u2610"  # ☐
BOX_ON = "\u2611"  # ☑

FONTS = ("Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", "TkDefaultFont")


def pick_font(root, size, weight="normal", overstrike=False):
    families = set(tkfont.families(root))
    family = next((f for f in FONTS if f in families), "TkDefaultFont")
    return tkfont.Font(root=root, family=family, size=size,
                       weight=weight, overstrike=overstrike)


def new_item(text):
    return {"id": uuid.uuid4().hex[:8], "text": text, "done": False,
            "children": [], "open": True}


def open_url(url):
    """用系统默认浏览器打开链接"""
    if not url:
        return False
    if url.lower().startswith("www."):
        url = "http://" + url
    try:
        os.startfile(url)
        return True
    except Exception:
        pass
    try:
        return webbrowser.open(url)
    except Exception:
        return False


def best_text_color(hex_color):
    """深色底配白字, 浅色底配黑字"""
    red, green, blue = hex_to_rgb(hex_color)
    brightness = (red * 299 + green * 587 + blue * 114) / 1000
    if brightness > 150:
        return "#1c1d22"
    return "#ffffff"


def place_window(window, x, y, width, height):
    """把无边框窗口摆到指定位置(只动窗口本身, 不涉及鼠标键盘)"""
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetParent(window.winfo_id())
        if not hwnd:
            hwnd = window.winfo_id()
        flags = 0x0004 | 0x0010 | 0x0040  # NOZORDER | NOACTIVATE | SHOWWINDOW
        user32.SetWindowPos(hwnd, 0, int(x), int(y), int(width), int(height),
                            flags)
        return True
    except Exception:
        return False


class FakeEvent:
    """测试用的事件对象, 字段和 Tk 事件保持一致"""

    def __init__(self, widget, x, y):
        self.widget = widget
        self.x = x
        self.y = y
        try:
            self.x_root = widget.winfo_rootx() + x
            self.y_root = widget.winfo_rooty() + y
        except Exception:
            self.x_root = x
            self.y_root = y


# --------------------------------------------------------------------------
# 数据
# --------------------------------------------------------------------------
class Store:
    """多份清单; 每份清单是 {id, name, items}"""

    def __init__(self, path=DATA_FILE):
        self.path = path
        self.lists = []
        self.current = ""
        self.load()

    @property
    def items(self):
        lst = self.current_list()
        if lst is None:
            return []
        return lst["items"]

    def current_list(self):
        for lst in self.lists:
            if lst["id"] == self.current:
                return lst
        if self.lists:
            return self.lists[0]
        return None

    def current_name(self):
        lst = self.current_list()
        if lst is None:
            return "待办"
        return lst["name"]

    def select(self, list_id):
        for lst in self.lists:
            if lst["id"] == list_id:
                self.current = list_id
                return True
        return False

    def add_list(self, name):
        clean = (name or "").strip() or "新清单"
        lst = {"id": uuid.uuid4().hex[:8], "name": clean, "items": []}
        self.lists.append(lst)
        self.current = lst["id"]
        return lst

    def rename_list(self, list_id, name):
        clean = (name or "").strip()
        if not clean:
            return False
        for lst in self.lists:
            if lst["id"] == list_id:
                lst["name"] = clean
                return True
        return False

    def delete_list(self, list_id):
        if len(self.lists) <= 1:
            return False
        left = []
        for lst in self.lists:
            if lst["id"] != list_id:
                left.append(lst)
        if len(left) == len(self.lists):
            return False
        self.lists = left
        if self.current == list_id:
            self.current = self.lists[0]["id"]
        return True

    def load(self):
        if not os.path.exists(self.path):
            self.lists = [{"id": uuid.uuid4().hex[:8], "name": "待办",
                           "items": seed_data()}]
            self.current = self.lists[0]["id"]
            self.save()
            return

        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}

        lists = data.get("lists")
        if isinstance(lists, list) and lists:
            self.lists = lists
            for lst in self.lists:
                if not lst.get("id"):
                    lst["id"] = uuid.uuid4().hex[:8]
                if not lst.get("name"):
                    lst["name"] = "待办"
                if not isinstance(lst.get("items"), list):
                    lst["items"] = []
            self.current = data.get("current") or self.lists[0]["id"]
            if self.current_list() is None:
                self.current = self.lists[0]["id"]
            return

        old_items = data.get("items")
        if isinstance(old_items, list):
            # 老版本是单清单格式, 平滑升级成一份叫做"待办"的清单
            self.lists = [{"id": uuid.uuid4().hex[:8], "name": "待办",
                           "items": old_items}]
            self.current = self.lists[0]["id"]
            self.save()
            return

        self.lists = [{"id": uuid.uuid4().hex[:8], "name": "待办", "items": []}]
        self.current = self.lists[0]["id"]

    def save(self):
        if not self.lists:
            self.lists = [{"id": uuid.uuid4().hex[:8], "name": "待办",
                           "items": []}]
            self.current = self.lists[0]["id"]
        if self.current_list() is None:
            self.current = self.lists[0]["id"]

        data = {"updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "current": self.current,
                "lists": self.lists}
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)


def seed_data():
    """首次启动时的示例清单"""
    src = [
        ("开始使用", ["点左边的框勾选", "双击任务写便签", "拖动行可以排序"]),
        ("这些也可以试试", ["左上角清单名: 切换 / 新建清单",
                          "右上角 ▾: 折叠成一条横杠", "右下角 ⚙: 换配色"]),
    ]
    out = []
    for title, kids in src:
        it = new_item(title)
        it["children"] = [new_item(k) for k in kids]
        out.append(it)
    return out


def walk(items, parent=None):
    """深度遍历, 产出 (item, 所在列表)"""
    for it in items:
        yield it, items
        yield from walk(it.get("children") or [])


def leaf_stats(item):
    done = total = 0
    for it, _ in walk([item]):
        if it is item:
            continue
        if not it.get("children"):
            total += 1
            done += 1 if it.get("done") else 0
    return done, total


# --------------------------------------------------------------------------
# 主界面
# --------------------------------------------------------------------------
class TodoApp:
    def __init__(self, root, store=None):
        self.root = root
        self.store = store or Store()
        self.conf = self.load_conf()
        self.mode = self.conf.get("mode", "desktop")
        self.topmost = bool(self.conf.get("topmost", True))
        self.alpha = float(self.conf.get("alpha", 1.0))
        self._refs = {}
        self._editor = None
        self._drag = None
        self._drag_src = None
        self._drag_xy = (0, 0)
        self._dragging = False
        self._drop = None
        self._marked = None
        self._hover = None
        self._press_box = None
        self._ghost = None
        self._finish_edit = None
        self._tray = None
        self.collapsed = False
        self._expanded_size = None
        self.tab = self.conf.get("tab", "pending")
        self.theme = self.conf.get("theme", "dark")
        self.accent = self.conf.get("accent") or None
        self.settings_win = None
        self.note_win = None
        self.note_text = None
        self.note_item = None
        self.note_raw = ""
        self.note_editing = True
        self._note_link_job = None
        self.prompt_win = None
        self._drag_from = (0, 0)
        self._drag_moved = False

        set_theme(self.theme, self.accent)
        self.build_ui()
        self.normalize()
        self.refresh()
        folded = bool(self.conf.get("collapsed"))
        self.apply_window()
        if folded:
            self.set_folded(True)
        self.start_tray()

    # ---------------- 配置 ----------------
    def load_conf(self):
        try:
            with open(CONF_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def save_conf(self):
        self.conf.update(mode=self.mode, topmost=self.topmost, alpha=self.alpha,
                         collapsed=bool(self.collapsed), tab=self.tab,
                         theme=self.theme, accent=self.accent)
        try:
            with open(CONF_FILE, "w", encoding="utf-8") as f:
                json.dump(self.conf, f, ensure_ascii=False, indent=1)
        except Exception:
            pass

    def save_geom(self):
        if self.root.state() != "normal":
            return
        w, h = self.root.winfo_width(), self.root.winfo_height()
        if self.collapsed and self._expanded_size:
            w, h = self._expanded_size
        self.conf["geom"] = "{}x{}+{}+{}".format(w, h, self.root.winfo_x(),
                                                 self.root.winfo_y())
        self.save_conf()

    # ---------------- 界面 ----------------
    def build_ui(self):
        r = self.root
        is_desktop = self.mode == "desktop"
        r.title("待办清单")
        r.configure(bg=C_BORDER)
        r.overrideredirect(is_desktop)
        r.minsize(270, 220)

        self.f_title = pick_font(r, 11, "bold")
        self.f_group = pick_font(r, 10, "bold")
        self.f_group_done = pick_font(r, 10, "bold", True)
        self.f_item = pick_font(r, 10)
        self.f_item_done = pick_font(r, 10, overstrike=True)
        self.f_small = pick_font(r, 8)
        self.f_note_h1 = pick_font(r, 13, "bold")
        self.f_note_h2 = pick_font(r, 11, "bold")
        self.f_note_bold = pick_font(r, 10, "bold")

        # 外层留 1px 当描边
        inner = tk.Frame(r, bg=C_BG)
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        self.inner = inner

        # 勾选框用小图片画, 比字符清楚, 也方便只点框勾选
        self.img_on = self.make_box(True)
        self.img_off = self.make_box(False)

        # ---- 顶栏 ----
        head = tk.Frame(inner, bg=C_HEAD, height=40)
        head.pack(fill="x", side="top")
        head.pack_propagate(False)
        self._head = head

        self.lbl_title = tk.Label(head, text="待办", bg=C_HEAD, fg=C_FG,
                                  font=self.f_title, cursor="hand2")
        self.lbl_title.pack(side="left", padx=(14, 8))
        self.lbl_stat = tk.Label(head, text="", bg=C_HEAD, fg=C_FG_DIM,
                                 font=self.f_small)
        self.lbl_stat.pack(side="left", pady=(3, 0))

        def icon_btn(text, cmd):
            b = tk.Label(head, text=text, bg=C_HEAD, fg=C_FG_DIM,
                         font=self.f_item, width=2, cursor="hand2")
            b.pack(side="right", padx=(0, 4), pady=8)
            b.bind("<Button-1>", lambda e, c=cmd: c())
            b.bind("<Enter>", lambda e, w=b: w.configure(fg=C_FG, bg=C_BG_ALT))
            b.bind("<Leave>", lambda e, w=b: w.configure(fg=C_FG_DIM, bg=C_HEAD))
            return b

        icon_btn("\u2715", self.hide)
        icon_btn("\uff0b", self.add_top)
        self.btn_fold = icon_btn("\u25b4", self.toggle_fold)

        # 总进度条
        track = tk.Frame(inner, bg=C_BORDER, height=2)
        track.pack(fill="x", side="top")
        track.pack_propagate(False)
        self._track = track
        self.pbar = tk.Frame(track, bg=C_ACCENT, height=2)
        self.pbar.place(x=0, y=0, relheight=1, relwidth=0)

        # ---- 未完成 / 已完成 两个页签 ----
        tabbar = tk.Frame(inner, bg=C_BG, height=34)
        tabbar.pack(fill="x", side="top")
        tabbar.pack_propagate(False)
        self._tabbar = tabbar
        self.f_tab = pick_font(r, 9, "bold")
        self.tab_labels = {}
        self.tab_bars = {}
        for key, text in (("pending", "未完成"), ("done", "已完成")):
            cell = tk.Frame(tabbar, bg=C_BG, cursor="hand2")
            cell.pack(side="left", padx=(12, 6), pady=(6, 0))
            lbl = tk.Label(cell, text=text, bg=C_BG, fg=C_FG_DIM,
                           font=self.f_tab, cursor="hand2")
            lbl.pack()
            bar = tk.Frame(cell, bg=C_BG, height=2)
            bar.pack(fill="x", pady=(4, 0))
            for w in (cell, lbl):
                w.bind("<Button-1>", lambda e, k=key: self.set_tab(k))
            self.tab_labels[key] = lbl
            self.tab_bars[key] = bar

        def start_drag(e):
            self._drag_from = (e.x_root, e.y_root)
            self._drag = (e.x_root - r.winfo_x(), e.y_root - r.winfo_y())
            self._drag_moved = False

        def on_drag(e):
            if not self._drag:
                return
            move_x = abs(e.x_root - self._drag_from[0])
            move_y = abs(e.y_root - self._drag_from[1])
            if move_x > 3 or move_y > 3:
                self._drag_moved = True
            r.geometry("+{}+{}".format(e.x_root - self._drag[0],
                                       e.y_root - self._drag[1]))

        def end_drag(e, as_click=False):
            moved = getattr(self, "_drag_moved", False)
            self._drag = None
            self._drag_moved = False
            self.save_geom()
            if as_click and not moved:
                self.open_list_menu(e)

        for widget in (head, self.lbl_stat):
            widget.bind("<Button-1>", start_drag)
            widget.bind("<B1-Motion>", on_drag)
            widget.bind("<ButtonRelease-1>", lambda ev: end_drag(ev))
            widget.bind("<Button-3>", self.popup_header)

        # 左上角的清单名: 点一下下拉, 按住拖动则是挪窗口
        self.lbl_title.bind("<Button-1>", start_drag)
        self.lbl_title.bind("<B1-Motion>", on_drag)
        self.lbl_title.bind("<ButtonRelease-1>", lambda ev: end_drag(ev, True))
        self.lbl_title.bind("<Button-3>", self.popup_header)
        head.bind("<Double-Button-1>", lambda e: self.toggle_collapse_all())

        # ---- 列表 ----
        body = tk.Frame(inner, bg=C_BG)
        body.pack(fill="both", expand=True, padx=(6, 3), pady=(6, 0))
        self._body = body

        style = ttk.Style(r)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.layout("Todo.Treeview", [("Todo.Treeview.treearea", {"sticky": "nswe"})])
        style.configure("Todo.Treeview", background=C_BG, fieldbackground=C_BG,
                        foreground=C_FG, borderwidth=0, relief="flat",
                        indent=18, rowheight=28, font=self.f_item)
        style.map("Todo.Treeview", background=[("selected", C_SEL)],
                  foreground=[("selected", "#ffffff")])
        style.layout("Todo.Vertical.TScrollbar", [
            ("Vertical.Scrollbar.trough", {"sticky": "ns", "children": [
                ("Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})]})])
        style.configure("Todo.Vertical.TScrollbar", background=C_BORDER,
                        troughcolor=C_BG, bordercolor=C_BG, arrowcolor=C_FG_DIM,
                        darkcolor=C_BORDER, lightcolor=C_BORDER,
                        relief="flat", width=7)

        self.tree = ttk.Treeview(body, show="tree", style="Todo.Treeview",
                                 selectmode="browse")
        sb = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview,
                           style="Todo.Vertical.TScrollbar")
        self.scroll = sb
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y", pady=2)
        self.tree.pack(side="left", fill="both", expand=True)

        # Treeview 的 tag 优先级跟定义顺序有关, 混着用会串色,
        # 所以每行的状态只用一个 tag, 悬停/拖放都是独立的一套
        base_cfg = {
            "group": dict(font=self.f_group, foreground=C_GROUP,
                          background=C_GROUP_BG),
            "group_done": dict(font=self.f_group_done, foreground=C_DONE,
                               background=C_GROUP_BG),
            "item": dict(font=self.f_item, foreground=C_FG),
            "item_done": dict(font=self.f_item_done, foreground=C_DONE),
        }
        for name, cfg in base_cfg.items():
            self.tree.tag_configure(name, **cfg)
            hover = dict(cfg, background=C_HOVER)
            self.tree.tag_configure(name + "_h", **hover)
            drop = dict(cfg, background="#4a3f22")
            self.tree.tag_configure("drop_" + name, **drop)
        self.tree.tag_configure("empty", font=self.f_item, foreground=C_FG_FAINT)

        self.tree.bind("<space>", lambda e: self.toggle(self.tree.focus()))
        self.tree.bind("<Double-1>", self.on_double_click)
        self.tree.bind("<Insert>", lambda e: self.add_sibling())
        self.tree.bind("<Control-Insert>", lambda e: self.add_child())
        self.tree.bind("<Control-Return>", lambda e: self.add_child())
        self.tree.bind("<Delete>", lambda e: self.delete_selected())
        self.tree.bind("<F2>", lambda e: self.start_edit(self.tree.focus()))
        self.tree.bind("<Button-3>", self.popup)
        self.tree.bind("<<TreeviewOpen>>", lambda e: self.set_open(True))
        self.tree.bind("<<TreeviewClose>>", lambda e: self.set_open(False))

        self.hint = tk.Frame(self.tree, bg=C_ACCENT, height=2)

        self.tree.bind("<ButtonPress-1>", self.on_press, add="+")
        self.tree.bind("<B1-Motion>", self.on_drag, add="+")
        self.tree.bind("<ButtonRelease-1>", self.on_release, add="+")
        self.tree.bind("<Configure>", self.on_tree_configure, add="+")
        self.tree.bind("<Motion>", self.on_hover, add="+")
        self.tree.bind("<Leave>", lambda e: self.clear_hover(), add="+")

        # 无边框窗口点击时不会自动获得焦点, 手动抢一下, 否则键盘快捷键失效
        for w in (r, inner, body, self.tree):
            w.bind("<Button-1>", self.grab_focus, add="+")

        # ---- 底栏 ----
        foot = tk.Frame(inner, bg=C_BG, height=32)
        foot.pack(fill="x", side="bottom")
        foot.pack_propagate(False)
        self._foot = foot
        line = tk.Frame(inner, bg=C_BORDER, height=1)
        line.pack(fill="x", side="bottom")
        self._line = line

        def flat_btn(parent, text, cmd):
            b = tk.Label(parent, text=text, bg=C_BG, fg=C_FG_FAINT,
                         font=self.f_small, cursor="hand2", padx=7)
            b.pack(side="left", pady=7)
            b.bind("<Button-1>", lambda e: cmd())
            b.bind("<Enter>", lambda e, w=b: w.configure(fg=C_FG))
            b.bind("<Leave>", lambda e, w=b: w.configure(fg=C_FG_FAINT))
            return b

        flat_btn(foot, "\uff0b 新建", self.add_top)
        flat_btn(foot, "展开", lambda: self.collapse_all(False))
        flat_btn(foot, "折叠", lambda: self.collapse_all(True))

        self.tip = tk.Label(foot, text="双击便签 · 拖动排序", bg=C_BG,
                            fg=C_FG_FAINT, font=self.f_small)
        self.tip.pack(side="right", padx=(4, 2))

        gear = tk.Label(foot, text="\u2699", bg=C_BG, fg=C_FG_FAINT,
                        font=self.f_item, cursor="hand2", width=2)
        gear.pack(side="right", padx=(0, 6))
        gear.bind("<Button-1>", lambda e: self.open_settings())
        gear.bind("<Enter>", lambda e, w=gear: w.configure(fg=C_FG))
        gear.bind("<Leave>", lambda e, w=gear: w.configure(fg=C_FG_FAINT))

        r.bind("<FocusOut>", self.on_focus_out)
        r.bind("<Button-1>", self.on_any_click, add="+")
        r.bind("<Configure>", self.on_win_configure, add="+")
        r.bind("<Control-q>", lambda e: self.quit())

    def make_box(self, checked, size=16):
        """画一个勾选框小图标 (圆角方框, 勾在框里)"""
        if not HAS_TRAY:
            return None
        try:
            img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            mask = Image.new("L", (size, size), 0)
            ImageDraw.Draw(mask).rounded_rectangle(
                [1, 1, size - 2, size - 2], radius=4, fill=255)
            if checked:
                red, green, blue = hex_to_rgb(C_ACCENT)
                img.paste(Image.new("RGBA", (size, size), (red, green, blue, 255)),
                          (0, 0), mask)
                # 勾单独画一层再按框裁剪, 不然线头会戳出框外
                chk = Image.new("RGBA", (size, size), (0, 0, 0, 0))
                ImageDraw.Draw(chk).line(
                    [(5.0, 8.2), (7.0, 10.4), (11.2, 5.8)],
                    fill=(255, 255, 255, 255), width=2, joint="curve")
                img.paste(chk, (0, 0),
                          ImageChops.multiply(chk.getchannel("A"), mask))
            else:
                inner = Image.new("L", (size, size), 0)
                ImageDraw.Draw(inner).rounded_rectangle(
                    [2, 2, size - 3, size - 3], radius=3, fill=255)
                ring = ImageChops.subtract(mask, inner)
                img.paste(Image.new("RGBA", (size, size), (110, 115, 130, 255)),
                          (0, 0), ring)
            return ImageTk.PhotoImage(img)
        except Exception:
            return None

    def set_tab(self, key):
        if key == self.tab:
            return
        self.finish_edit()
        self.tab = key
        self.save_conf()
        self.refresh()

    def update_tabs(self, done, total):
        try:
            self.tab_labels["pending"].config(
                text="未完成 {}".format(total - done),
                fg=C_FG if self.tab == "pending" else C_FG_DIM)
            self.tab_labels["done"].config(
                text="已完成 {}".format(done),
                fg=C_FG if self.tab == "done" else C_FG_DIM)
            self.tab_bars["pending"].config(
                bg=C_ACCENT if self.tab == "pending" else C_BG)
            self.tab_bars["done"].config(
                bg=C_ACCENT if self.tab == "done" else C_BG)
        except Exception:
            pass

    def toggle_fold(self):
        self.set_folded(not self.collapsed)

    def set_folded(self, folded):
        """右上角折叠: 只留一条横杠"""
        if folded == self.collapsed:
            return
        self.collapsed = bool(folded)
        if self.collapsed:
            w, h = self.root.winfo_width(), self.root.winfo_height()
            if w < 120 or h < 120:
                try:
                    size = self.conf.get("geom", "").split("+")[0]
                    w, h = (int(v) for v in size.split("x"))
                except Exception:
                    w, h = 330, 460
            self._expanded_size = (w, h)
            for w in (self._track, self._tabbar, self._body, self._foot, self._line):
                w.pack_forget()
            self.btn_fold.config(text="\u25be")
            w = max(220, self.root.winfo_width())
            self.root.minsize(220, 42)
            self.root.geometry("{}x{}".format(w, 42))
        else:
            self._track.pack(fill="x", side="top")
            self._tabbar.pack(fill="x", side="top")
            self._body.pack(fill="both", expand=True, padx=(6, 3), pady=(6, 0))
            self._foot.pack(fill="x", side="bottom")
            self._line.pack(fill="x", side="bottom")
            self.btn_fold.config(text="\u25b4")
            self.root.minsize(270, 220)
            w, h = self._expanded_size or (330, 460)
            self.root.geometry("{}x{}".format(w, h))
        self.save_conf()

    def on_win_configure(self, e):
        if e.widget is not self.root:
            return
        if getattr(self, "_win_size", None) == (e.width, e.height):
            return
        self._win_size = (e.width, e.height)
        self.root.after(15, self.round_window)

    def round_window(self):
        """无边框 + 圆角, 看着像个小组件"""
        if self.mode != "desktop":
            return
        try:
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            w = max(2, self.root.winfo_width())
            h = max(2, self.root.winfo_height())
            rgn = ctypes.windll.gdi32.CreateRoundRectRgn(0, 0, w + 1, h + 1, 20, 20)
            ctypes.windll.user32.SetWindowRgn(hwnd, rgn, True)
        except Exception:
            pass

    def on_hover(self, e):
        if self._dragging:
            return
        iid = self.tree.identify_row(e.y)
        if iid == getattr(self, "_hover", None):
            return
        self.clear_hover()
        if iid and iid in self._refs:
            self._hover = iid
            self.tree.item(iid, tags=(self.base_tag(iid) + "_h",))

    def clear_hover(self):
        iid = getattr(self, "_hover", None)
        self._hover = None
        if iid and self.tree.exists(iid):
            self.tree.item(iid, tags=(self.base_tag(iid),))

    def base_tag(self, iid):
        ref = self._refs.get(iid)
        if not ref:
            return "item"
        it = ref["item"]
        if it.get("children"):
            return "group_done" if it.get("done") else "group"
        return "item_done" if it.get("done") else "item"

    # ---------------- 渲染 ----------------
    def normalize(self):
        """组的状态 = 所有子项都完成"""
        def walk_up(items):
            for it in items:
                kids = it.setdefault("children", [])
                walk_up(kids)
                if kids:
                    it["done"] = all(k.get("done") for k in kids)
        walk_up(self.store.items)

    def refresh(self, sync_open=True):
        t = self.tree
        sel = t.focus()
        name = self.store.current_name()
        if len(name) > 10:
            name = name[:9] + "\u2026"
        self.lbl_title.config(text=name + "  \u25be")
        open_state = {}
        if sync_open:
            for iid in self._refs:
                if t.exists(iid):
                    open_state[iid] = bool(t.item(iid, "open"))

        t.delete(*t.get_children())
        self._refs.clear()
        self._hover = None
        self._marked = None

        def add(parent, items):
            for it in items:
                # 只看根节点的完成状态: 一个根条目要么整条在"未完成", 要么整条在"已完成"
                if not parent and bool(it.get("done")) != (self.tab == "done"):
                    continue
                kids = it.get("children") or []
                done = bool(it.get("done"))
                if self.img_off is not None:
                    text = " " + (it["text"] or "(未命名)")
                    image = self.img_on if done else self.img_off
                else:
                    text = "{} {}".format(BOX_ON if done else BOX_OFF,
                                          it["text"] or "(未命名)")
                    image = None
                if kids:
                    d, n = leaf_stats(it)
                    text += "  ·  {}/{}".format(d, n)
                    tag = "group_done" if done else "group"
                else:
                    tag = "item_done" if done else "item"
                note = (it.get("note") or "").strip()
                if note:
                    text += "  \u270e"
                iid = it["id"]
                if iid in open_state:
                    it["open"] = open_state[iid]
                t.insert(parent, "end", iid=iid, text=text, tags=(tag,),
                         image=image, open=it.get("open", True))
                self._refs[iid] = {"item": it, "list": items}
                add(iid, kids)

        add("", self.store.items)
        if not t.get_children():
            t.insert("", "end", iid="__empty__", tags=("empty",),
                     text="  （还没有已完成的任务）" if self.tab == "done"
                     else "  （没有未完成的任务）")
        if sel and t.exists(sel):
            t.focus(sel)
            t.selection_set(sel)

        total = done = 0
        for it, _ in walk(self.store.items):
            if not it.get("children"):
                total += 1
                done += 1 if it.get("done") else 0
        # 页签和顶栏按根条目统计, 跟列表里看到的保持一致
        root_done = sum(1 for it in self.store.items if it.get("done"))
        root_total = len(self.store.items)
        self.lbl_stat.config(
            text="{} 项未完成 · {} 项已完成".format(root_total - root_done, root_done))
        self.update_tabs(root_done, root_total)
        try:
            self.pbar.place_configure(relwidth=(done / total) if total else 0)
        except Exception:
            pass
        self.root.after_idle(self.sync_scroll)

    def sync_scroll(self):
        """内容放得下就把滚动条藏起来, 更干净"""
        try:
            y0, y1 = self.tree.yview()
            need = (y1 - y0) < 0.998
            mapped = bool(self.scroll.winfo_ismapped())
            if need and not mapped:
                self.scroll.pack(side="right", fill="y", before=self.tree)
            elif not need and mapped:
                self.scroll.pack_forget()
        except Exception:
            pass

    def on_tree_configure(self, e):
        # 只有高度变了才重算, 否则滚动条一显示一隐藏会来回抖
        if getattr(self, "_tree_h", None) != e.height:
            self._tree_h = e.height
            self.root.after_idle(self.sync_scroll)

    # ---------------- 操作 ----------------
    def set_open(self, val):
        iid = self.tree.focus()
        ref = self._refs.get(iid)
        if ref:
            ref["item"]["open"] = val

    def toggle(self, iid):
        ref = self._refs.get(iid)
        if not ref:
            return
        item = ref["item"]
        target = not item.get("done")

        def apply(it):
            it["done"] = target
            for k in it.get("children") or []:
                apply(k)

        apply(item)
        self.normalize()
        self.store.save()
        self.refresh()

    def add_top(self):
        if self.collapsed:
            self.set_folded(False)
        self._add_to(self.store.items, "")

    def add_child(self):
        ref = self._refs.get(self.tree.focus())
        if not ref:
            return self.add_top()
        kids = ref["item"].setdefault("children", [])
        ref["item"]["open"] = True
        self._add_to(kids, ref["item"]["id"])

    def add_sibling(self):
        ref = self._refs.get(self.tree.focus())
        if not ref:
            return self.add_top()
        self._add_to(ref["list"], self._parent_of(ref["item"]))

    def _parent_of(self, item):
        for it, _ in walk(self.store.items):
            if item in (it.get("children") or []):
                return it["id"]
        return ""

    def _add_to(self, target_list, parent_iid):
        if self.tab != "pending":
            self.set_tab("pending")
        it = new_item("")
        target_list.append(it)
        self.normalize()
        self.refresh()
        if parent_iid and self.tree.exists(parent_iid):
            self.tree.item(parent_iid, open=True)
        self.tree.selection_set(it["id"])
        self.tree.focus(it["id"])
        self.tree.see(it["id"])
        self.root.after(30, lambda: self.start_edit(it["id"]))

    def delete_selected(self):
        iid = self.tree.focus()
        ref = self._refs.get(iid)
        if not ref:
            return
        item = ref["item"]
        kids = item.get("children") or []
        if kids:
            try:
                self.root.attributes("-topmost", True)
            except Exception:
                pass
            ok = messagebox.askyesno(
                "删除", "删除「{}」及 {} 个子项？".format(item["text"], len(kids)),
                parent=self.root)
            try:
                self.root.attributes("-topmost", bool(self.topmost))
            except Exception:
                pass
            if not ok:
                return
        ref["list"].remove(item)
        self.normalize()
        self.store.save()
        self.refresh()

    def move(self, delta):
        ref = self._refs.get(self.tree.focus())
        if not ref:
            return
        lst, item = ref["list"], ref["item"]
        i = lst.index(item)
        j = i + delta
        if 0 <= j < len(lst):
            lst[i], lst[j] = lst[j], lst[i]
            self.store.save()
            self.refresh()
            self.tree.focus(item["id"])
            self.tree.selection_set(item["id"])

    def collapse_all(self, val):
        for it, _ in walk(self.store.items):
            if it.get("children"):
                it["open"] = not val
        self.refresh(sync_open=False)

    def toggle_collapse_all(self):
        self.collapse_all(any(it.get("open") for it, _ in walk(self.store.items)
                              if it.get("children")))

    # ---------------- 拖动排序 ----------------
    def on_press(self, e):
        iid = self.tree.identify_row(e.y)
        self._drag_src = iid
        self._drag_xy = (e.x, e.y)
        self._dragging = False
        self._drop = None
        self._press_box = iid if (iid and self.clicked_box(e.x, e.y)) else None

    def on_drag(self, e):
        if not self._drag_src:
            return
        if not self._dragging:
            dx = abs(e.x - self._drag_xy[0])
            dy = abs(e.y - self._drag_xy[1])
            if dy < 6 or dy < dx:  # 竖向拖开一点才算拖动, 否则当普通点击
                return
            self._dragging = True
            self.clear_hover()
            self.show_ghost(self._drag_src)
        self.move_ghost(e.x_root, e.y_root)
        self.autoscroll(e.y)
        self.update_hint(e.y)

    def show_ghost(self, iid):
        """跟着鼠标走的小卡片, 一眼看出在拖什么"""
        ref = self._refs.get(iid)
        if not ref:
            return
        item = ref["item"]
        text = item["text"] or "(未命名)"
        if len(text) > 20:
            text = text[:19] + "\u2026"
        if item.get("children"):
            text = "\u2261 " + text
        try:
            g = tk.Toplevel(self.root)
            g.overrideredirect(True)
            g.attributes("-topmost", True)
            try:
                g.attributes("-alpha", 0.85)
            except Exception:
                pass
            box = tk.Frame(g, bg=C_GHOST_BG)
            box.pack()
            ghost_fg = best_text_color(C_GHOST_BG)
            tk.Label(box, text=text, bg=C_GHOST_BG, fg=ghost_fg,
                     font=self.f_group, padx=12, pady=6).pack()
            self._ghost = g
        except Exception:
            self._ghost = None

    def move_ghost(self, x, y):
        if getattr(self, "_ghost", None) is not None:
            try:
                self._ghost.geometry("+{}+{}".format(x + 16, y + 14))
            except Exception:
                pass

    def hide_ghost(self):
        g = getattr(self, "_ghost", None)
        self._ghost = None
        if g is not None:
            try:
                g.destroy()
            except Exception:
                pass

    def on_release(self, e):
        dragging, src = self._dragging, self._drag_src
        box = getattr(self, "_press_box", None)
        self._drag_src = None
        self._dragging = False
        self._press_box = None
        self.hide_ghost()
        self.hide_hint()
        if dragging:
            if src:
                self.drop(src, self._drop)
            return "break"
        if box and self.tree.exists(box):
            # 放到事件之后再做, 免得在树的点击事件里重建整个列表
            self.root.after(0, self.toggle, box)
            return "break"

    def autoscroll(self, y):
        h = self.tree.winfo_height()
        if y < 22:
            self.tree.yview_scroll(-1, "units")
        elif y > h - 22:
            self.tree.yview_scroll(1, "units")

    def drop_target(self, y):
        """算出松手位置: (父iid, 插入下标, 目标行, 方式 before/after/inside/end)"""
        iid = self.tree.identify_row(y)
        if not iid or iid not in self._refs:
            return "", len(self.store.items), "", "end"
        bbox = self.tree.bbox(iid)
        ref = self._refs[iid]
        item = ref["item"]
        kids = item.get("children") or []
        if not bbox:
            return "", len(self.store.items), "", "end"
        rel = (y - bbox[1]) / max(1, bbox[3])
        if kids and 0.28 <= rel <= 0.72:  # 落在组的中间 -> 收进去当子项
            return iid, len(kids), iid, "inside"
        parent = self.tree.parent(iid)
        idx = ref["list"].index(item)
        if rel < 0.5:
            return parent, idx, iid, "before"
        return parent, idx + 1, iid, "after"

    def update_hint(self, y):
        parent, index, tgt, mode = self.drop_target(y)
        src = self._drag_src
        ok = True
        if tgt and (tgt == src or self.is_ancestor(src, tgt)):
            ok = False
        if not ok:
            self.hide_hint()
            self._drop = None
            return
        self._drop = (parent, index, tgt, mode)
        self.clear_marks()
        if mode == "inside":
            bbox = self.tree.bbox(tgt)
            if bbox:
                self.mark_row(tgt)
                self.hint.place(x=bbox[0] + 2, y=bbox[1] + bbox[3] - 3,
                                width=max(40, self.tree.winfo_width() - 8),
                                height=2)
                self.hint.lift()
            return
        if mode == "end":
            bbox = self.tree.bbox(self.tree.get_children()[-1])
            if bbox:
                yy = bbox[1] + bbox[3]
                self.hint.place(x=4, y=yy, width=max(40, self.tree.winfo_width() - 10),
                                height=2)
                self.hint.lift()
            return
        bbox = self.tree.bbox(tgt)
        if bbox:
            yy = bbox[1] if mode == "before" else bbox[1] + bbox[3] - 1
            self.hint.place(x=bbox[0] + 2, y=yy,
                            width=max(40, self.tree.winfo_width() - 8), height=2)
            self.hint.lift()

    def mark_row(self, iid):
        self._marked = iid
        self.tree.item(iid, tags=("drop_" + self.base_tag(iid),))

    def clear_marks(self):
        iid = getattr(self, "_marked", None)
        self._marked = None
        if iid and self.tree.exists(iid):
            self.tree.item(iid, tags=(self.base_tag(iid),))

    def hide_hint(self):
        try:
            self.hint.place_forget()
        except Exception:
            pass
        self.clear_marks()

    def is_ancestor(self, a, b):
        p = self.tree.parent(b)
        while p:
            if p == a:
                return True
            p = self.tree.parent(p)
        return False

    def drop(self, src, target):
        if not target:
            return
        parent, index, tgt, mode = target
        if tgt and (tgt == src or self.is_ancestor(src, tgt)):
            return
        ref = self._refs.get(src)
        if not ref:
            return
        item, src_list = ref["item"], ref["list"]
        src_index = src_list.index(item)
        if mode == "inside":
            dst_list = self._refs[tgt]["item"].setdefault("children", [])
            dst_index = len(dst_list)
            self._refs[tgt]["item"]["open"] = True
        elif mode == "end":
            dst_list, dst_index = self.store.items, len(self.store.items)
        else:
            dst_list = self._refs[tgt]["list"]
            dst_index = dst_list.index(self._refs[tgt]["item"])
            if mode == "after":
                dst_index += 1
        if src_list is dst_list and dst_index > src_index:
            dst_index -= 1
        src_list.remove(item)
        dst_list.insert(dst_index, item)
        self.normalize()
        self.store.save()
        self.refresh()
        if self.tree.exists(src):
            self.tree.focus(src)
            self.tree.selection_set(src)
            self.tree.see(src)

    # ---------------- 双击便签 ----------------
    def on_double_click(self, e):
        iid = self.tree.identify_row(e.y)
        if not iid:
            return
        if self.clicked_box(e.x, e.y):
            return  # 框上双击不弹便签
        try:
            element = self.tree.identify_element(e.x, e.y)
        except Exception:
            element = ""
        if element == "Treeitem.indicator":
            return  # 双击小三角是展开/折叠
        self.open_note(iid)

    def clicked_box(self, x, y):
        try:
            return self.tree.identify_element(x, y) == "image"
        except Exception:
            return False

    def box_x(self, iid):
        """这一行勾选框的中心 x, 找不到就返回 None"""
        bbox = self.tree.bbox(iid)
        if not bbox:
            return None
        left = bbox[0]
        mid_y = bbox[1] + bbox[3] // 2
        limit = left + min(bbox[2], 240)
        x = left
        while x < limit:
            try:
                element = self.tree.identify_element(x, mid_y)
            except Exception:
                element = ""
            if element == "image":
                return x + 6
            x += 2
        return None

    # ---------------- 测试接口(不碰真实鼠标键盘) ----------------
    def simulate_click(self, iid, on_box=False):
        """等价于用鼠标点这一行, 处理链和真实点击完全一样"""
        bbox = self.tree.bbox(iid)
        if not bbox:
            return False
        mid_y = bbox[1] + bbox[3] // 2
        if on_box:
            x = self.box_x(iid)
        else:
            x = self.row_content_x(iid) + 40
        if x is None:
            return False

        tree_event = FakeEvent(self.tree, x, mid_y)
        root_event = FakeEvent(self.root, x, mid_y)
        self.on_press(tree_event)
        self.on_release(tree_event)
        self.on_any_click(root_event)
        return True

    def simulate_double_click(self, iid):
        """等价于用鼠标双击这一行的文字"""
        bbox = self.tree.bbox(iid)
        if not bbox:
            return False
        mid_y = bbox[1] + bbox[3] // 2
        x = self.row_content_x(iid) + 40

        tree_event = FakeEvent(self.tree, x, mid_y)
        root_event = FakeEvent(self.root, x, mid_y)
        self.on_press(tree_event)
        self.on_release(tree_event)
        self.on_press(tree_event)
        self.on_double_click(tree_event)
        self.on_any_click(root_event)
        self.on_release(tree_event)
        return True

    def row_content_x(self, iid):
        """某一行的正文从哪个 x 开始 (跳过展开箭头和勾选框)"""
        bbox = self.tree.bbox(iid)
        if not bbox:
            return 0
        left = bbox[0]
        mid_y = bbox[1] + bbox[3] // 2
        limit = left + min(bbox[2], 240)
        first_text = None
        x = left
        while x < limit:
            try:
                element = self.tree.identify_element(x, mid_y)
            except Exception:
                element = ""
            if element == "image":
                return x
            if element == "text" and first_text is None:
                first_text = x
            x += 2
        if first_text is not None:
            return first_text
        return left

    def start_edit(self, iid):
        if self._editor is not None:
            return
        ref = self._refs.get(iid)
        if not ref:
            return
        item = ref["item"]
        bbox = self.tree.bbox(iid)
        if not bbox:
            return

        x, y, w, h = bbox
        start_x = self.row_content_x(iid)
        avail = self.tree.winfo_width() - start_x - 10
        entry = tk.Entry(self.tree, font=self.f_item, bg=C_BG_ALT, fg=C_FG,
                         insertbackground=C_ACCENT, relief="flat", bd=0,
                         highlightthickness=1, highlightbackground=C_ACCENT,
                         highlightcolor=C_ACCENT)
        entry.place(x=start_x, y=y, width=max(120, avail), height=h)
        entry.insert(0, item["text"])
        entry.select_range(0, "end")
        entry.focus_set()
        self._editor = entry
        state = {"done": False}

        def finish(commit):
            if state["done"]:
                return
            state["done"] = True
            self._finish_edit = None
            text = entry.get().strip()
            try:
                entry.destroy()
            except Exception:
                pass
            self._editor = None
            if commit and text:
                item["text"] = text
            if text:
                self.store.save()
            else:  # 空文本 = 取消/丢弃新建的空任务
                if item in ref["list"]:
                    ref["list"].remove(item)
                self.store.save()
            self.normalize()
            self.refresh()

        self._finish_edit = finish
        entry.bind("<Return>", lambda ev: finish(True))
        entry.bind("<KP_Enter>", lambda ev: finish(True))
        entry.bind("<Escape>", lambda ev: finish(False))
        entry.bind("<FocusOut>", lambda ev: finish(True))

    def finish_edit(self):
        """退出改名状态(保存当前输入)"""
        f = getattr(self, "_finish_edit", None)
        if f is not None:
            f(True)

    def on_any_click(self, e):
        """在窗口里点任何别的地方都结束改名 / 收起便签"""
        if self.note_win is not None:
            # 双击那次点击也会走到这里, 刚弹出来的便签别马上关掉
            opened_at = getattr(self, "_note_opened_at", 0.0)
            if time.time() - opened_at > 0.4:
                self.close_note()
        if self._editor is None:
            return
        if e.widget is self._editor:
            return  # 点输入框内部不结束
        # e.widget 有时拿到的是顶层窗口, 再用坐标兜一层
        try:
            x, y = e.x_root, e.y_root
            ex, ey = self._editor.winfo_rootx(), self._editor.winfo_rooty()
            ew, eh = self._editor.winfo_width(), self._editor.winfo_height()
            if ex <= x < ex + ew and ey <= y < ey + eh:
                return
        except Exception:
            pass
        self.finish_edit()

    # ---------------- 多清单 ----------------
    def build_list_menu(self):
        menu = tk.Menu(self.root, tearoff=0)
        for lst in self.store.lists:
            label = lst["name"]
            if lst["id"] == self.store.current:
                label = "\u2713  " + label
            else:
                label = "    " + label
            menu.add_command(label=label,
                             command=lambda lid=lst["id"]: self.switch_list(lid))
        menu.add_separator()
        menu.add_command(label="新建清单…", command=self.new_list)
        menu.add_command(label="重命名当前清单…", command=self.rename_list)
        menu.add_command(label="删除当前清单…", command=self.delete_list)
        return menu

    def open_list_menu(self, event=None):
        self.finish_edit()
        menu = self.build_list_menu()
        x = self.lbl_title.winfo_rootx()
        y = self.lbl_title.winfo_rooty() + self.lbl_title.winfo_height() + 2
        try:
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def switch_list(self, list_id):
        if list_id == self.store.current:
            return
        self.finish_edit()
        self.close_note()
        self.store.select(list_id)
        self.store.save()
        self.refresh()

    def new_list(self):
        def create(name):
            self.store.add_list(name)
            self.store.save()
            self.refresh()

        self.prompt_text("新建清单", "新清单", create)

    def rename_list(self):
        def apply(name):
            self.store.rename_list(self.store.current, name)
            self.store.save()
            self.refresh()

        self.prompt_text("重命名清单", self.store.current_name(), apply)

    def delete_list(self):
        if len(self.store.lists) <= 1:
            messagebox.showinfo("删除清单", "至少要保留一份清单。",
                                parent=self.root)
            return
        name = self.store.current_name()
        try:
            self.root.attributes("-topmost", True)
        except Exception:
            pass
        confirmed = messagebox.askyesno(
            "删除清单", "删除清单「{}」以及里面的所有任务？".format(name),
            parent=self.root)
        try:
            self.root.attributes("-topmost", bool(self.topmost))
        except Exception:
            pass
        if not confirmed:
            return
        self.close_note()
        self.store.delete_list(self.store.current)
        self.store.save()
        self.refresh()

    def prompt_text(self, title, initial, on_ok):
        """一个小的输入弹窗, 风格跟主界面一致"""
        if self.prompt_win is not None:
            try:
                self.prompt_win.destroy()
            except Exception:
                pass
            self.prompt_win = None

        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg=C_BORDER)
        self.prompt_win = win

        body = tk.Frame(win, bg=C_BG)
        body.pack(fill="both", expand=True, padx=1, pady=1)

        head = tk.Frame(body, bg=C_HEAD, height=28)
        head.pack(fill="x")
        head.pack_propagate(False)
        tk.Label(head, text=title, bg=C_HEAD, fg=C_FG,
                 font=self.f_small).pack(side="left", padx=10)

        entry = tk.Entry(body, bg=C_BG_ALT, fg=C_FG,
                         insertbackground=C_ACCENT, relief="flat", bd=0,
                         highlightthickness=1, highlightbackground=C_ACCENT,
                         highlightcolor=C_ACCENT, font=self.f_item)
        entry.pack(fill="x", padx=10, pady=10)
        entry.insert(0, initial or "")
        entry.select_range(0, "end")

        row = tk.Frame(body, bg=C_BG)
        row.pack(fill="x", padx=10, pady=(0, 10))

        state = {"done": False}

        def close(commit):
            if state["done"]:
                return
            state["done"] = True
            value = entry.get().strip()
            self.prompt_win = None
            try:
                win.destroy()
            except Exception:
                pass
            if commit and value:
                on_ok(value)

        ok_btn = tk.Label(row, text="确定", bg=C_ACCENT,
                          fg=best_text_color(C_ACCENT), font=self.f_small,
                          cursor="hand2", padx=12, pady=3)
        ok_btn.pack(side="right")
        ok_btn.bind("<Button-1>", lambda ev: close(True))

        cancel_btn = tk.Label(row, text="取消", bg=C_BG, fg=C_FG_DIM,
                              font=self.f_small, cursor="hand2", padx=10, pady=3)
        cancel_btn.pack(side="right", padx=(0, 6))
        cancel_btn.bind("<Button-1>", lambda ev: close(False))

        entry.bind("<Return>", lambda ev: close(True))
        entry.bind("<Escape>", lambda ev: close(False))
        win.bind("<Escape>", lambda ev: close(False))

        width, height = 260, 108
        base_x = self.root.winfo_rootx() + (self.root.winfo_width() - width) // 2
        base_y = self.root.winfo_rooty() + (self.root.winfo_height() - height) // 2
        win.geometry("{}x{}+{}+{}".format(width, height, base_x, base_y))
        win.lift()
        entry.focus_set()

    # ---------------- 便签 ----------------
    def screen_center(self, width, height):
        """算出让窗口落在主窗体那块屏幕正中间的位置"""
        try:
            user32 = ctypes.windll.user32
            hwnd = user32.GetParent(self.root.winfo_id())
            monitor = user32.MonitorFromWindow(hwnd, 2)  # 2 = 最近的显示器
            info = MonitorInfo()
            info.cbSize = ctypes.sizeof(MonitorInfo)
            if user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                area = info.rcWork
                area_w = area.right - area.left
                area_h = area.bottom - area.top
                x = area.left + (area_w - width) // 2
                y = area.top + (area_h - height) // 2
                return x, y
        except Exception:
            pass
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        return (screen_w - width) // 2, (screen_h - height) // 2

    def open_note(self, iid):
        ref = self._refs.get(iid)
        if ref is None:
            return
        self.finish_edit()
        if self.note_win is not None:
            self.close_note()

        item = ref["item"]
        self.note_item = item
        self.note_raw = item.get("note") or ""
        self.note_editing = True

        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg=NOTE_EDGE)
        self.note_win = win

        body = tk.Frame(win, bg=NOTE_BG)
        body.pack(fill="both", expand=True, padx=1, pady=1)

        strip = tk.Frame(body, bg=C_ACCENT, height=3)
        strip.pack(fill="x", side="top")

        head = tk.Frame(body, bg=NOTE_HEAD, height=32)
        head.pack(fill="x", side="top")
        head.pack_propagate(False)

        title_text = item["text"] or "(未命名)"
        if len(title_text) > 14:
            title_text = title_text[:13] + "\u2026"
        title = tk.Label(head, text="\u270e  " + title_text, bg=NOTE_HEAD,
                         fg=NOTE_FG, font=self.f_small, anchor="w")
        title.pack(side="left", padx=10)

        close_btn = tk.Label(head, text="\u2715", bg=NOTE_HEAD, fg=NOTE_DIM,
                             font=self.f_item, width=2, cursor="hand2")
        close_btn.pack(side="right", padx=4)
        close_btn.bind("<Button-1>", lambda ev: self.close_note())
        close_btn.bind("<Enter>", lambda ev: close_btn.configure(fg=NOTE_FG))
        close_btn.bind("<Leave>", lambda ev: close_btn.configure(fg=NOTE_DIM))

        self.btn_note_mode = tk.Label(head, text="\u9884\u89c8", bg=NOTE_HEAD,
                                      fg=NOTE_DIM, font=self.f_small,
                                      cursor="hand2", padx=6)
        self.btn_note_mode.pack(side="right")
        self.btn_note_mode.bind("<Button-1>", lambda ev: self.note_toggle_mode())
        self.btn_note_mode.bind("<Enter>",
                                lambda ev: self.btn_note_mode.configure(fg=NOTE_FG))
        self.btn_note_mode.bind("<Leave>",
                                lambda ev: self.btn_note_mode.configure(fg=NOTE_DIM))

        hint = tk.Label(body, text="# 标题 · - 列表 · 1. 编号 · **加粗** · 网址可点",
                        bg=NOTE_BG, fg=NOTE_DIM, font=self.f_small, anchor="w")
        hint.pack(fill="x", side="bottom", padx=12, pady=(0, 6))

        text = tk.Text(body, bg=NOTE_BG, fg=NOTE_FG, insertbackground=C_ACCENT,
                       relief="flat", bd=0, highlightthickness=0, wrap="word",
                       font=self.f_item, padx=12, pady=10, undo=True,
                       selectbackground="#e6d7a8", selectforeground=NOTE_FG)
        text.pack(fill="both", expand=True)
        self.note_text = text

        text.tag_configure("h1", font=self.f_note_h1, foreground=NOTE_FG,
                           spacing1=8, spacing3=4)
        text.tag_configure("h2", font=self.f_note_h2, foreground=NOTE_FG,
                           spacing1=6, spacing3=2)
        text.tag_configure("li", lmargin1=16, lmargin2=30)
        text.tag_configure("mark", foreground=NOTE_MARK)
        text.tag_configure("quote", lmargin1=16, lmargin2=16, foreground=NOTE_DIM)
        text.tag_configure("bold", font=self.f_note_bold)
        text.tag_configure("code", background=NOTE_CODE, foreground="#7a5c1f")
        text.tag_configure("link", foreground=NOTE_LINK, underline=True)
        text.tag_bind("link", "<Button-1>", self.note_link_click)
        text.tag_bind("link", "<Enter>",
                      lambda ev: text.configure(cursor="hand2"))
        text.tag_bind("link", "<Leave>",
                      lambda ev: text.configure(cursor="xterm"))

        if self.note_raw:
            text.insert("1.0", self.note_raw)
        self.root.after(30, self.note_mark_links)

        drag = {}

        def start_move(ev):
            drag["dx"] = ev.x_root - win.winfo_x()
            drag["dy"] = ev.y_root - win.winfo_y()

        def do_move(ev):
            if "dx" not in drag:
                return
            nx = ev.x_root - drag["dx"]
            ny = ev.y_root - drag["dy"]
            win.geometry("+{}+{}".format(nx, ny))

        for widget in (head, title, strip):
            widget.bind("<Button-1>", start_move)
            widget.bind("<B1-Motion>", do_move)

        win.bind("<Escape>", lambda ev: self.close_note())
        text.bind("<Escape>", lambda ev: self.close_note())
        text.bind("<Return>", self.note_on_return)
        text.bind("<KeyRelease>", self.note_schedule_links)

        width, height = 400, 320
        x, y = self.screen_center(width, height)
        win.geometry("{}x{}+{}+{}".format(width, height, x, y))
        win.lift()
        text.focus_set()
        self._note_opened_at = time.time()

    def note_on_return(self, event):
        """回车自动续列表: - 续 - , 1. 续 2."""
        widget = self.note_text
        line_start = widget.index("insert linestart")
        line = widget.get(line_start, "insert")

        bullet = re.match(r"^(\s*)([-*+])\s+", line)
        if bullet:
            rest = line[bullet.end():].strip()
            if not rest:  # 空条目再回车 = 退出列表
                widget.delete(line_start, "insert")
                return "break"
            insert_text = "\n{}{} ".format(bullet.group(1), bullet.group(2))
            widget.insert("insert", insert_text)
            widget.see("insert")
            return "break"

        ordered = re.match(r"^(\s*)(\d+)([.)])\s+", line)
        if ordered:
            rest = line[ordered.end():].strip()
            if not rest:
                widget.delete(line_start, "insert")
                return "break"
            next_no = int(ordered.group(2)) + 1
            insert_text = "\n{}{}{} ".format(ordered.group(1), next_no,
                                             ordered.group(3))
            widget.insert("insert", insert_text)
            widget.see("insert")
            return "break"

        return None

    def note_toggle_mode(self):
        if self.note_editing:
            self.note_raw = self.note_text.get("1.0", "end-1c")
            self.note_render()
            self.note_editing = False
            self.btn_note_mode.config(text="\u7f16\u8f91")
            return

        self.note_text.configure(state="normal")
        self.note_text.delete("1.0", "end")
        if self.note_raw:
            self.note_text.insert("1.0", self.note_raw)
        self.note_editing = True
        self.btn_note_mode.config(text="\u9884\u89c8")
        self.note_text.focus_set()

    def note_render(self):
        widget = self.note_text
        raw = self.note_raw or ""
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        for line in raw.split("\n"):
            self.note_render_line(widget, line)
        widget.configure(state="disabled")
        self.note_mark_links()

    def note_schedule_links(self, event=None):
        win = self.note_win
        if win is None or not self.note_editing:
            return
        job = getattr(self, "_note_link_job", None)
        if job is not None:
            try:
                win.after_cancel(job)
            except Exception:
                pass
        self._note_link_job = win.after(350, self.note_mark_links)

    def note_mark_links(self):
        """把文里的网址标出来, 变成可点的链接"""
        self._note_link_job = None
        widget = self.note_text
        if widget is None:
            return
        try:
            widget.tag_remove("link", "1.0", "end")
            content = widget.get("1.0", "end-1c")
        except Exception:
            return
        for match in LINK_RE.finditer(content):
            url = match.group(0).rstrip(LINK_TAIL)
            if not url:
                continue
            start = "1.0+{}c".format(match.start())
            end = "1.0+{}c".format(match.start() + len(url))
            widget.tag_add("link", start, end)

    def note_link_at(self, index):
        widget = self.note_text
        if widget is None:
            return None
        ranges = widget.tag_ranges("link")
        for i in range(0, len(ranges), 2):
            start = ranges[i]
            end = ranges[i + 1]
            after_start = widget.compare(start, "<=", index)
            before_end = widget.compare(index, "<", end)
            if after_start and before_end:
                return widget.get(start, end)
        return None

    def note_link_click(self, event):
        widget = self.note_text
        if widget is None:
            return None
        index = widget.index("@{},{}".format(event.x, event.y))
        url = self.note_link_at(index)
        if not url:
            return None
        open_url(url)
        return "break"

    def note_render_line(self, widget, line):
        start = widget.index("end-1c")

        heading = re.match(r"^(#{1,3})\s+(.*)$", line)
        if heading:
            level = len(heading.group(1))
            tag = "h1" if level == 1 else "h2"
            self.note_insert_inline(widget, heading.group(2))
            end = widget.index("end-1c")
            widget.tag_add(tag, start, end)
            widget.insert("end", "\n")
            return

        bullet = re.match(r"^\s*[-*+]\s+(.*)$", line)
        if bullet:
            widget.insert("end", "\u2022  ")
            mark_end = widget.index("end-1c")
            self.note_insert_inline(widget, bullet.group(1))
            end = widget.index("end-1c")
            widget.tag_add("li", start, end)
            widget.tag_add("mark", start, mark_end)
            widget.insert("end", "\n")
            return

        ordered = re.match(r"^\s*(\d+[.)])\s+(.*)$", line)
        if ordered:
            mark = ordered.group(1) + "  "
            widget.insert("end", mark)
            mark_end = widget.index("end-1c")
            self.note_insert_inline(widget, ordered.group(2))
            end = widget.index("end-1c")
            widget.tag_add("li", start, end)
            widget.tag_add("mark", start, mark_end)
            widget.insert("end", "\n")
            return

        quote = re.match(r"^\s*>\s?(.*)$", line)
        if quote:
            widget.insert("end", "\u258f  ")
            mark_end = widget.index("end-1c")
            self.note_insert_inline(widget, quote.group(1))
            end = widget.index("end-1c")
            widget.tag_add("quote", start, end)
            widget.tag_add("mark", start, mark_end)
            widget.insert("end", "\n")
            return

        self.note_insert_inline(widget, line)
        widget.insert("end", "\n")

    def note_insert_inline(self, widget, text):
        """处理 **加粗** 和 `代码`"""
        parts = re.split(r"(\*\*.+?\*\*|`[^`]+`)", text)
        for part in parts:
            if not part:
                continue
            start = widget.index("end-1c")
            if part.startswith("**") and part.endswith("**") and len(part) > 4:
                widget.insert("end", part[2:-2])
                end = widget.index("end-1c")
                widget.tag_add("bold", start, end)
            elif part.startswith("`") and part.endswith("`") and len(part) > 2:
                widget.insert("end", part[1:-1])
                end = widget.index("end-1c")
                widget.tag_add("code", start, end)
            else:
                widget.insert("end", part)

    def close_note(self):
        win = self.note_win
        if win is None:
            return
        text = self.note_text
        item = self.note_item
        editing = self.note_editing
        raw = self.note_raw

        self.note_win = None
        self.note_text = None
        self.note_item = None
        self.note_editing = True
        self.note_raw = ""
        self._note_link_job = None

        content = ""
        if editing and text is not None:
            try:
                content = text.get("1.0", "end").strip()
            except Exception:
                content = ""
        elif raw:
            content = raw.strip()

        try:
            win.destroy()
        except Exception:
            pass
        if item is None:
            return
        if content:
            item["note"] = content
        else:
            item.pop("note", None)
        self.store.save()
        self.refresh()

    # ---------------- 设置 ----------------
    def open_settings(self, pos=None):
        if self.settings_win is not None:
            try:
                self.settings_win.lift()
                return
            except Exception:
                self.settings_win = None

        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg=C_BORDER)
        self.settings_win = win

        body = tk.Frame(win, bg=C_BG)
        body.pack(fill="both", expand=True, padx=1, pady=1)

        head = tk.Frame(body, bg=C_HEAD, height=30)
        head.pack(fill="x")
        head.pack_propagate(False)
        tk.Label(head, text="设置", bg=C_HEAD, fg=C_FG,
                 font=self.f_small).pack(side="left", padx=10)
        close = tk.Label(head, text="\u2715", bg=C_HEAD, fg=C_FG_DIM,
                         font=self.f_small, width=2, cursor="hand2")
        close.pack(side="right", padx=4)
        close.bind("<Button-1>", lambda ev: self.close_settings())

        tk.Label(body, text="配色", bg=C_BG, fg=C_FG_DIM,
                 font=self.f_small).pack(anchor="w", padx=12, pady=(10, 4))

        chips = tk.Frame(body, bg=C_BG)
        chips.pack(fill="x", padx=12)
        for key, label in THEME_NAMES:
            self.make_theme_chip(chips, key, label)

        accent_row = tk.Frame(body, bg=C_BG, cursor="hand2")
        accent_row.pack(fill="x", padx=12, pady=(14, 10))
        tk.Label(accent_row, text="强调色", bg=C_BG, fg=C_FG_DIM,
                 font=self.f_small).pack(side="left")
        swatch = tk.Frame(accent_row, bg=C_ACCENT, width=26, height=16,
                          highlightthickness=1,
                          highlightbackground=C_BORDER)
        swatch.pack(side="left", padx=8)
        swatch.pack_propagate(False)
        tk.Label(accent_row, text="点这里自定义", bg=C_BG, fg=C_FG_FAINT,
                 font=self.f_small).pack(side="left")
        for w in (accent_row, swatch):
            w.bind("<Button-1>", lambda ev: self.pick_accent())

        drag = {}

        def start_move(ev):
            drag["dx"] = ev.x_root - win.winfo_x()
            drag["dy"] = ev.y_root - win.winfo_y()

        def do_move(ev):
            if "dx" not in drag:
                return
            win.geometry("+{}+{}".format(ev.x_root - drag["dx"],
                                         ev.y_root - drag["dy"]))

        head.bind("<Button-1>", start_move)
        head.bind("<B1-Motion>", do_move)

        width, height = 262, 166
        if pos is None:
            right = self.root.winfo_rootx() + self.root.winfo_width()
            bottom = self.root.winfo_rooty() + self.root.winfo_height()
            x = right - width - 8
            y = bottom + 6
            screen_h = self.root.winfo_screenheight()
            if y + height > screen_h - 40:
                y = bottom - height - 8  # 下面放不下就压在窗口里
        else:
            x, y = pos
        win.geometry("{}x{}+{}+{}".format(width, height, x, y))
        win.lift()

    def make_theme_chip(self, parent, key, label):
        theme = THEMES[key]
        chosen = (key == self.theme)

        cell = tk.Frame(parent, bg=C_BG, cursor="hand2")
        cell.pack(side="left", padx=(0, 12))

        border = C_FG if chosen else C_BORDER
        swatch = tk.Frame(cell, bg=theme["accent"], width=30, height=20,
                          highlightthickness=1 if not chosen else 2,
                          highlightbackground=border)
        swatch.pack()
        swatch.pack_propagate(False)

        name_color = C_FG if chosen else C_FG_DIM
        name = tk.Label(cell, text=label, bg=C_BG, fg=name_color,
                        font=self.f_small)
        name.pack(pady=(3, 0))

        for widget in (cell, swatch, name):
            widget.bind("<Button-1>", lambda ev, k=key: self.choose_theme(k))

    def choose_theme(self, key):
        pos = None
        if self.settings_win is not None:
            pos = (self.settings_win.winfo_x(), self.settings_win.winfo_y())
        self.close_settings()
        self.theme = key
        self.accent = None
        set_theme(key, None)
        self.save_conf()
        self.reload_ui()
        self.open_settings(pos)

    def pick_accent(self):
        from tkinter import colorchooser
        rgb, picked = colorchooser.askcolor(color=C_ACCENT, parent=self.root,
                                            title="选择强调色")
        if not picked:
            return
        pos = None
        if self.settings_win is not None:
            pos = (self.settings_win.winfo_x(), self.settings_win.winfo_y())
        self.close_settings()
        self.accent = picked
        set_theme(self.theme, picked)
        self.save_conf()
        self.reload_ui()
        self.open_settings(pos)

    def close_settings(self):
        win = self.settings_win
        self.settings_win = None
        if win is not None:
            try:
                win.destroy()
            except Exception:
                pass

    def reload_ui(self):
        """配色变了就整块重建界面, 省得一个个去改颜色"""
        self.finish_edit()
        self.close_note()
        for widget in list(self.root.winfo_children()):
            try:
                widget.destroy()
            except Exception:
                pass

        was_folded = self.collapsed
        self.collapsed = False
        self.build_ui()
        self.refresh()
        self.apply_window()
        if was_folded:
            self.set_folded(True)

        if self._tray is not None:
            try:
                self._tray.icon = make_icon()
            except Exception:
                pass

    # ---------------- 菜单 ----------------
    def popup_header(self, e):
        m = tk.Menu(self.root, tearoff=0)
        m.add_command(label="显示 / 隐藏", command=self.hide)
        m.add_separator()
        m.add_checkbutton(label="总在最前", command=self.toggle_topmost,
                          variable=tk.BooleanVar(value=self.topmost))
        m.add_command(label="退出", command=self.quit)
        m.tk_popup(e.x_root, e.y_root)

    def popup(self, e):
        iid = self.tree.identify_row(e.y)
        if iid:
            self.tree.selection_set(iid)
            self.tree.focus(iid)
        has = bool(iid)
        m = tk.Menu(self.root, tearoff=0)
        m.add_command(label="新建任务", command=self.add_top)
        m.add_command(label="新建子任务", command=self.add_child, state="normal" if has else "disabled")
        m.add_command(label="重命名", command=lambda: self.start_edit(self.tree.focus()),
                      state="normal" if has else "disabled")
        m.add_separator()
        m.add_command(label="上移", command=lambda: self.move(-1),
                      state="normal" if has else "disabled")
        m.add_command(label="下移", command=lambda: self.move(1),
                      state="normal" if has else "disabled")
        m.add_separator()
        m.add_command(label="删除", command=self.delete_selected,
                      state="normal" if has else "disabled")
        m.add_separator()
        m.add_command(label="全部展开", command=lambda: self.collapse_all(False))
        m.add_command(label="全部折叠", command=lambda: self.collapse_all(True))
        m.tk_popup(e.x_root, e.y_root)

    # ---------------- 窗口形态 ----------------
    def apply_window(self):
        r = self.root
        r.withdraw()
        r.overrideredirect(self.mode == "desktop")
        try:
            r.attributes("-topmost", bool(self.topmost))
            r.attributes("-alpha", float(self.alpha))
        except Exception:
            pass
        geom = self.conf.get("geom")
        if geom:
            r.geometry(geom)
        else:
            sw, sh = r.winfo_screenwidth(), r.winfo_screenheight()
            r.geometry("330x460+{}+{}".format(sw - 370, max(70, sh // 10)))
        r.deiconify()
        r.lift()
        if self.mode == "desktop" and not self.topmost:
            r.after(150, self.sink)
        r.after(60, self.round_window)
        self.save_conf()

    def set_mode(self, mode):
        if mode == self.mode:
            return
        self.save_geom()
        self.mode = mode
        self.save_conf()
        self.apply_window()

    def toggle_topmost(self):
        self.topmost = not self.topmost
        try:
            self.root.attributes("-topmost", self.topmost)
            if self.topmost:
                self.root.lift()
        except Exception:
            pass
        self.save_conf()
        if not self.topmost and self.mode == "desktop":
            self.root.after(100, self.sink)

    def sink(self):
        """把窗口压到所有普通窗口下面(贴着桌面)"""
        try:
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            if not hwnd:
                hwnd = self.root.winfo_id()
            HWND_BOTTOM = 1
            SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x0001, 0x0002, 0x0010
            ctypes.windll.user32.SetWindowPos(
                hwnd, HWND_BOTTOM, 0, 0, 0, 0,
                SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE)
        except Exception:
            pass

    def grab_focus(self, e):
        # 正在改名时点输入框自己, 别把焦点抢走
        if self._editor is not None and e.widget is self._editor:
            return
        try:
            self.root.focus_force()
        except Exception:
            pass

    def on_focus_out(self, e):
        # 窗口整体失去焦点(点了别的程序)也要结束改名
        if self._editor is not None:
            try:
                still_in_app = self.root.focus_get() is not None
            except Exception:
                still_in_app = False
            if not still_in_app:
                self.finish_edit()
        if self.mode != "desktop":
            return
        self.root.after(250, self.maybe_sink)

    def maybe_sink(self):
        if self.mode != "desktop" or self.topmost or self._dragging:
            return
        try:
            if self.root.focus_get() is None:
                self.sink()
        except Exception:
            pass

    def hide(self):
        self.save_geom()
        if self._tray is None:  # 没有托盘就别真藏起来, 最小化到任务栏
            self.set_mode("window")
            self.root.iconify()
            return
        self.root.withdraw()

    def show(self):
        self.root.deiconify()
        self.root.lift()
        try:
            self.root.focus_force()
        except Exception:
            pass

    def toggle_window(self):
        if self.root.state() == "withdrawn":
            self.show()
        else:
            self.hide()

    # ---------------- 托盘 ----------------
    def start_tray(self):
        if not HAS_TRAY:
            return
        image = make_icon()
        menu = pystray.Menu(
            pystray.MenuItem("显示 / 隐藏", lambda: self.call(self.toggle_window), default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("贴到桌面（占桌面, 不占任务栏）",
                             lambda: self.call(self.set_mode, "desktop"),
                             checked=lambda i: self.mode == "desktop", radio=True),
            pystray.MenuItem("普通窗口（占任务栏）",
                             lambda: self.call(self.set_mode, "window"),
                             checked=lambda i: self.mode == "window", radio=True),
            pystray.MenuItem("总在最前", lambda: self.call(self.toggle_topmost),
                             checked=lambda i: self.topmost),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("新建任务", lambda: self.call(self.show_and_add)),
            pystray.MenuItem("打开数据文件", lambda: self.call(os.startfile, self.store.path)),
            pystray.MenuItem("重载数据", lambda: self.call(self.reload)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", lambda: self.call(self.quit)),
        )
        self._tray = pystray.Icon("todo_widget", image, "待办清单", menu)
        try:
            self._tray.run_detached()
        except Exception:
            threading.Thread(target=self._tray.run, daemon=True).start()

    def call(self, fn, *args):
        try:
            self.root.after(0, lambda: fn(*args))
        except Exception:
            pass

    def show_and_add(self):
        self.show()
        self.add_top()

    def reload(self):
        self.store.load()
        self.normalize()
        self.refresh()

    def quit(self):
        self.save_geom()
        if self._tray is not None:
            try:
                self._tray.stop()
            except Exception:
                pass
        try:
            self.root.after(0, self.root.destroy)
        except Exception:
            pass


def hex_to_rgb(value):
    """'#5b9cff' -> (91, 156, 255)"""
    text = value.lstrip("#")
    if len(text) != 6:
        return (91, 156, 255)
    try:
        return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))
    except ValueError:
        return (91, 156, 255)


def make_icon(size=64):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    red, green, blue = hex_to_rgb(C_ACCENT)
    d.rounded_rectangle([2, 2, size - 3, size - 3], radius=14,
                        fill=(red, green, blue, 255))
    w = max(4, size // 9)
    d.line([(size * 0.24, size * 0.52), (size * 0.43, size * 0.72),
            (size * 0.76, size * 0.30)], fill=(255, 255, 255, 255), width=w,
           joint="curve")
    return img


def single_instance():
    """返回 False 表示已有实例在跑"""
    try:
        kernel32 = ctypes.windll.kernel32
        h = kernel32.CreateMutexW(None, False, "DesktopTodoWidgetMutex")
        if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            return False, h
        return True, h
    except Exception:
        return True, None


def log_error(exc, val, tb):
    """把 Tk 回调里的异常写到文件, pythonw 下没有控制台也能查"""
    import traceback
    path = os.path.join(APP_DIR, "todo_error.log")
    try:
        with open(path, "a", encoding="utf-8") as f:
            stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            f.write("\n==== {} ====\n".format(stamp))
            traceback.print_exception(exc, val, tb, file=f)
    except Exception:
        pass


class TkApp(tk.Tk):
    def report_callback_exception(self, exc, val, tb):
        log_error(exc, val, tb)


def run_selftest():
    """自检: 直接调用界面里公开的处理链, 不碰真实鼠标键盘

    用法: py -3 todo.py --selftest
    """
    data_path = os.path.join(APP_DIR, "todo_selftest_data.json")
    if os.path.exists(data_path):
        os.remove(data_path)

    conf_backup = None
    if os.path.exists(CONF_FILE):
        with open(CONF_FILE, encoding="utf-8") as f:
            conf_backup = f.read()

    TodoApp.start_tray = lambda self: None
    root = TkApp()
    app = TodoApp(root, store=Store(data_path))
    results = []

    def check(name, ok):
        results.append((name, bool(ok)))

    def settle(times=5):
        for _ in range(times):
            root.update()
            time.sleep(0.02)

    def find(text):
        for iid, ref in app._refs.items():
            if ref["item"]["text"] == text:
                return iid
        return None

    settle(8)

    # 不写死任务名, 直接取第一条叶子任务和第一个分组
    first_leaf = None
    second_leaf = None
    first_group = None
    for iid, ref in app._refs.items():
        item = ref["item"]
        if item.get("children"):
            if first_group is None:
                first_group = iid
        else:
            if first_leaf is None:
                first_leaf = iid
            elif second_leaf is None:
                second_leaf = iid

    target = first_leaf
    app.simulate_double_click(target)
    settle()
    check("双击弹出便签", app.note_win is not None)

    if app.note_win is not None:
        app.note_text.insert("1.0", "自检写入的备注")
    time.sleep(0.45)  # 越过"刚打开不关"的保护
    app.simulate_click(second_leaf)
    settle()
    note_text = app._refs[target]["item"].get("note")
    closed = app.note_win is None
    check("点别处关闭便签并保存内容", closed and note_text == "自检写入的备注")

    state_before = app._refs[target]["item"]["done"]
    app.simulate_click(target, on_box=True)
    settle()
    state_after = app._refs[target]["item"]["done"]
    check("点勾选框可以切换完成", state_before != state_after)

    parent = first_group
    parent_x = app.row_content_x(parent)
    app.tree.focus(parent)
    app.tree.selection_set(parent)
    app.add_child()
    time.sleep(0.1)
    settle()
    editor = app._editor
    indented = False
    if editor is not None:
        indented = editor.winfo_x() > parent_x
    check("新增子任务按层级缩进", indented)
    app.finish_edit()
    settle()

    total = len(app._refs)
    app.collapse_all(True)
    settle()
    collapsed = sum(1 for iid in app._refs if app.tree.bbox(iid))
    check("全部折叠生效", collapsed == len(app.store.items))
    app.collapse_all(False)
    settle()
    expanded = sum(1 for iid in app._refs if app.tree.bbox(iid))
    check("全部展开生效", expanded == total)

    app.set_tab("done")
    settle()
    wrong = []
    for ref in app._refs.values():
        is_root = app.tree.parent(ref["item"]["id"]) == ""
        if is_root and not ref["item"]["done"]:
            wrong.append(ref["item"]["text"])
    check("已完成页只放整条完成的根任务", not wrong)
    app.set_tab("pending")
    settle()

    root.destroy()
    if conf_backup is not None:
        with open(CONF_FILE, "w", encoding="utf-8") as f:
            f.write(conf_backup)
    if os.path.exists(data_path):
        os.remove(data_path)

    failed = 0
    for name, ok in results:
        mark = "OK  " if ok else "FAIL"
        print("  [{}] {}".format(mark, name))
        if not ok:
            failed += 1
    print("\n自检: {}/{} 通过".format(len(results) - failed, len(results)))
    return 1 if failed else 0


def main():
    if "--selftest" in sys.argv:
        sys.exit(run_selftest())

    ok, _handle = single_instance()
    if not ok:
        ctypes.windll.user32.MessageBoxW(
            None, "待办清单已经在运行了。\n图标在右下角托盘里，双击即可显示。",
            "待办清单", 0x40)
        return

    root = TkApp()
    try:
        if ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("todowidget.app")
    except Exception:
        pass
    TodoApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
