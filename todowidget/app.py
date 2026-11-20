# -*- coding: utf-8 -*-
"""主窗口外壳: 布局、页签、折叠、窗口形态、托盘"""

import ctypes
import json
import os
import threading
import time

import tkinter as tk
from tkinter import ttk

try:
    import pystray
except Exception:
    pystray = None

from .paths import APP_DIR, CONF_FILE
from .store import Store
from . import theme as T
from .anim import Tween, ease_in_out_cubic, mix_hex
from .theme import (P, GRADIENTS, apply_palette, custom_scheme, hex_to_rgb,
                    mix_color, pick_font, set_theme)
from .utils import HAS_TRAY, make_icon, place_window

if HAS_TRAY:
    from PIL import Image, ImageChops, ImageDraw, ImageTk
from .ui_list import ListViewMixin
from .ui_lists import ListMenuMixin
from .ui_note import NoteMixin
from .ui_settings import SettingsMixin

# 色键透明用的颜色: 主窗口里刷成这个色的地方会被当成透明
SKIN_KEY = "#010203"


class TodoApp(ListViewMixin, ListMenuMixin, NoteMixin, SettingsMixin):
    """主窗口(按功能拆在几个 Mixin 里)"""

    def __init__(self, root, store=None):
        self.root = root
        self.store = store or Store()
        self.conf = self.load_conf()
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
        self._finish_edit = None
        self._tray = None
        self.collapsed = False
        self._expanded_size = None
        self.resize_locked = bool(self.conf.get("resize_locked", False))
        self._resize_from = None
        self._resizing = False
        self._resize_job = None
        self._resize_target = None
        self.skin_win = None
        self.skin_label = None
        self.skin_photo = None
        self._skin_image = None
        self._skin_plain = None
        self._skin_size = None
        self._skin_region_size = None
        self._skin_crop_job = None
        self._skin_target = None
        self._folded_size = None
        self._skin_source = None
        self._skin_source_path = None
        self._skin_key = None
        self._skin_avg = None
        self._skin_avg_path = None
        self._skin_stack_job = None
        self._skin_sync_job = None
        self._skin_geom = None
        self._skin_stretched = None
        # 主窗口当前的圆角区域大小, 免得重复设
        self._main_region_size = None
        # 列表那层半透明膜的缓存: (宽, 高, 浓度) -> 圆角遮罩
        self._scrim_cache = {}
        # 这一版底图上到底铺上膜没有(刚启动时布局还没算好, 铺不上要补一次)
        self._scrim_drawn = False
        self._scrim_body_size = None
        self._fold_job = None
        self._animating = False
        self._frozen = []
        self._title_target = None
        self._title_tween = None
        self._title_swapped = False
        self.tab = self.conf.get("tab", "pending")
        self.sort_mode = self.conf.get("sort_mode", "manual")
        self._day_open = {}
        self._days_collapsed = False
        self.theme = self.conf.get("theme", "dark")
        self.accent = self.conf.get("accent") or None
        self.custom_themes = self.conf.get("themes") or []
        self.show_stat = bool(self.conf.get("show_stat", True))
        # 图片皮肤时列表底图的三档: frost 磨砂膜 / solid 纯色 / off 不铺
        mode = self.conf.get("scrim_mode")
        if not mode:
            mode = "frost" if self.conf.get("scrim", True) else "off"
        self.scrim_mode = mode if mode in ("frost", "solid", "off") else "frost"
        # 外观细节(边框 / 顶底栏)存在配色里, 这里先给默认值
        self.border_mode = "none"
        self.border_width = 2
        self.border_color = "#3b7cf6"
        self.border_color2 = "#8a5cf6"
        self.header_split = False
        self.header_color = "#17181d"
        self.footer_split = False
        self.footer_color = "#17181d"
        self.bg_image = ""
        self._theme_image = ""
        self.settings_win = None
        self.settings_tab = "look"
        self.notes = {}
        self.note_by_widget = {}
        self.prompt_win = None
        self._drag_from = (0, 0)
        self._drag_moved = False

        self.apply_palette_choice()
        self.build_ui()
        self.normalize()
        self.refresh()
        folded = bool(self.conf.get("collapsed"))
        self.apply_window()
        if folded:
            self.set_folded(True, animate=False)
        self.start_tray()

    # ---------------- 配置 ----------------

    def load_conf(self):
        try:
            with open(CONF_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def save_conf(self):
        self.conf.update(topmost=self.topmost, alpha=self.alpha,
                         collapsed=bool(self.collapsed), tab=self.tab,
                         sort_mode=self.sort_mode,
                         theme=self.theme, accent=self.accent,
                         resize_locked=bool(self.resize_locked),
                         show_stat=bool(self.show_stat),
                         themes=self.custom_themes)
        try:
            with open(CONF_FILE, "w", encoding="utf-8") as f:
                json.dump(self.conf, f, ensure_ascii=False, indent=1)
        except Exception:
            pass

    def save_geom(self):
        if self.root.state() != "normal" or self._animating:
            return
        w, h = self.root.winfo_width(), self.root.winfo_height()
        if self.collapsed and self._expanded_size:
            w, h = self._expanded_size
        self.conf["geom"] = "{}x{}+{}+{}".format(w, h, self.root.winfo_x(),
                                                 self.root.winfo_y())
        self.save_conf()

    # ---------------- 界面 ----------------

    def gradient_theme(self, key=None):
        """按 key 找一份内置渐变配色; 不传就找当前用的

        :param key: 主题键, 形如 'gradient:deep_sea'
        """
        key = key or self.theme
        if not str(key).startswith("gradient:"):
            return None
        return GRADIENTS.get(str(key)[len("gradient:"):])

    def custom_theme(self, key=None):
        """按 key 找一份自定义配色; 不传就找当前用的"""
        key = key or self.theme
        if not str(key).startswith("custom:"):
            return None
        theme_id = str(key)[len("custom:"):]
        for theme in self.custom_themes:
            if theme.get("id") == theme_id:
                return theme
        return None

    def bg_image_path(self):
        """当前主题的背景图片绝对路径, 没有就返回空"""
        path = self._theme_image or ""
        if not path:
            return ""
        if os.path.isabs(path):
            return path if os.path.exists(path) else ""
        full = os.path.join(APP_DIR, path.replace("/", os.sep))
        return full if os.path.exists(full) else ""

    def apply_palette_choice(self):
        """按当前主题和质感选一套配色"""
        self._theme_image = ""
        custom = self.custom_theme()
        grad = self.gradient_theme()
        if grad is not None:
            mid = mix_color(grad.get("start") or "#17181d",
                            grad.get("end") or "#2a2a40", 0.5)
            apply_palette(custom_scheme(mid, grad.get("accent") or "#5b9cff",
                                        grad.get("fg") or None))
        elif custom is not None:
            bg = custom.get("bg") or "#17181d"
            mode = custom.get("mode") or ("image" if custom.get("image") else "solid")
            # 先记下图片路径, 算平均色要用
            self._theme_image = custom.get("image") or ""
            if mode == "gradient":
                bg = mix_color(custom.get("grad_start") or bg,
                               custom.get("grad_end") or bg, 0.5)
            elif mode == "image":
                # 图片主题按图上的平均色配一套颜色, 浅色图才会配深字
                average = self.skin_average(custom)
                if average is not None:
                    bg = "#{:02x}{:02x}{:02x}".format(*average)
            apply_palette(custom_scheme(bg, custom.get("accent") or "#5b9cff",
                                        custom.get("fg") or None))
            self._theme_image = custom.get("image") or ""
        else:
            set_theme(self.theme, self.accent)
        if self.skin_spec() is not None:
            # 压在底图上时灰字太淡就糊了, 次要文字离背景别拉太远
            P.done = mix_color(P.fg, P.bg, 0.35)
            P.fg_dim = mix_color(P.fg, P.bg, 0.22)
            P.fg_faint = mix_color(P.fg, P.bg, 0.45)
        extras = self.theme_extras()
        self.scrim_mode = extras["scrim_mode"]
        self.border_mode = extras["border_mode"]
        self.border_width = extras["border_width"]
        self.border_color = extras["border_color"]
        self.border_color2 = extras["border_color2"]
        self.header_split = extras["header_split"]
        self.header_color = extras["header_color"]
        self.footer_split = extras["footer_split"]
        self.footer_color = extras["footer_color"]
        self.bg_image = self.bg_image_path()

    def build_ui(self):
        # 皮肤相关缓存跟着重建一起重算(透明色/底图平均色都跟主题走)
        self._skin_key = None
        self._skin_avg = None
        self._skin_avg_path = None
        self._skin_stack_job = None
        self._skin_sync_job = None
        self._skin_geom = None
        self._skin_stretched = None
        self._main_region_size = None
        # 换主题后膜的浓度和底色都变了, 缓存作废
        self._scrim_cache = {}
        self._scrim_drawn = False
        self.apply_palette_choice()
        self.stop_title_fade()
        self._frozen = []
        # 重建界面时旧的皮肤窗口已经被销毁, 这里把引用清掉
        self.skin_win = None
        self.skin_label = None
        self.skin_photo = None
        self._skin_image = None
        self._skin_size = None
        self._skin_region_size = None
        self._skin_crop_job = None
        self._head_rect = None
        r = self.root
        r.title("待办清单")
        r.configure(bg=P.bg)
        r.overrideredirect(True)
        r.minsize(270, 220)

        self.f_title = pick_font(r, 11, "bold")
        self.f_group = pick_font(r, 10, "bold")
        self.f_group_done = pick_font(r, 10, "bold", True)
        self.f_item = pick_font(r, 10)
        self.f_item_done = pick_font(r, 10, overstrike=True)
        self.f_small = pick_font(r, 8)
        # 皮肤模式文字是压在底图上的, 加粗一点抗锯齿的边就不那么显糊
        if self.skin_spec() is not None:
            self.f_item_skin = pick_font(r, 10, "bold")
            self.f_item_skin_done = pick_font(r, 10, "bold", True)
            # 列表项加粗后跟分组一样重, 分组放大一号把层次找回来
            self.f_group_skin = pick_font(r, 11, "bold")
            self.f_group_skin_done = pick_font(r, 11, "bold", True)
            # 日期这种小字压在图上本来就糊, 放大一号
            self.f_small_skin = pick_font(r, 9)
        else:
            self.f_item_skin = self.f_item
            self.f_item_skin_done = self.f_item_done
            self.f_group_skin = self.f_group
            self.f_group_skin_done = self.f_group_done
            self.f_small_skin = self.f_small
        self.f_note_h1 = pick_font(r, 13, "bold")
        self.f_note_h2 = pick_font(r, 11, "bold")
        self.f_note_bold = pick_font(r, 10, "bold")

        # 有边框时内容往里让出一圈, 那一圈透出皮肤窗口画的边框
        inner = tk.Frame(r, bg=P.bg)
        pad = self.border_pad()
        inner.pack(fill="both", expand=True, padx=pad, pady=pad)
        self.inner = inner
        # 边框占的那一圈也算"卡片四周的留白", 收起横条时要把它算进宽度
        self._frame_pad = pad
        card = tk.Frame(inner, bg=P.bg)
        card.pack(fill="both", expand=True)
        self.card = card

        # 勾选框用小图片画, 比字符清楚, 也方便只点框勾选
        self.img_on = self.make_box(True)
        self.img_off = self.make_box(False)

        # ---- 顶栏 ----
        head = tk.Frame(card, bg=P.head, height=40)
        head.pack(fill="x", side="top")
        head.pack_propagate(False)
        self._head = head

        # 顶栏底色画在画布上: 收起动画时每帧重画一遍, 擦掉按钮移动留下的残影
        self.head_bg = tk.Canvas(head, bg=P.head, highlightthickness=0, bd=0)
        self.head_bg.place(x=0, y=0, relwidth=1, relheight=1)

        self.list_dot = tk.Canvas(head, width=10, height=10, bg=P.head,
                                  highlightthickness=0, bd=0)
        self.list_dot.pack(side="left", padx=(14, 2), pady=(2, 0))
        self.lbl_title = tk.Label(head, text="待办", bg=P.head, fg=P.fg,
                                  font=self.f_title, cursor="hand2")
        self.lbl_title.pack(side="left", padx=(0, 8))
        # 未完成条数: 宽度固定, 太长就省略号; 设置里可以关掉
        self.stat_box = tk.Frame(head, bg=P.head, width=82, height=22)
        self.stat_box.pack(side="left", pady=(2, 0))
        self.stat_box.pack_propagate(False)
        self.lbl_stat = tk.Label(self.stat_box, text="", bg=P.head,
                                 fg=P.fg_dim, font=self.f_small, anchor="w")
        self.lbl_stat.pack(fill="both", expand=True)

        def icon_btn(text, cmd):
            b = tk.Label(head, text=text, bg=P.head, fg=P.fg_dim,
                         font=self.f_item, width=2, cursor="hand2")
            b.pack(side="right", padx=(0, 4), pady=8)
            b.bind("<Button-1>", lambda e, c=cmd: c())
            b.bind("<Enter>", lambda e, w=b: w.configure(fg=P.fg, bg=P.bg_alt))
            b.bind("<Leave>", lambda e, w=b: w.configure(fg=P.fg_dim, bg=P.head))
            return b

        icon_btn("\u2715", self.hide)
        icon_btn("\uff0b", self.add_top)
        self.btn_fold = icon_btn("\u25b4", self.toggle_fold)

        # 总进度条
        track = tk.Frame(card, bg=P.border, height=2)
        track.pack(fill="x", side="top")
        track.pack_propagate(False)
        self._track = track
        self.pbar = tk.Frame(track, bg=P.accent, height=2)
        self.pbar.place(x=0, y=0, relheight=1, relwidth=0)

        # ---- 未完成 / 已完成 两个页签 ----
        tabbar = tk.Frame(card, bg=P.bg, height=34)
        tabbar.pack(fill="x", side="top")
        tabbar.pack_propagate(False)
        self._tabbar = tabbar
        self.f_tab = pick_font(r, 9, "bold")
        self.tab_labels = {}
        self.tab_bars = {}
        for key, text in (("pending", "未完成"), ("done", "已完成")):
            cell = tk.Frame(tabbar, bg=P.bg, cursor="hand2")
            cell.pack(side="left", padx=(12, 6), pady=(6, 0))
            lbl = tk.Label(cell, text=text, bg=P.bg, fg=P.fg_dim,
                           font=self.f_tab, cursor="hand2")
            lbl.pack()
            bar = tk.Frame(cell, bg=P.bg, height=2)
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
            target_x = e.x_root - self._drag[0]
            target_y = e.y_root - self._drag[1]
            if self.skin_win is None:
                # 纯色主题没有皮肤窗口, 直接挪主窗口
                r.geometry("+{}+{}".format(target_x, target_y))
            else:
                self.sync_skin(x=target_x, y=target_y, instant=True)

        def end_drag(e, as_click=False):
            moved = getattr(self, "_drag_moved", False)
            self._drag = None
            self._drag_moved = False
            self.save_geom()
            if as_click and not moved and not self.collapsed:
                self.open_list_menu(e)

        for widget in (head, self.head_bg, self.lbl_stat):
            widget.bind("<Button-1>", start_drag)
            widget.bind("<B1-Motion>", on_drag)
            widget.bind("<ButtonRelease-1>", lambda ev: end_drag(ev))
            widget.bind("<Button-3>", self.popup_header)

        # 左上角的清单名: 点一下下拉, 按住拖动则是挪窗口
        self.lbl_title.bind("<Button-1>", start_drag)
        self.lbl_title.bind("<B1-Motion>", on_drag)
        self.lbl_title.bind("<ButtonRelease-1>", lambda ev: end_drag(ev, True))
        self.lbl_title.bind("<Button-3>", self.popup_header)
        for widget in (head, self.head_bg):
            widget.bind("<Double-Button-1>", lambda e: self.toggle_collapse_all())

        # ---- 列表 ----
        body = tk.Frame(card, bg=P.bg)
        body.pack(fill="both", expand=True, padx=(6, 3), pady=(6, 0))
        self._body = body

        style = ttk.Style(r)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.layout("Todo.Treeview", [("Todo.Treeview.treearea", {"sticky": "nswe"})])
        style.configure("Todo.Treeview", background=P.bg, fieldbackground=P.bg,
                        foreground=P.fg, borderwidth=0, relief="flat",
                        indent=18, rowheight=28, font=self.f_item)
        style.map("Todo.Treeview", background=[("selected", P.sel)],
                  foreground=[("selected", "#ffffff")])
        style.layout("Todo.Vertical.TScrollbar", [
            ("Vertical.Scrollbar.trough", {"sticky": "ns", "children": [
                ("Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})]})])
        # 滚动条的拖动块用主题色, 别用灰的
        style.configure("Todo.Vertical.TScrollbar", background=P.accent,
                        troughcolor=P.bg, bordercolor=P.bg, arrowcolor=P.fg_dim,
                        darkcolor=P.accent, lightcolor=P.accent,
                        relief="flat", width=7)

        self.tree = ttk.Treeview(body, show="tree", style="Todo.Treeview",
                                 selectmode="browse", columns=("pin",))
        self.tree.column("pin", width=26, minwidth=18, stretch=False,
                         anchor="center")
        sb = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview,
                           style="Todo.Vertical.TScrollbar")
        self.scroll = sb
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y", pady=2)
        self.tree.pack(side="left", fill="both", expand=True)
        # 列表区大小定下来以后, 底下那层膜要按新区域重铺(窗口刚改大时布局会晚一拍)
        body.bind("<Configure>", self.on_body_configure, add="+")

        # Treeview 的 tag 优先级跟定义顺序有关, 混着用会串色,
        # 所以每行的状态只用一个 tag, 悬停/拖放都是独立的一套
        base_cfg = {
            "group": dict(font=self.f_group_skin, foreground=P.group,
                          background=P.group_bg),
            "group_done": dict(font=self.f_group_skin_done, foreground=P.done,
                               background=P.group_bg),
            "item": dict(font=self.f_item_skin, foreground=P.fg),
            "item_done": dict(font=self.f_item_skin_done, foreground=P.done),
        }
        for name, cfg in base_cfg.items():
            self.tree.tag_configure(name, **cfg)
            hover = dict(cfg, background=P.hover)
            self.tree.tag_configure(name + "_h", **hover)
            drop = dict(cfg, background="#4a3f22")
            self.tree.tag_configure("drop_" + name, **drop)
        self.tree.tag_configure("empty", font=self.f_item, foreground=P.fg_faint)
        self.tree.tag_configure("sep", font=self.f_small_skin, foreground=P.fg_dim)
        self.tree.tag_configure("day", font=self.f_small_skin, foreground=P.fg_dim)

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

        self.hint = tk.Frame(self.tree, bg=P.accent, height=2)

        self.tree.bind("<ButtonPress-1>", self.on_press, add="+")
        self.tree.bind("<B1-Motion>", self.on_drag, add="+")
        self.tree.bind("<ButtonRelease-1>", self.on_release, add="+")
        self.tree.bind("<Configure>", self.on_tree_configure, add="+")
        self.tree.bind("<Motion>", self.on_hover, add="+")
        self.tree.bind("<Leave>", lambda e: self.clear_hover(), add="+")

        # 无边框窗口点击时不会自动获得焦点, 手动抢一下, 否则键盘快捷键失效
        for w in (r, inner, card, body, self.tree):
            w.bind("<Button-1>", self.grab_focus, add="+")

        # ---- 底栏 ----
        foot = tk.Frame(card, bg=P.bg, height=32)
        foot.pack(fill="x", side="bottom")
        foot.pack_propagate(False)
        self._foot = foot
        line = tk.Frame(card, bg=P.border, height=1)
        line.pack(fill="x", side="bottom")
        self._line = line

        def flat_btn(parent, text, cmd):
            b = tk.Label(parent, text=text, bg=P.bg, fg=P.fg_faint,
                         font=self.f_small, cursor="hand2", padx=7)
            b.pack(side="left", pady=7)
            b.bind("<Button-1>", lambda e: cmd())
            b.bind("<Enter>", lambda e, w=b: w.configure(fg=P.fg))
            b.bind("<Leave>", lambda e, w=b: w.configure(fg=P.fg_faint))
            return b

        flat_btn(foot, "\uff0b 新建", self.add_top)
        flat_btn(foot, "展开", lambda: self.collapse_all(False))
        flat_btn(foot, "折叠", lambda: self.collapse_all(True))

        tip_text = "按时间排序" if self.sort_mode == "time" else "双击便签 · 拖动排序"

        # 右下角三道斜纹: 无边框窗口没有系统边框, 靠它拖宽高
        self.grip = tk.Canvas(foot, width=14, height=14, bg=P.bg,
                              highlightthickness=0, bd=0, cursor="sizing")
        for offset in (4, 8, 12):
            self.grip.create_line(14 - offset, 12, 12, 14 - offset,
                                  fill=P.fg_faint)
        self.grip.pack(side="right", padx=(0, 5), pady=(0, 3), anchor="s")
        self.grip.bind("<ButtonPress-1>", self.start_resize)
        self.grip.bind("<B1-Motion>", self.on_resize)
        self.grip.bind("<ButtonRelease-1>", self.end_resize)

        gear = tk.Label(foot, text="\u2699", bg=P.bg, fg=P.fg_faint,
                        font=self.f_item, cursor="hand2", width=2)
        gear.pack(side="right", padx=(0, 4))
        gear.bind("<Button-1>", lambda e: self.open_settings())
        gear.bind("<Enter>", lambda e, w=gear: w.configure(fg=P.fg))
        gear.bind("<Leave>", lambda e, w=gear: w.configure(fg=P.fg_faint))
        self._gear = gear

        self.tip = tk.Label(foot, text=tip_text, bg=P.bg,
                            fg=P.fg_faint, font=self.f_small)
        self.tip.pack(side="right", padx=(4, 2))

        # 底栏和分隔线先占好位置, 列表最后 pack 去分剩下的空间,
        # 不然窗口拖矮时列表会把底栏整个挤没
        body.pack_forget()
        body.pack(fill="both", expand=True, padx=(6, 3), pady=(6, 0))

        # 最小化/恢复、藏到托盘/再显示, 皮肤窗口都跟着主窗口走
        r.bind("<Map>", lambda e: self.sync_skin_later(), add="+")
        r.bind("<Unmap>", lambda e: self.sync_skin_later(), add="+")
        r.bind("<FocusOut>", self.on_focus_out)
        r.bind("<Button-1>", self.on_any_click, add="+")
        r.bind("<Configure>", self.on_win_configure, add="+")
        r.bind("<Control-q>", lambda e: self.quit())
        self.set_window_icon()
        self.apply_resize_state()
        if self.skin_spec() is not None:
            self.apply_skin_key()
        # 纯色模式要把列表区盖成不透明底, 必须放在 apply_skin_key 之后
        self.apply_panel_mode()
        self.apply_border_frame()
        self.apply_bars()
        # 重建界面后按当前宽度再摆一次, 免得统计/提示停在旧状态
        self._win_size = None
        self.fit_width(self.root.winfo_width())

    def set_window_icon(self):
        """给窗口换成本程序的图标, 不设的话任务栏会显示 Tk 的羽毛"""
        if not HAS_TRAY:
            return
        try:
            photo = ImageTk.PhotoImage(make_icon(64))
            self._icon_photo = photo
            self.root.iconphoto(True, photo)
        except Exception:
            pass

    def update_stat(self, pending):
        """顶栏的未完成条数: 固定宽度, 放不下就用省略号

        :param pending: 还没完成的条数
        """
        full = "{} 项未完成".format(pending)
        width = self.stat_box.winfo_width() - 6
        if width < 20:
            width = 76
        text = full
        if self.f_small.measure(full) > width:
            while text and self.f_small.measure(text + "\u2026") > width:
                text = text[:-1]
            text = (text + "\u2026") if text else ""
        self.lbl_stat.config(text=text)

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
                red, green, blue = hex_to_rgb(P.accent)
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

    def title_text(self):
        """当前该显示的标题文字和鼠标样式"""
        if self.collapsed:
            return "待办清单", "arrow"
        name = self.store.current_name()
        if len(name) > 10:
            name = name[:9] + "\u2026"
        return name + "  \u25be", "hand2"

    def update_title(self):
        """左上角标题: 收起时固定显示"待办清单", 展开时显示当前清单名"""
        text, cursor = self.title_text()
        self.lbl_title.config(cursor=cursor)
        if self._title_tween is not None:
            # 正在淡出淡入, 让它到中间换字时再取最新文字
            self._title_target = text
            return
        self._title_target = None
        self.lbl_title.config(text=text, fg=P.fg)

    def stop_title_fade(self):
        """停掉还没跑完的标题淡化, 颜色恢复成正常"""
        if self._title_tween is not None:
            self._title_tween.stop()
            self._title_tween = None
        self._title_target = None
        self._title_swapped = False
        try:
            self.lbl_title.config(fg=P.fg)
        except Exception:
            pass

    def fade_title(self):
        """标题先淡出, 换成当前该显示的文字, 再淡回来

        用按真实时间推进的补间(而不是固定几步), 中间帧够多, 看着才顺。
        """
        text, cursor = self.title_text()
        self.lbl_title.config(cursor=cursor)
        self.stop_title_fade()
        # 皮肤模式下顶栏是透明的, 往透明色上淡才自然
        backdrop = self.skin_key() if self.skin_spec() is not None else P.head
        self._title_target = text
        self._title_swapped = False

        def frame(progress):
            if progress < 0.5:
                ratio = progress * 2.0
                self.lbl_title.config(fg=mix_hex(P.fg, backdrop, ratio))
                return
            if not self._title_swapped:
                self._title_swapped = True
                self.lbl_title.config(text=self._title_target or text)
            ratio = (progress - 0.5) * 2.0
            self.lbl_title.config(fg=mix_hex(backdrop, P.fg, ratio))

        def done():
            self._title_tween = None
            self._title_target = None
            self._title_swapped = False
            self.lbl_title.config(fg=P.fg)

        self._title_tween = Tween(self.root, 0.26, frame, on_done=done,
                                  easing=ease_in_out_cubic)
        self._title_tween.start()

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
                text="未完成 {}".format(total - done))
            self.tab_labels["done"].config(
                text="已完成 {}".format(done))
            pending_color = P.accent
            done_color = T.TAB_COLORS.get("done") or P.accent
            self.tab_labels["pending"].config(
                fg=pending_color if self.tab == "pending" else P.fg_dim)
            self.tab_labels["done"].config(
                fg=done_color if self.tab == "done" else P.fg_dim)
            empty = self.empty_bar_bg()
            self.tab_bars["pending"].config(
                bg=pending_color if self.tab == "pending" else empty)
            self.tab_bars["done"].config(
                bg=done_color if self.tab == "done" else empty)
        except Exception:
            pass

    def toggle_fold(self):
        self.set_folded(not self.collapsed)

    def folded_width(self):
        """收起时横条要多宽: 按顶栏内容量出来, 不留一大片空白

        统计文字收起时不显示, 也不计入宽度; 标题按收起后固定的
        "待办清单" 量, 免得按清单名量出过宽或过窄。
        """
        head = self._head
        head.update_idletasks()
        width = 0
        for child in head.winfo_children():
            if child is self.stat_box or child is self.head_bg:
                continue
            if child is self.lbl_title:
                width += self.f_title.measure("待办清单")
                continue
            width += child.winfo_reqwidth()
        # 圆点 padx(14, 2)、标题 padx(0, 8)、三个按钮各 padx(0, 4) 的留白
        width += 14 + 2 + 8 + 3 * 4 + 4
        # 图片主题时卡片四周的留白(现在没有外框了)
        width += 2 * getattr(self, "_frame_pad", 0)
        return max(140, width)

    def set_folded(self, folded, on_done=None, animate=True):
        """右上角折叠: 平滑地收成一条窄横条 / 展开回原来的大小

        :param folded: True 收起, False 展开
        :param on_done: 动画跑完后要做的事(比如展开后马上新建)
        :param animate: 要不要过渡动画(启动时直接摆好, 别闪一下)
        """
        if folded == self.collapsed:
            if on_done is not None:
                on_done()
            return
        self.collapsed = bool(folded)
        if animate:
            self.fade_title()
        else:
            self.update_title()
        # 动画期间窗口比较矮, 先放开正常的最小尺寸, 结束再恢复
        folded_h = 42 + 2 * self._frame_pad
        self.root.minsize(140, folded_h)
        start_w = max(1, self.root.winfo_width())
        start_h = max(1, self.root.winfo_height())
        if self.collapsed:
            w, h = self.root.winfo_width(), self.root.winfo_height()
            if self._animating and self._expanded_size:
                # 展开动画还没跑完就又收起, 目标仍按原来的展开尺寸
                w, h = self._expanded_size
            if w < 120 or h < 120:
                try:
                    size = self.conf.get("geom", "").split("+")[0]
                    w, h = (int(v) for v in size.split("x"))
                except Exception:
                    w, h = 330, 460
            self._expanded_size = (w, h)
            self.btn_fold.config(text="\u25be")
            # 收起后不看统计, 先把这一行去掉, 横条才缩得窄
            self.stat_box.pack_forget()
            target_w, target_h = self.folded_width(), folded_h
            self._folded_size = (target_w, target_h)
            # 下面的内容钉住不动, 跟着窗口边缘被裁掉
            if animate:
                self.freeze_content()
            animator = self.animate_collapse if animate else None
        else:
            self.restore_layout()
            self._folded_size = None
            self.btn_fold.config(text="\u25b4")
            target_w, target_h = self._expanded_size or (330, 460)
            # 先撑到最终大小把内容排好; 无边框窗口再用显示区域把它"放"出来
            self.root.geometry("{}x{}".format(target_w, target_h))
            # 先只把皮肤窗口撑到目标大小, 区域留到下面按横条裁,
            # 不然这一瞬间皮肤会整个铺开闪一下
            self.sync_skin(target_w, target_h, clip=False)
            self.clip_skin(start_w, start_h)
            self.fit_width(target_w)
            animator = self.animate_reveal if animate else None

        def finish():
            if self.collapsed:
                self.finish_collapse(target_w, target_h)
            else:
                self.finish_expand(target_w, target_h)
            if on_done is not None:
                on_done()

        if animator is None:
            self.root.geometry("{}x{}".format(target_w, target_h))
            self.fit_width(target_w)
            finish()
        else:
            animator(start_w, start_h, target_w, target_h, finish)
        self.save_conf()

    def restore_layout(self):
        """把顶栏下面的部分重新装回来

        底栏和分隔线先占位, 列表最后 pack 去分剩下的空间, 免得被挤掉。
        """
        self.attach_head()
        self.unfreeze_content()
        self._track.pack(fill="x", side="top")
        self._tabbar.pack(fill="x", side="top")
        self._foot.pack(fill="x", side="bottom")
        self._line.pack(fill="x", side="bottom")
        self._body.pack(fill="both", expand=True, padx=(6, 3), pady=(6, 0))

    def attach_head(self):
        """把收起动画里单独摆的顶栏装回 pack"""
        head = self._head
        if head.winfo_manager() == "place":
            head.place_forget()
        if head.winfo_manager() != "pack":
            head.pack(fill="x", side="top")

    def freeze_content(self):
        """把顶栏下面的部件按当前尺寸钉住

        收起动画里窗口一直在变小, 如果让 pack 每帧重排, 列表会被压扁、
        页签只露半截; 钉住以后就只是被窗口边缘裁掉, 像拉窗帘一样。
        """
        frozen = []
        for widget in (self._track, self._tabbar, self._body,
                       self._foot, self._line):
            manager = widget.winfo_manager()
            if manager != "pack" or not widget.winfo_ismapped():
                continue
            geo = (widget.winfo_x(), widget.winfo_y(),
                   widget.winfo_width(), widget.winfo_height())
            widget.pack_forget()
            widget.place(x=geo[0], y=geo[1], width=geo[2], height=geo[3])
            frozen.append(widget)
        self._frozen = frozen

    def unfreeze_content(self):
        """放开钉住的部件, 之后可以重新 pack"""
        for widget in self._frozen:
            try:
                widget.place_forget()
            except Exception:
                pass
        self._frozen = []

    def paint_head_bg(self, width=None):
        """重画顶栏底色, 擦掉按钮移动后留在原地的残影

        :param width: 顶栏当前宽度; 不传就按实际宽度来
        """
        canvas = getattr(self, "head_bg", None)
        if canvas is None:
            return
        w = max(1, width or canvas.winfo_width())
        fill = self.header_bg()
        # 复用同一个矩形, 别每帧删掉再画 —— 删掉的那一瞬间会闪一下
        if getattr(self, "_head_rect", None) is None:
            self._head_rect = canvas.create_rectangle(0, 0, w, 40,
                                                      fill=fill, outline="")
            return
        canvas.coords(self._head_rect, 0, 0, w, 40)
        canvas.itemconfigure(self._head_rect, fill=fill)

    def animate_collapse(self, start_w, start_h, target_w, target_h, done):
        """收起用: 窗口本身不动, 只按缓出曲线把显示区域缩上去

        窗口尺寸一变 Tk 就整块重画, 会闪; 这里保持窗口大小, 只收显示区域,
        顶栏宽度跟着显示区域走(图标平滑左移), 下面的内容钉住被边缘裁掉。

        :param start_w: 起始可见宽度
        :param start_h: 起始可见高度
        :param target_w: 目标宽度
        :param target_h: 目标高度
        :param done: 动画结束后的收尾函数
        """
        self.stop_fold_anim()
        head = self._head
        inner_w = max(1, start_w - 2 * self._frame_pad)
        if head.winfo_manager() != "place":
            head.pack_forget()
            head.place(x=0, y=0, width=inner_w, height=40)
        steps = 14
        state = {"step": 0}

        def tick():
            state["step"] += 1
            ratio = state["step"] / float(steps)
            # 三次缓出: 起步快、收尾慢, 看着不生硬
            eased = 1.0 - (1.0 - ratio) ** 3
            width = max(1, int(round(start_w + (target_w - start_w) * eased)))
            height = max(1, int(round(start_h + (target_h - start_h) * eased)))
            head.place_configure(
                width=max(1, width - 2 * self._frame_pad))
            # 先把顶栏排好、重画底色, 再把显示区域收上来:
            # 不然区域比顶栏窄一帧会切掉右边的按钮, 按钮移动还会留残影
            head.update_idletasks()
            self.paint_head_bg(max(1, width - 2 * self._frame_pad))
            self.round_window(width, height)
            self.clip_skin(width, height)
            self.paint_skin_frame(width, height)
            if state["step"] < steps:
                self._fold_job = self.root.after(16, tick)
                return
            self._fold_job = None
            self._animating = False
            done()

        self._animating = True
        tick()

    def animate_reveal(self, start_w, start_h, target_w, target_h, done):
        """展开用: 窗口已经是最终大小, 只把可见区域从横条慢慢放出来

        内容先按最终尺寸排好再露出, 不会每帧重排版。

        :param start_w: 起始可见宽度
        :param start_h: 起始可见高度
        :param target_w: 目标宽度
        :param target_h: 目标高度
        :param done: 动画结束后的收尾函数
        """
        self.stop_fold_anim()
        steps = 14
        state = {"step": 0}

        def tick():
            state["step"] += 1
            ratio = state["step"] / float(steps)
            eased = 1.0 - (1.0 - ratio) ** 3
            width = int(round(start_w + (target_w - start_w) * eased))
            height = int(round(start_h + (target_h - start_h) * eased))
            self.round_window(max(1, width), max(1, height))
            self.clip_skin(max(1, width), max(1, height))
            self.paint_skin_frame(max(1, width), max(1, height))
            if state["step"] < steps:
                self._fold_job = self.root.after(16, tick)
                return
            self._fold_job = None
            self._animating = False
            done()

        self._animating = True
        # 先把可见区域压回横条大小, 再从这一帧开始放
        self.round_window(max(1, start_w), max(1, start_h))
        tick()

    def stop_fold_anim(self):
        """取消还没跑完的收起 / 展开动画"""
        if self._fold_job is not None:
            try:
                self.root.after_cancel(self._fold_job)
            except Exception:
                pass
            self._fold_job = None
        self._animating = False

    def finish_collapse(self, width=None, height=None):
        """收起动画结束: 卸掉下面的内容, 只留顶栏

        :param width: 收起后的宽度(用动画最后一帧的值, 免得取到旧值)
        :param height: 收起后的高度
        """
        self.unfreeze_content()
        for widget in (self._track, self._tabbar, self._body,
                       self._foot, self._line):
            widget.pack_forget()
        self.stat_box.pack_forget()
        if width and height:
            self.root.geometry("{}x{}".format(width, height))
        self.root.minsize(140, 42 + 2 * self._frame_pad)
        self.apply_resize_state()
        self.round_window(width, height)
        if width and height:
            self.paint_skin_frame(width, height)
        self.sync_skin(width, height)

    def finish_expand(self, width=None, height=None):
        """展开动画结束: 恢复正常窗口的最小尺寸

        :param width: 展开后的宽度
        :param height: 展开后的高度
        """
        self.root.minsize(270, 220)
        self.apply_resize_state()
        self.round_window(width, height)
        self.sync_skin(width, height)

    # ---------------- 拖右下角改宽高 ----------------

    def start_resize(self, e):
        """按下右下角斜纹: 记下起点和当前宽高"""
        if self.resize_locked or self.collapsed:
            return
        self._resize_from = (e.x_root, e.y_root,
                             self.root.winfo_width(), self.root.winfo_height())
        self._resizing = True

    def on_resize(self, e):
        """按住斜纹拖动: 按位移同时改宽和高

        每帧都直接改 geometry 会重画很多遍, 攒一下再改, 拖起来更稳。
        """
        if not self._resize_from:
            return
        x0, y0, w0, h0 = self._resize_from
        width = max(270, w0 + (e.x_root - x0))
        height = max(220, h0 + (e.y_root - y0))
        self._resize_target = (width, height)
        if self._resize_job is None:
            self._resize_job = self.root.after(12, self.apply_resize_size)

    def apply_resize_size(self):
        """把攒下来的目标宽高真正应用到窗口上"""
        self._resize_job = None
        target = getattr(self, "_resize_target", None)
        if not target:
            return
        if self.skin_win is None:
            self.root.geometry("{}x{}".format(int(target[0]), int(target[1])))
            return
        self.sync_skin(target[0], target[1], instant=True)
        self.schedule_skin_crop()

    def end_resize(self, e):
        """松手: 把新的宽高记进配置"""
        if not self._resize_from:
            return
        if self._resize_job is not None:
            try:
                self.root.after_cancel(self._resize_job)
            except Exception:
                pass
            self._resize_job = None
        target = getattr(self, "_resize_target", None)
        if target:
            # 最后一帧可能还没应用, 这里补一次
            self.sync_skin(target[0], target[1], instant=True)
        self._resize_target = None
        self._resize_from = None
        self._resizing = False
        self.round_window()
        # 拖动过程中只是把上一张图拉伸顶上, 松手才正经按最终尺寸裁一次
        self._skin_size = None
        self.refresh_skin_crop()
        self.save_geom()

    def toggle_resize_lock(self):
        """右键顶栏 / 托盘: 锁住或解开自由调节宽高"""
        self.set_resize_locked(not self.resize_locked)

    def set_resize_locked(self, locked):
        """锁住后右下角斜纹收起, 窗口就不能拖大小了"""
        locked = bool(locked)
        if locked == self.resize_locked:
            return
        self.resize_locked = locked
        self.save_conf()
        self.apply_resize_state()

    def apply_resize_state(self):
        """按锁定 / 折叠 决定要不要显示右下角调节柄"""
        locked = bool(getattr(self, "resize_locked", False))
        grip = getattr(self, "grip", None)
        if grip is None:
            return
        show = (not locked and not self.collapsed)
        shown = bool(grip.winfo_manager())
        if show and not shown:
            anchor = getattr(self, "_gear", grip)
            grip.pack(side="right", padx=(0, 5), pady=(0, 3), anchor="s",
                      before=anchor)
        elif not show and shown:
            grip.pack_forget()

    def fit_width(self, width):
        """窗口拖窄时先收起次要文字, 别把折叠、齿轮这些要紧的挤掉"""
        avail = width - 2 * getattr(self, "_frame_pad", 0)
        narrow = avail < 300 or bool(getattr(self, "collapsed", False))
        tip = getattr(self, "tip", None)
        if tip is not None:
            shown = bool(tip.winfo_manager())
            if narrow and shown:
                tip.pack_forget()
            elif not narrow and not shown:
                anchor = getattr(self, "_gear", None)
                options = {"side": "right", "padx": (4, 2)}
                if anchor is not None:
                    options["after"] = anchor
                tip.pack(**options)
        box = getattr(self, "stat_box", None)
        if box is None:
            return
        show = self.show_stat and not self.collapsed and avail >= self.stat_need()
        shown = bool(box.winfo_manager())
        if show and not shown:
            box.pack(side="left", pady=(2, 0), after=self.lbl_title)
        elif not show and shown:
            box.pack_forget()

    def stat_need(self):
        """顶栏放下统计文字至少要多宽"""
        head = self._head
        total = 0
        for child in head.winfo_children():
            if child is self.stat_box or child is self.head_bg:
                continue
            total += child.winfo_reqwidth()
        # 圆点 padx(14, 2)、标题 padx(0, 8)、三个按钮各 padx(0, 4) 的留白
        total += 14 + 2 + 8 + 3 * 4 + 4
        stat_width = self.stat_box.winfo_reqwidth() or 82
        return total + stat_width + 12

    def on_win_configure(self, e):
        if e.widget is not self.root:
            return
        # 等事件处理完再按真实窗口大小同步, 免得用到过期的事件尺寸(会闪一帧大窗口)
        # 动画期间尺寸由动画自己裁, 这里不插手
        if self.skin_win is not None and not self._animating:
            self.sync_skin_later()
        if getattr(self, "_win_size", None) == (e.width, e.height):
            return
        self._win_size = (e.width, e.height)
        self.fit_width(e.width)
        if self.skin_win is not None and not self._animating:
            self.schedule_skin_crop()
        # 动画每帧自己更新圆角区域, 拖动改大小时也别每帧重切, 不然更闪
        if not self._animating and not self._resizing:
            self.root.after(15, self.round_window)

    # ---------------- 图片皮肤 ----------------

    def theme_extras(self):
        """当前配色自带的外观细节: 边框 + 顶栏/底栏

        内置配色没有这些, 就是"不画边框、顶栏底栏跟列表一体";
        自定义配色把它们存在自己身上。
        """
        defaults = {"scrim_mode": "frost",
                    "border_mode": "none", "border_width": 2,
                    "border_color": "#3b7cf6", "border_color2": "#8a5cf6",
                    "header_split": False, "header_color": "#17181d",
                    "footer_split": False, "footer_color": "#17181d"}
        custom = self.custom_theme()
        if custom is None:
            return defaults
        border = custom.get("border") or {}
        mode = border.get("mode")
        scrim = custom.get("scrim")
        return {
            "scrim_mode": scrim if scrim in ("frost", "solid", "off") else "frost",
            "border_mode": mode if mode in ("none", "solid", "gradient") else "none",
            "border_width": max(0, min(8, int(border.get("width") or 2))),
            "border_color": border.get("color") or "#3b7cf6",
            "border_color2": border.get("color2") or "#8a5cf6",
            "header_split": bool(custom.get("header_split")),
            "header_color": custom.get("header_color") or "#17181d",
            "footer_split": bool(custom.get("footer_split")),
            "footer_color": custom.get("footer_color") or "#17181d",
        }

    def skin_spec(self):
        """当前是不是图片/渐变皮肤; 是的话返回一份皮肤说明"""
        if not HAS_TRAY:
            return None
        grad = self.gradient_theme()
        if grad is not None:
            return {"mode": "gradient",
                    "grad_start": grad.get("start") or "#17181d",
                    "grad_end": grad.get("end") or "#2a2a40",
                    "grad_angle": grad.get("angle") or "vertical",
                    "alpha": float(grad.get("alpha") or 0.0)}
        custom = self.custom_theme()
        if custom is None:
            return None
        mode = custom.get("mode") or ("image" if custom.get("image") else "solid")
        if mode == "gradient":
            return custom
        if mode == "image" and custom.get("image") and self.bg_image_path():
            return custom
        return None

    def skin_key(self):
        """皮肤模式里当透明色用的那个颜色

        取底图的平均色再挪开一点点, 这样文字抗锯齿混出来的边也接近图上的颜色,
        不会在字周围留一圈深色描边(看着像空心字)。
        """
        if self._skin_key is not None:
            return self._skin_key
        spec = self.skin_spec()
        if spec is None:
            return SKIN_KEY
        average = self.skin_average(spec)
        if average is None:
            return SKIN_KEY
        reserved = self.skin_reserved_colors(spec)
        key = SKIN_KEY
        # 挪开 1 起步: 大色块的底图平均色正好是它自己, 不挪的话整块都会变透明
        for delta in (1, 2, 3, 5, 8):
            candidate = []
            for index in range(3):
                step = delta if index % 2 == 0 else -delta
                candidate.append((average[index] + step) % 256)
            text = "#{:02x}{:02x}{:02x}".format(*candidate)
            if text not in reserved:
                key = text
                break
        self._skin_key = key
        return key

    def skin_average(self, spec):
        """算底图的平均色, 按图片路径缓存

        :param spec: 自定义配色字典
        """
        mode = spec.get("mode") or ("image" if spec.get("image") else "solid")
        if mode == "gradient":
            start = hex_to_rgb(spec.get("grad_start") or "#1b2030")
            end = hex_to_rgb(spec.get("grad_end") or "#2a2a40")
            return tuple(int(round((start[i] + end[i]) / 2.0)) for i in range(3))
        path = self.bg_image_path()
        if not path:
            return None
        if self._skin_avg is not None and self._skin_avg_path == path:
            return self._skin_avg
        try:
            from PIL import Image
            image = self.skin_source_image(path).resize((8, 8), Image.BILINEAR)
            pixels = list(image.getdata())
            average = []
            for index in range(3):
                total = sum(pixel[index] for pixel in pixels)
                average.append(int(round(total / float(len(pixels)))))
        except Exception:
            return None
        self._skin_avg = tuple(average)
        self._skin_avg_path = path
        return self._skin_avg

    def skin_reserved_colors(self, spec):
        """界面上会用到的实色, 透明色不能跟它们撞

        :param spec: 自定义配色字典
        """
        names = ("bg", "bg_alt", "head", "border", "group_bg", "hover",
                 "fg", "fg_dim", "fg_faint", "accent", "done", "group",
                 "sel", "ghost_bg")
        reserved = set()
        for name in names:
            value = getattr(P, name, None)
            if isinstance(value, str):
                reserved.add(value.lower())
        fg = spec.get("fg")
        if fg:
            reserved.add(str(fg).lower())
        reserved.add("#000000")
        reserved.add("#ffffff")
        return reserved

    def skin_hwnd(self):
        """皮肤窗口的原生句柄(顶层那个; 包装窗口还没建好时返回 0)"""
        win = self.skin_win
        if win is None:
            return 0
        user32 = ctypes.windll.user32
        return user32.GetParent(win.winfo_id()) or 0

    def main_hwnd(self):
        """主窗口的原生句柄"""
        user32 = ctypes.windll.user32
        return user32.GetParent(self.root.winfo_id()) or self.root.winfo_id()

    def skin_source_image(self, path):
        """读一次图片, 缩到 1600 以内缓存起来, 反复裁的时候快

        :param path: 图片路径
        """
        if self._skin_source is not None and self._skin_source_path == path:
            return self._skin_source
        from PIL import Image
        image = Image.open(path).convert("RGB")
        image.thumbnail((1600, 1600), Image.LANCZOS)
        self._skin_source = image
        self._skin_source_path = path
        return image

    def gradient_image(self, spec, width, height):
        """按两个颜色和方向画一张渐变底图

        :param spec: 自定义配色字典(取 grad_start / grad_end / grad_angle)
        :param width: 目标宽
        :param height: 目标高
        """
        from PIL import Image
        start = hex_to_rgb(spec.get("grad_start") or "#1b2030")
        end = hex_to_rgb(spec.get("grad_end") or "#2a2a40")
        mid = tuple(int(round((start[i] + end[i]) / 2.0)) for i in range(3))
        angle = spec.get("grad_angle") or "vertical"
        if angle == "horizontal":
            small = Image.new("RGB", (2, 1))
            small.putpixel((0, 0), start)
            small.putpixel((1, 0), end)
        elif angle == "diagonal":
            small = Image.new("RGB", (2, 2))
            small.putpixel((0, 0), start)
            small.putpixel((1, 0), mid)
            small.putpixel((0, 1), mid)
            small.putpixel((1, 1), end)
        else:
            small = Image.new("RGB", (1, 2))
            small.putpixel((0, 0), start)
            small.putpixel((0, 1), end)
        target = (max(2, int(width)), max(2, int(height)))
        return small.resize(target, Image.BILINEAR)

    def crop_skin_image(self, path, width, height, spec):
        """图片皮肤: 按 cover + 缩放 + 偏移裁成窗口大小

        :param path: 图片路径
        :param width: 目标宽
        :param height: 目标高
        :param spec: 自定义配色字典(取 zoom / offset)
        """
        from PIL import Image
        image = self.skin_source_image(path)
        zoom = float(spec.get("zoom") or 1.0)
        zoom = max(1.0, min(3.0, zoom))
        scale = max(width / float(image.width),
                    height / float(image.height)) * zoom
        new_w = max(width, int(round(image.width * scale)))
        new_h = max(height, int(round(image.height * scale)))
        image = image.resize((new_w, new_h), Image.BILINEAR)
        offset = spec.get("offset") or [0.0, 0.0]
        offset_x = max(-1.0, min(1.0, float(offset[0])))
        offset_y = max(-1.0, min(1.0, float(offset[1])))
        span_x = new_w - width
        span_y = new_h - height
        left = int(round((offset_x + 1.0) / 2.0 * span_x))
        top = int(round((offset_y + 1.0) / 2.0 * span_y))
        return image.crop((left, top, left + width, top + height))

    def skin_base_image(self, spec, width, height):
        """按皮肤模式拿底图: 图片裁一块, 渐变现画一张

        :param spec: 自定义配色字典
        :param width: 目标宽
        :param height: 目标高
        """
        mode = spec.get("mode") or ("image" if spec.get("image") else "solid")
        if mode == "gradient":
            return self.gradient_image(spec, width, height)
        if mode == "solid":
            from PIL import Image
            return Image.new("RGB", (max(2, int(width)), max(2, int(height))),
                             hex_to_rgb(spec.get("bg") or P.bg))
        path = self.bg_image_path()
        if not path:
            return None
        return self.crop_skin_image(path, width, height, spec)

    def make_skin(self):
        """建一块只显示皮肤的窗口, 垫在主窗口下面"""
        if self.render_spec() is None:
            self.destroy_skin()
            return
        if self.skin_win is None:
            win = tk.Toplevel(self.root)
            win.withdraw()
            win.overrideredirect(True)
            win.configure(bg="#000000")
            label = tk.Label(win, bd=0, highlightthickness=0, bg="#000000")
            label.place(x=0, y=0)
            self.skin_win = win
            self.skin_label = label
            self._skin_size = None
            self._skin_geom = None
            self.skin_quiet()
            self.skin_bind_events()
        self.reload_skin_image()
        try:
            self.skin_win.deiconify()
        except Exception:
            pass
        self.drop_skin_child_region()
        self.sync_skin()

    def drop_skin_child_region(self):
        """清掉皮肤子窗口上可能残留的裁剪区域

        以前顶层包装窗口还没建好时把圆角区域设到过子窗口上, 那块区域不会跟着改大小,
        窗口拖大以后下半截就被裁掉了(看着是透明的)。
        """
        win = self.skin_win
        if win is None:
            return
        try:
            ctypes.windll.user32.SetWindowRgn(win.winfo_id(), None, True)
        except Exception:
            pass

    def destroy_skin(self):
        """去掉皮肤窗口"""
        if self._skin_crop_job is not None:
            try:
                self.root.after_cancel(self._skin_crop_job)
            except Exception:
                pass
            self._skin_crop_job = None
        if self._skin_stack_job is not None:
            try:
                self.root.after_cancel(self._skin_stack_job)
            except Exception:
                pass
            self._skin_stack_job = None
        win = self.skin_win
        self.skin_win = None
        self.skin_label = None
        self.skin_photo = None
        self._skin_image = None
        self._skin_plain = None
        self._skin_size = None
        self._skin_region_size = None
        self._skin_geom = None
        self._skin_stretched = None
        if win is not None:
            try:
                win.destroy()
            except Exception:
                pass

    def skin_quiet(self):
        """皮肤窗口不抢焦点、不进 Alt+Tab, 但要能收到鼠标事件用来转发"""
        try:
            user32 = ctypes.windll.user32
            hwnd = self.skin_hwnd()
            gwl_exstyle = -20
            style = user32.GetWindowLongPtrW(hwnd, gwl_exstyle)
            style |= 0x08000000      # WS_EX_NOACTIVATE
            style |= 0x00000080      # WS_EX_TOOLWINDOW
            user32.SetWindowLongPtrW(hwnd, gwl_exstyle, style)
        except Exception:
            pass

    def skin_bind_events(self):
        """皮肤窗口上的鼠标事件都转给主窗口里对应的控件

        背景是色键透明的, 空白处点击会落到皮肤窗口上, 不转发的话点不动。
        """
        win = self.skin_win
        if win is None:
            return
        sequences = ("<Button-1>", "<B1-Motion>", "<ButtonRelease-1>",
                     "<Button-3>", "<Motion>", "<MouseWheel>")
        for sequence in sequences:
            win.bind(sequence,
                     lambda ev, seq=sequence: self.forward_skin_event(ev, seq),
                     add="+")

    def skin_widget_at(self, x, y):
        """按坐标找主窗口里最上层的控件 (x, y 相对主窗口)

        :param x: 相对主窗口的横坐标
        :param y: 相对主窗口的纵坐标
        """
        def walk(widget, local_x, local_y):
            for child in reversed(widget.winfo_children()):
                try:
                    if not child.winfo_ismapped():
                        continue
                    cx, cy = child.winfo_x(), child.winfo_y()
                    cw, ch = child.winfo_width(), child.winfo_height()
                except Exception:
                    continue
                if cx <= local_x < cx + cw and cy <= local_y < cy + ch:
                    found = walk(child, local_x - cx, local_y - cy)
                    return found if found is not None else child
            return None

        found = walk(self.root, x, y)
        return found if found is not None else self.root

    def forward_skin_event(self, event, sequence):
        """把皮肤窗口收到的鼠标事件转给主窗口里的控件

        :param event: 皮肤窗口上的 Tk 事件
        :param sequence: 要转发的绑定序列
        """
        root = self.root
        try:
            x = event.x_root - root.winfo_rootx()
            y = event.y_root - root.winfo_rooty()
            inside = (0 <= x < root.winfo_width()
                      and 0 <= y < root.winfo_height())
            if sequence in ("<B1-Motion>", "<ButtonRelease-1>"):
                # 拖动沿用按下时的控件, 拖出窗口也别断
                target = self._skin_target
            elif not inside:
                return
            else:
                target = self.skin_widget_at(x, y)
            if sequence == "<Button-1>":
                self._skin_target = target
            if target is None:
                return
            local_x = x - (target.winfo_rootx() - root.winfo_rootx())
            local_y = y - (target.winfo_rooty() - root.winfo_rooty())
            options = {"x": local_x, "y": local_y,
                       "rootx": event.x_root, "rooty": event.y_root}
            delta = getattr(event, "delta", 0)
            if delta:
                options["delta"] = delta
            target.event_generate(sequence, **options)
            if sequence == "<ButtonRelease-1>":
                self._skin_target = None
        except Exception:
            pass

    def apply_skin_key(self):
        """把主窗口里的纯色底换成透明色, 让底图从底下透出来

        只改底色, 文字/图标保持不透明。
        """
        key = self.skin_key()
        for widget in (self.root, self.inner, self.card):
            try:
                widget.configure(bg=key)
            except Exception:
                pass
        try:
            # 透明色跟着底图平均色走, 文字抗锯齿的边才不会发黑
            self.root.attributes("-transparentcolor", key)
        except Exception:
            pass

        def recolor(widget):
            for child in widget.winfo_children():
                try:
                    background = child.cget("bg")
                except Exception:
                    background = None
                if background in (P.bg, P.head, P.group_bg):
                    try:
                        child.configure(bg=key)
                    except Exception:
                        pass
                recolor(child)

        recolor(self.card)
        self.paint_head_bg()
        try:
            style = ttk.Style(self.root)
            style.configure("Todo.Treeview", background=key,
                            fieldbackground=key)
            style.configure("Todo.Vertical.TScrollbar", troughcolor=key)
        except Exception:
            pass

    def reload_skin_image(self, width=None, height=None, force=False):
        """按窗口大小把皮肤底图弄好

        :param width: 指定宽度, 不传就用当前窗口的
        :param height: 指定高度
        :param force: 大小没变也重做一遍(比如只是列表区的膜要重铺)
        """
        win = self.skin_win
        spec = self.render_spec()
        if win is None or spec is None:
            return
        given = width is not None and height is not None
        width = max(40, int(width or self.root.winfo_width()))
        height = max(40, int(height or self.root.winfo_height()))
        if not given and self.collapsed and self._expanded_size:
            width, height = self._expanded_size
            width = max(40, width)
            height = max(40, height)
        if not force and self._skin_size == (width, height) and self.skin_photo is not None:
            return
        try:
            image = self.skin_base_image(spec, width, height)
            if image is None:
                return
            # “透明度”是把底图往底色里混, 0% 就是原图满色
            strength = float(spec.get("alpha") or 0.0)
            strength = max(0.0, min(0.6, strength))
            if strength > 0:
                from PIL import Image
                base = Image.new("RGB", image.size, hex_to_rgb(P.bg))
                image = Image.blend(image, base, strength)
            image = self.apply_skin_scrim(image, spec)
            self._skin_plain = image.copy()
            rect = None
            if self.collapsed and self._folded_size:
                folded_w, folded_h = self._folded_size
                rect = (0, 0, folded_w, folded_h)
            image = self.apply_border(image, rect)
            photo = ImageTk.PhotoImage(image)
            self.skin_label.configure(image=photo)
            self.skin_photo = photo
            self._skin_image = image
            self._skin_size = (width, height)
        except Exception:
            pass

    def stretch_skin_image(self, width, height):
        """拖动改大小时先用上一张底图拉伸顶上, 松手再正经裁一次

        正经裁一次要重采样整张原图(10ms 上下), 每帧都这么干拖起来会卡;
        拉伸一张已经裁好的小图不到 1ms, 视觉上也就这一两百毫秒。

        :param width: 目标宽
        :param height: 目标高
        """
        image = self._skin_image
        if image is None:
            return
        width = max(2, int(width))
        height = max(2, int(height))
        if (width, height) == self._skin_stretched:
            return
        self._skin_stretched = (width, height)
        try:
            from PIL import Image
            sized = image.resize((width, height), Image.BILINEAR)
            photo = ImageTk.PhotoImage(sized)
            self.skin_label.configure(image=photo)
            self.skin_photo = photo
            # 记成"没正经裁过": 松手 / 空闲时会按最终尺寸重裁
            self._skin_size = None
        except Exception:
            pass

    def skin_scrim_alpha(self, spec):
        """列表上那层磨砂膜要多浓(0 就是不铺)

        :param spec: 自定义配色字典
        """
        mode = spec.get("mode") or ("image" if spec.get("image") else "solid")
        if self.scrim_mode != "frost":
            return 0.0
        # 渐变本身是干净的, 只有照片会把文字衬得看不清
        return 0.3 if mode == "image" else 0.0

    def panel_solid(self):
        """列表区是不是铺成不透明纯色"""
        return self.skin_spec() is not None and self.scrim_mode == "solid"

    def panel_color(self):
        """纯色列表的底色: 在主题底色上压一点, 看着像一块面板"""
        return mix_color(P.bg, "#000000", 0.05)

    def border_pad(self):
        """内容要给边框让出多少像素"""
        if not self.border_active():
            return 0
        return max(1, int(self.border_width))

    def border_active(self):
        """是不是要画边框"""
        return self.border_mode in ("solid", "gradient") and self.border_width > 0

    def render_spec(self):
        """画底图用的规格

        皮肤主题用它自己的; 纯色主题只开了边框时, 也给皮肤窗口一块纯色底,
        边框才有地方画。
        """
        spec = self.skin_spec()
        if spec is not None:
            return spec
        if self.border_active():
            return {"mode": "solid", "bg": P.bg, "alpha": 0.0}
        return None

    def apply_border_frame(self):
        """按边框粗细给内容留出一圈空白, 并让这一圈透出皮肤窗口"""
        pad = self.border_pad()
        try:
            self.inner.pack_configure(padx=pad, pady=pad)
        except Exception:
            pass
        self._frame_pad = pad
        if self.collapsed:
            # 收起横条宽度是按顶栏内容算的, 留白变了要重新量一次
            folded_h = 42 + 2 * pad
            try:
                self._folded_size = (self.folded_width(), folded_h)
                self.root.minsize(140, folded_h)
                self.root.geometry("{}x{}".format(*self._folded_size))
            except Exception:
                pass
        color = P.bg
        if self.skin_spec() is not None or self.border_active():
            color = self.skin_key()
        try:
            self.root.configure(bg=color)
        except Exception:
            pass

    def border_fill(self, width, height):
        """边框那圈用什么颜色/渐变, 返回一张 RGB 图

        :param width: 窗口宽
        :param height: 窗口高
        """
        if self.border_mode == "gradient":
            return self.gradient_image({"grad_start": self.border_color,
                                        "grad_end": self.border_color2,
                                        "grad_angle": "diagonal"},
                                       width, height)
        from PIL import Image
        return Image.new("RGB", (width, height), hex_to_rgb(self.border_color))

    def apply_border(self, image, rect=None, scale=1):
        """在底图外围画一圈边框(圆角跟窗口一致)

        :param image: 已经处理好的底图(RGB)
        :param rect: 边框围着哪一块, 不传就是整张图(收起时传横条那块)
        """
        if not self.border_active():
            return image
        try:
            from PIL import Image, ImageChops, ImageDraw
            left, top, right, bottom = rect or (0, 0) + image.size
            right = min(right, image.width)
            bottom = min(bottom, image.height)
            width = max(2, right - left)
            height = max(2, bottom - top)
            thickness = max(1, min(8, int(self.border_width)))
            radius = max(2, int(round(10 * (scale or 1))))
            scale = 2

            def mask(inset, rad):
                big = Image.new("L", (width * scale, height * scale), 0)
                draw = ImageDraw.Draw(big)
                x0 = inset * scale
                draw.rounded_rectangle(
                    [x0, x0, width * scale - 1 - x0, height * scale - 1 - x0],
                    radius=max(0, rad) * scale, fill=255)
                return big.resize((width, height), Image.LANCZOS)

            outer = mask(0, radius)
            inner = mask(thickness, max(1, radius - thickness))
            ring = ImageChops.subtract(outer, inner)
            image.paste(self.border_fill(width, height), (left, top), ring)
        except Exception:
            pass
        return image

    def paint_skin_frame(self, width, height):
        """按某一帧的可见大小重画底图(带边框), 收起/展开动画用

        :param width: 可见宽
        :param height: 可见高
        """
        base = self._skin_plain
        if base is None or not self.border_active():
            return
        try:
            image = base.copy()
            image = self.apply_border(
                image, (0, 0, max(2, int(width)), max(2, int(height))))
            photo = ImageTk.PhotoImage(image)
            self.skin_label.configure(image=photo)
            self.skin_photo = photo
        except Exception:
            pass

    def header_bg(self):
        """顶栏底色: 单独上色用它, 皮肤模式透明, 纯色主题用主题顶栏色"""
        if self.header_split:
            return self.header_color
        if self.skin_spec() is not None:
            return self.blank_bg()
        return P.head

    def footer_bg(self):
        """底栏底色"""
        if self.footer_split:
            return self.footer_color
        if self.skin_spec() is not None:
            return self.blank_bg()
        return P.bg

    def repaint_area(self, widget, color):
        """把一块区域里"本来是底色"的控件刷成 color(强调色之类不动)

        :param widget: 区域根控件
        :param color: 目标底色
        """
        if widget is None:
            return
        replaceable = set()
        for value in (P.bg, P.head, P.group_bg, self.panel_color(),
                      self.header_color, self.footer_color):
            replaceable.add(str(value).lower())
        try:
            replaceable.add(str(self.skin_key()).lower())
        except Exception:
            pass
        try:
            if str(widget.cget("bg")).lower() in replaceable:
                widget.configure(bg=color)
        except Exception:
            pass

        def repaint(node):
            for child in node.winfo_children():
                try:
                    background = str(child.cget("bg")).lower()
                except Exception:
                    background = None
                if background in replaceable:
                    try:
                        child.configure(bg=color)
                    except Exception:
                        pass
                repaint(child)

        repaint(widget)

    def apply_bars(self):
        """顶栏 / 底栏上色(单独上色时铺自己的颜色)"""
        self.repaint_area(getattr(self, "_head", None), self.header_bg())
        self.repaint_area(getattr(self, "_foot", None), self.footer_bg())
        self.paint_head_bg()

    def blank_bg(self):
        """"透明"那一档用色: 皮肤模式是色键, 否则是主题底色"""
        if self.skin_spec() is None:
            return P.bg
        return self.skin_key()

    def empty_bar_bg(self):
        """页签下面那条细条"未选中"时的颜色"""
        if self.panel_solid():
            return self.panel_color()
        return self.blank_bg()

    def apply_panel_mode(self):
        """按三档模式决定列表区怎么画

        纯色模式给列表区铺不透明底色: 文字底下有真正的背景, ClearType 才不会
        在字周围留一圈色键色的毛边(看着像锯齿/有点底色)。
        """
        color = self.panel_color() if self.panel_solid() else self.blank_bg()
        try:
            style = ttk.Style(self.root)
            style.configure("Todo.Treeview", background=color,
                            fieldbackground=color)
            style.configure("Todo.Vertical.TScrollbar", troughcolor=color,
                            bordercolor=color)
        except Exception:
            pass
        # 只改"当前是透明/面板色"的控件, 强调色的下划线之类不要动
        replaceable = set()
        for value in (P.bg, P.head, P.group_bg, self.panel_color()):
            replaceable.add(str(value).lower())
        try:
            replaceable.add(str(self.skin_key()).lower())
        except Exception:
            pass

        def repaint(widget):
            for child in widget.winfo_children():
                try:
                    background = str(child.cget("bg")).lower()
                except Exception:
                    background = None
                if background in replaceable:
                    try:
                        child.configure(bg=color)
                    except Exception:
                        pass
                repaint(child)

        for widget in (getattr(self, "_tabbar", None), getattr(self, "_body", None)):
            if widget is None:
                continue
            try:
                widget.configure(bg=color)
            except Exception:
                pass
            repaint(widget)
        # 卡片本身也铺上: 列表四周的留白/页签和列表之间的缝就不会漏出照片
        card = getattr(self, "card", None)
        if card is not None:
            try:
                card.configure(bg=color)
            except Exception:
                pass
        self.paint_head_bg()

    def skin_scrim_rect(self):
        """列表(页签 + 列表区)在窗口里的矩形, 拿不到就返回 None"""
        if self.collapsed:
            return None
        tabbar = getattr(self, "_tabbar", None)
        body = getattr(self, "_body", None)
        if tabbar is None or body is None:
            return None
        try:
            if not body.winfo_ismapped() or not tabbar.winfo_ismapped():
                return None
            root_x = self.root.winfo_rootx()
            root_y = self.root.winfo_rooty()
            left = body.winfo_rootx() - root_x
            right = left + body.winfo_width()
            top = tabbar.winfo_rooty() - root_y
            bottom = body.winfo_rooty() - root_y + body.winfo_height()
        except Exception:
            return None
        if right - left < 20 or bottom - top < 20:
            return None
        return (max(0, left), max(0, top), right, bottom)

    def skin_scrim_overlay(self, width, height, alpha):
        """列表上那层膜的圆角遮罩, 按大小缓存

        :param width: 膜的宽
        :param height: 膜的高
        :param alpha: 不透明度 0~1(只影响缓存键)
        """
        key = (width, height, round(alpha, 3))
        mask = self._scrim_cache.get(key)
        if mask is not None:
            return mask
        from PIL import Image, ImageDraw
        scale = 2
        big = Image.new("L", (width * scale, height * scale), 0)
        draw = ImageDraw.Draw(big)
        draw.rounded_rectangle(
            [0, 0, width * scale - 1, height * scale - 1],
            radius=10 * scale, fill=255)
        mask = big.resize((width, height), Image.LANCZOS)
        # 只留最近几份, 别把拖动改大小时的每一帧都攒着
        if len(self._scrim_cache) > 6:
            self._scrim_cache.clear()
        self._scrim_cache[key] = mask
        return mask

    def skin_frost(self, region):
        """把一块底图磨砂: 缩到 1/6 再模糊再放大, 比原图直接高斯快得多

        :param region: 要磨砂的图片区域(RGB)
        """
        from PIL import Image, ImageFilter
        width, height = region.size
        small_w = max(2, int(width / 6))
        small_h = max(2, int(height / 6))
        small = region.resize((small_w, small_h), Image.BILINEAR)
        small = small.filter(ImageFilter.GaussianBlur(2.0))
        return small.resize(region.size, Image.BILINEAR)

    def apply_skin_scrim(self, image, spec):
        """给列表区铺一层半透明膜, 底图再花文字也看得清

        先磨砂(把照片的花纹糊掉), 再往底色里混一点, 最后按圆角遮罩贴回去。

        :param image: 已经裁好的底图(RGB)
        :param spec: 自定义配色字典
        """
        self._scrim_drawn = False
        alpha = self.skin_scrim_alpha(spec)
        if alpha <= 0:
            return image
        rect = self.skin_scrim_rect()
        if rect is None:
            return image
        left, top, right, bottom = rect
        width = min(int(image.width), right) - left
        height = min(int(image.height), bottom) - top
        if width < 8 or height < 8:
            return image
        try:
            region = image.crop((left, top, left + width, top + height))
            frosted = self.skin_frost(region)
            base = Image.new("RGB", frosted.size, hex_to_rgb(P.bg))
            frosted = Image.blend(frosted, base, alpha)
            mask = self.skin_scrim_overlay(width, height, alpha)
            image.paste(frosted, (left, top), mask)
            self._scrim_drawn = True
        except Exception:
            pass
        return image

    def scrim_missing(self):
        """该铺膜却没铺上(启动时布局还没算好), 需要重裁一次底图"""
        if self._resizing:
            # 拖动中不补, 松手时统一重裁
            return False
        spec = self.skin_spec()
        if spec is None or self.skin_scrim_alpha(spec) <= 0:
            return False
        if self._scrim_drawn:
            return False
        return self.skin_scrim_rect() is not None

    def apply_skin_effects(self):
        """边框 / 顶栏底栏颜色改了: 立刻重铺一遍

        需要皮肤窗口(图片主题或开着边框)却没有就建一个, 不需要了就去掉。
        """
        need_skin = self.render_spec() is not None
        try:
            # 边框那一圈要靠色键透出皮肤窗口, 这里跟着开关
            key = self.skin_key() if need_skin else ""
            self.root.attributes("-transparentcolor", key)
        except Exception:
            pass
        if need_skin and self.skin_win is None:
            self.make_skin()
        elif not need_skin and self.skin_win is not None:
            self.destroy_skin()
        self._skin_size = None
        self.apply_border_frame()
        self.apply_panel_mode()
        self.apply_bars()
        if self.skin_win is not None:
            self.reload_skin_image(force=True)
            self.sync_skin()
            self.root.after_idle(self.restack_skin)
        self.refresh()

    def refresh_skin_film(self):
        """列表底图模式(磨砂 / 纯色 / 不铺)改了: 立刻重铺一遍"""
        self._scrim_drawn = False
        self._skin_size = None
        if self.skin_spec() is not None:
            # 先把界面底色打回"透明"的基准, 再按新模式盖
            self.apply_skin_key()
        self.apply_panel_mode()
        self.apply_border_frame()
        self.apply_bars()
        self._skin_size = None
        if self.skin_win is not None:
            self.reload_skin_image(force=True)
            self.sync_skin()
        self.refresh()

    def refresh_skin_crop(self):
        """窗口大小定下来以后重裁一次皮肤底图"""
        if self.skin_win is None or self._animating or self.collapsed:
            return
        if self._resizing:
            # 拖动中走"拉伸上一张图"的快路径, 别在这儿重采样整张原图
            return
        width = max(40, self.root.winfo_width())
        height = max(40, self.root.winfo_height())
        if self._skin_size == (width, height) and not self.scrim_missing():
            return
        self.reload_skin_image(force=True)
        self.sync_skin()

    def schedule_skin_crop(self):
        """拖动改大小时按 ~30fps 重裁, 别每个事件都算一遍"""
        if self.skin_win is None or self._skin_crop_job is not None:
            return
        self._skin_crop_job = self.root.after(30, self.run_skin_crop)

    def run_skin_crop(self):
        """到点重裁一次皮肤底图"""
        self._skin_crop_job = None
        if self.skin_win is None:
            return
        self.refresh_skin_crop()

    def on_body_configure(self, e):
        """列表区尺寸变了: 底下那层膜是按列表区铺的, 得跟着重铺

        :param e: 列表区(列表 + 滚动条)的 Configure 事件
        """
        size = (e.width, e.height)
        if getattr(self, "_scrim_body_size", None) == size:
            return
        self._scrim_body_size = size
        if self.skin_win is None or self._animating:
            return
        self._scrim_drawn = False
        self.sync_skin_later()

    def sync_skin_later(self):
        """把"等会儿再同步皮肤"合并成一次

        窗口一次变化会连着来一串事件, 每个都排一个同步的话,
        皮肤窗口会被反复挪位置/重画, 收起的时候就看着一闪一闪的。
        """
        if self._resizing:
            # 拖动中由 apply_resize_size 逐帧同步, 这里再补一次纯属多干活
            return
        if self._skin_sync_job is not None:
            return
        self._skin_sync_job = self.root.after_idle(self.run_skin_sync)

    def run_skin_sync(self):
        """空闲时补一次皮肤同步"""
        self._skin_sync_job = None
        self.sync_skin()

    def sync_skin(self, width=None, height=None, x=None, y=None, clip=True,
                  instant=False):
        """让皮肤窗口跟着主窗口的位置/大小, 并压在主窗口下面

        :param width: 可见宽度(动画时传当前帧的值)
        :param height: 可见高度
        :param x: 主窗口左上角屏幕坐标, 不传就现取
        :param y: 同上
        :param clip: 要不要顺手把皮肤区域裁成这个大小
        :param instant: 拖动中: 两个窗口用一次 SetWindowPos 同步挪, 不等空闲
        """
        win = self.skin_win
        if win is None:
            return
        if self._animating:
            # 折叠/展开动画每帧自己裁区域, 别让窗口事件用整窗大小盖回去(会闪出一帧大窗口)
            return
        root = self.root
        try:
            if root.state() in ("withdrawn", "iconic"):
                win.withdraw()
                return
            if win.state() != "normal":
                # 主窗口藏起来过又显示出来时, 皮肤窗口也要跟着回来
                win.deiconify()
            try:
                want_top = bool(self.topmost)
                if bool(win.attributes("-topmost")) != want_top:
                    win.attributes("-topmost", want_top)
            except Exception:
                pass
            width = int(width or root.winfo_width())
            height = int(height or root.winfo_height())
            if self.collapsed and self._folded_size:
                # 收起状态固定是横条大小, 别被过期的事件尺寸带偏
                width, height = self._folded_size
            size = (max(2, width), max(2, height))
            if not self.collapsed and (size != self._skin_size or self.scrim_missing()):
                if self._resizing and self._skin_image is not None:
                    # 拖动改大小: 先把上一张图拉伸顶上(不到 1ms), 松手再正经裁
                    self.stretch_skin_image(size[0], size[1])
                else:
                    # 先把底图裁成新尺寸, 再把窗口撑大, 中间不会露出空白
                    self.reload_skin_image(size[0], size[1], force=True)
            # 区域要先裁、位置要后挪: 反过来的话 SetWindowRgn 会把刚挪好的位置作废
            if clip and self._skin_region_size != size:
                self.clip_skin(width, height)
            if x is None:
                x = root.winfo_rootx()
            if y is None:
                y = root.winfo_rooty()
            geometry = (size[0], size[1], int(x), int(y))
            if instant:
                # 拖动时: 主窗口和皮肤窗口一次性挪到位, 不经过 Tk 的空闲队列。
                # 分两帧到的话, 中间那一帧底图会晚半拍, 看着就是闪。
                self.apply_window_rect(*geometry)
                return
            # 顺序不能反: SetWindowPos 会让 Tk 把窗口的旧位置当成"已成事实",
            # 先把窗口排到下面, 再改位置, 位置请求才不会被作废
            self.place_skin_below()
            if geometry != self._skin_geom:
                # 位置大小没变就别再设一遍, 重复设会让皮肤窗口重画(收起时会闪)
                win.geometry("{}x{}+{}+{}".format(*geometry))
                self._skin_geom = geometry
                # 刚设过位置/刚显示出来的顶层窗口有时会被抬到最上面,
                # 等这一轮事件忙完再压回去(压早的话会把位置请求作废)
                self.root.after_idle(self.restack_skin)
        except Exception:
            pass

    def apply_window_rect(self, width, height, x, y):
        """把主窗口和皮肤窗口一起摆到同一块矩形上(拖动时用)

        两个窗口在同一个调用里 SetWindowPos, 桌面合成器会把它们放在同一帧,
        不会出现"底图还在上一格"的那一帧。

        :param width: 宽
        :param height: 高
        :param x: 屏幕横坐标
        :param y: 屏幕纵坐标
        """
        width = max(2, int(width))
        height = max(2, int(height))
        x = int(x)
        y = int(y)
        try:
            user32 = ctypes.windll.user32
            no_zorder = 0x0004
            no_activate = 0x0010
            main = self.main_hwnd()
            user32.SetWindowPos(main, 0, x, y, width, height,
                                no_zorder | no_activate)
            skin = self.skin_hwnd()
            if skin:
                # 顺便把它压在主窗口下面, 一步到位
                user32.SetWindowPos(skin, main, x, y, width, height,
                                    no_activate)
                self._skin_geom = (width, height, x, y)
        except Exception:
            pass

    def place_skin_below(self):
        """把皮肤窗口排到主窗口正下方"""
        try:
            hwnd = self.skin_hwnd()
            if not hwnd:
                # 顶层包装窗口还没建出来, 等这一轮事件忙完再试一次,
                # 不然底图会盖在界面上
                if self._skin_stack_job is None:
                    self._skin_stack_job = self.root.after_idle(
                        self.restack_skin)
                return
            self.stack_skin(hwnd)
        except Exception:
            pass

    def restack_skin(self):
        """补压一次皮肤窗口(包装窗口建好的时候 place_skin_below 还没成)"""
        self._skin_stack_job = None
        hwnd = self.skin_hwnd()
        if not hwnd:
            # 刚建出来的皮肤窗口, Tk 的包装窗口要过一小会儿才有句柄:
            # 隔 30ms 再试几次, 不然它就一直压在界面上
            tries = getattr(self, "_skin_stack_tries", 0) + 1
            self._skin_stack_tries = tries
            if tries <= 12:
                self._skin_stack_job = self.root.after(30, self.restack_skin)
            return
        self._skin_stack_tries = 0
        self.stack_skin(hwnd)

    def stack_skin(self, hwnd):
        """把皮肤窗口的原生句柄压到主窗口下面

        :param hwnd: 皮肤窗口的顶层句柄
        """
        try:
            user32 = ctypes.windll.user32
            gw_hwndprev = 3
            # 主窗口已经紧挨在皮肤上面就不用再排了, 反复 SetWindowPos 会让它重画
            if user32.GetWindow(hwnd, gw_hwndprev) == self.main_hwnd():
                return
            flags = 0x0001 | 0x0002 | 0x0010  # NOSIZE | NOMOVE | NOACTIVATE
            user32.SetWindowPos(hwnd, self.main_hwnd(), 0, 0, 0, 0, flags)
        except Exception:
            pass

    def clip_skin(self, width, height):
        """把皮肤窗口的显示区域裁到指定大小(动画每帧用)

        :param width: 可见宽度
        :param height: 可见高度
        """
        if self.skin_round(width, height):
            self._skin_region_size = (max(2, int(width)), max(2, int(height)))

    def skin_round(self, width, height):
        """皮肤窗口也切圆角, 免得从主窗口四角露出来

        :param width: 圆角区域宽
        :param height: 圆角区域高
        :return: 是否真的设上了(顶层窗口还没建好时设不了)
        """
        try:
            win = self.skin_win
            if win is None:
                return False
            user32 = ctypes.windll.user32
            gdi32 = ctypes.windll.gdi32
            child = win.winfo_id()
            wrapper = user32.GetParent(child)
            if not wrapper:
                # 顶层包装窗口还没建出来。这时往子窗口上设区域,
                # 等包装窗口出来后就会留一块永远按旧大小裁的区域(拖动改大小时下面就是空的)
                return False
            w = max(2, int(width))
            h = max(2, int(height))
            rgn = gdi32.CreateRoundRectRgn(0, 0, w + 1, h + 1, 20, 20)
            user32.SetWindowRgn(wrapper, rgn, True)
            return True
        except Exception:
            return False

    def round_window(self, width=None, height=None):
        """无边框 + 圆角, 看着像个小组件

        动画过程中传当前帧的尺寸进来, 免得 winfo_width 还是上一帧的旧值。
        """
        try:
            w = max(2, int(width or self.root.winfo_width()))
            h = max(2, int(height or self.root.winfo_height()))
            size = (w, h)
            # 大小没变就别再设一遍区域, 每次 SetWindowRgn 都会让窗口重画
            if self._main_region_size == size:
                return
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            if not hwnd:
                return
            rgn = ctypes.windll.gdi32.CreateRoundRectRgn(0, 0, w + 1, h + 1, 20, 20)
            if ctypes.windll.user32.SetWindowRgn(hwnd, rgn, True):
                self._main_region_size = size
            else:
                ctypes.windll.gdi32.DeleteObject(rgn)
        except Exception:
            pass

    def on_any_click(self, e):
        """在窗口里点任何别的地方都结束改名 / 收起没钉住的便签"""
        if self.notes:
            # 双击那次点击也会走到这里, 刚弹出来的便签别马上关掉
            opened_at = getattr(self, "_note_opened_at", 0.0)
            if time.time() - opened_at > 0.4:
                self.close_note(keep_pinned=True)
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

    def popup_header(self, e):
        m = tk.Menu(self.root, tearoff=0)
        m.add_command(label="设置…", command=self.open_settings)
        m.add_separator()
        m.add_command(label="显示 / 隐藏", command=self.hide)
        m.add_separator()
        m.add_checkbutton(label="总在最前", command=self.toggle_topmost,
                          variable=tk.BooleanVar(value=self.topmost))
        m.add_checkbutton(label="锁定窗口大小", command=self.toggle_resize_lock,
                          variable=tk.BooleanVar(value=self.resize_locked))
        m.add_command(label="退出", command=self.quit)
        m.tk_popup(e.x_root, e.y_root)

    def apply_window(self):
        r = self.root
        r.withdraw()
        r.overrideredirect(True)
        # overrideredirect 一改, Tk 会重建顶层包装窗口, 旧的圆角区域跟着没了
        self._main_region_size = None
        skin = self.render_spec()
        alpha = float(self.alpha)
        try:
            r.attributes("-topmost", bool(self.topmost))
            r.attributes("-alpha", alpha)
            if skin is not None:
                # 背景色键透明, 文字保持不透明
                r.attributes("-transparentcolor", self.skin_key())
            else:
                r.attributes("-transparentcolor", "")
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
        self.apply_resize_state()
        if skin is not None:
            self.make_skin()
        else:
            self.destroy_skin()
        if not self.topmost:
            r.after(150, self.sink)
        r.after(60, self.round_window)
        r.after(80, self.sync_skin)
        self.save_conf()

    def toggle_topmost(self):
        self.topmost = not self.topmost
        try:
            self.root.attributes("-topmost", self.topmost)
            if self.topmost:
                self.root.lift()
        except Exception:
            pass
        self.save_conf()
        self.sync_skin()
        self.place_skin_below()
        if not self.topmost:
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
            self.place_skin_below()
        except Exception:
            pass

    def raise_notes(self):
        """让便签始终压在主窗口上面"""
        for state in self.notes.values():
            try:
                state["win"].lift()
            except Exception:
                pass

    def grab_focus(self, e):
        # 正在改名时点输入框自己, 别把焦点抢走
        if self._editor is not None and e.widget is self._editor:
            return
        try:
            self.root.focus_force()
            self.raise_notes()
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
        self.root.after(250, self.maybe_sink)

    def maybe_sink(self):
        if self.topmost or self._dragging:
            return
        if getattr(self, "_resizing", False):
            return
        try:
            if self.root.focus_get() is None:
                self.sink()
        except Exception:
            pass

    def hide(self):
        self.close_settings()
        self.save_geom()
        if self._tray is None:
            # 没有托盘图标就没法再显示出来, 干脆不隐藏
            return
        self.root.withdraw()
        self.sync_skin()

    def show(self):
        self.root.deiconify()
        self.root.lift()
        self.sync_skin()
        try:
            self.root.focus_force()
            self.raise_notes()
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
            pystray.MenuItem("设置…", lambda: self.call(self.open_settings)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("总在最前", lambda: self.call(self.toggle_topmost),
                             checked=lambda i: self.topmost),
            pystray.MenuItem("锁定窗口大小",
                             lambda: self.call(self.toggle_resize_lock),
                             checked=lambda i: self.resize_locked),
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
        self.stop_title_fade()
        self.close_settings()
        self.destroy_skin()
        self.save_geom()
        self.close_note()
        if self._tray is not None:
            try:
                self._tray.stop()
            except Exception:
                pass
        try:
            self.store.close()
        except Exception:
            pass
        try:
            self.root.after(0, self.root.destroy)
        except Exception:
            pass
