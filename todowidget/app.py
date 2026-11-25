# -*- coding: utf-8 -*-
"""主窗口外壳: 布局、页签、折叠、窗口形态、托盘"""

import ctypes
from ctypes import wintypes
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

from .paths import CONF_FILE, DATA_DIR
from .store import Store
from . import theme as T
from .anim import Tween, ease_in_out_cubic, mix_hex
from .listpaint import ListPaintMixin
from . import fonts, screens
from .theme import (P, GRADIENTS, apply_palette, best_text_color,
                    brightness, custom_scheme, hex_to_rgb, mix_color,
                    pick_font, set_theme)
from .utils import HAS_TRAY, make_icon, place_window

if HAS_TRAY:
    from PIL import Image, ImageChops, ImageDraw, ImageTk
from .ui_list import ListViewMixin
from .ui_lists import ListMenuMixin
from .ui_note import NoteMixin
from .ui_settings import SettingsMixin

# 色键透明用的颜色: 主窗口里刷成这个色的地方会被当成透明
SKIN_KEY = "#010203"


class _BitmapHeader(ctypes.Structure):
    """UpdateLayeredWindow 用的 DIB 头"""

    _fields_ = [
        ("biSize", ctypes.c_uint32),
        ("biWidth", ctypes.c_int32),
        ("biHeight", ctypes.c_int32),
        ("biPlanes", ctypes.c_uint16),
        ("biBitCount", ctypes.c_uint16),
        ("biCompression", ctypes.c_uint32),
        ("biSizeImage", ctypes.c_uint32),
        ("biXPelsPerMeter", ctypes.c_int32),
        ("biYPelsPerMeter", ctypes.c_int32),
        ("biClrUsed", ctypes.c_uint32),
        ("biClrImportant", ctypes.c_uint32),
    ]


class _BitmapInfo(ctypes.Structure):
    """DIB 头 + 调色板占位"""

    _fields_ = [("bmiHeader", _BitmapHeader),
                ("bmiColors", ctypes.c_uint32 * 3)]


class _BlendFunction(ctypes.Structure):
    """UpdateLayeredWindow 的混合参数"""

    _fields_ = [("BlendOp", ctypes.c_ubyte),
                ("BlendFlags", ctypes.c_ubyte),
                ("SourceConstantAlpha", ctypes.c_ubyte),
                ("AlphaFormat", ctypes.c_ubyte)]


def _layered_api():
    """取 UpdateLayeredWindow 那套函数, 顺手声明参数/返回类型

    64 位下句柄是指针, 不声明的话 ctypes 会按 int 截断(之前
    MonitorFromWindow 一直拿到主屏就是这个原因)。
    """
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    user32.GetParent.restype = ctypes.c_void_p
    user32.GetParent.argtypes = [ctypes.c_void_p]
    user32.GetWindowLongW.restype = ctypes.c_long
    user32.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]
    user32.SetWindowLongW.restype = ctypes.c_long
    user32.SetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                      ctypes.c_long]
    user32.GetDC.restype = ctypes.c_void_p
    user32.GetDC.argtypes = [ctypes.c_void_p]
    user32.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    user32.UpdateLayeredWindow.restype = ctypes.c_bool
    user32.UpdateLayeredWindow.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(wintypes.POINT),
        ctypes.POINTER(wintypes.SIZE), ctypes.c_void_p,
        ctypes.POINTER(wintypes.POINT), ctypes.c_uint32,
        ctypes.POINTER(_BlendFunction), ctypes.c_uint32]
    gdi32.CreateCompatibleDC.restype = ctypes.c_void_p
    gdi32.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
    gdi32.CreateDIBSection.restype = ctypes.c_void_p
    gdi32.CreateDIBSection.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(_BitmapInfo), ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p, ctypes.c_uint32]
    gdi32.SelectObject.restype = ctypes.c_void_p
    gdi32.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
    gdi32.DeleteDC.argtypes = [ctypes.c_void_p]
    return user32, gdi32


class _SkinPoint:
    """转发双击时用的轻量"事件", 处理函数只需要 x / y"""

    def __init__(self, x, y):
        self.x = x
        self.y = y


class TodoApp(ListViewMixin, ListMenuMixin, NoteMixin, SettingsMixin,
              ListPaintMixin):
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
        self._skin_click = None
        self._skin_layered = False
        self._skin_surface = None
        self._skin_surface_image = None
        self._skin_mask_cache = {}
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
        self._skin_base = None
        # 列表自绘用的字体/文字起点缓存
        self._list_fonts = {}
        self._list_text_x = {}
        self._glyph_ok = {}
        self._list_paint_job = None
        # 弹着菜单的时候不要重画皮肤, 不然会盖住菜单闪一下
        self._menu_open = False
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
        self.favorite_themes = list(self.conf.get("favorites") or [])
        self.show_stat = bool(self.conf.get("show_stat", True))
        # 图片皮肤时列表底图的三档: frost 磨砂膜 / solid 纯色 / off 不铺
        mode = self.conf.get("scrim_mode")
        if not mode:
            mode = "frost" if self.conf.get("scrim", True) else "off"
        self.scrim_mode = mode if mode in ("frost", "solid", "off") else "frost"
        # 外观细节(边框 / 顶底栏)存在配色里, 这里先给默认值
        self.font_cn = ""
        self.font_latin = ""
        self.border_mode = "none"
        self.border_width = 2
        self.border_color = "#3b7cf6"
        self.border_color2 = "#8a5cf6"
        self.radius = 0
        self.header_split = False
        self.header_color = "#17181d"
        self.footer_split = False
        self.footer_color = "#17181d"
        # 顶栏/底栏共用一份配置
        self.bars_split = False
        self.bars_color = "#17181d"
        self.bars_color2 = "#2b2e38"
        self.bars_grad = False
        self.bars_angle = "vertical"
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
        # 删掉的清单保留 30 天, 过期的清掉
        if self.store.purge_deleted(30):
            self.store.save()
        self.apply_window()
        if folded:
            self.set_folded(True, animate=False)
        self.start_tray()
        self.root.after(2500, self.watch_screens)

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
        """记下窗口大小和位置(同时按当前屏幕配置存一份)"""
        if self.root.state() != "normal" or self._animating:
            return
        w, h = self.root.winfo_width(), self.root.winfo_height()
        if self.collapsed and self._expanded_size:
            w, h = self._expanded_size
        geom = "{}x{}+{}+{}".format(w, h, self.root.winfo_x(),
                                    self.root.winfo_y())
        self.conf["geom"] = geom
        key = screens.layout_key()
        if key:
            layouts = dict(self.conf.get("layouts") or {})
            layouts[key] = geom
            self.conf["layouts"] = layouts
            self._screen_key = key
        self.save_conf()

    def pick_geom(self):
        """按当前屏幕配置挑窗口位置

        这套屏幕配置以前记过就用记的位置; 没有或者是旧的(已经跑到屏幕外)
        就夹回当前屏幕里。
        """
        key = screens.layout_key()
        self._screen_key = key
        layouts = self.conf.get("layouts") or {}
        saved = layouts.get(key) or self.conf.get("geom") or ""
        if not saved:
            return ""
        return screens.fit_geom(saved) or saved

    def watch_screens(self):
        """盯着显示器配置: 换了就把窗口摆到那套配置记住的位置"""
        try:
            key = screens.layout_key()
        except Exception:
            key = ""
        if key and self._screen_key and key != self._screen_key:
            # 先把现在的位置记在那套(旧的)配置名下
            self.save_geom()
            self._screen_key = key
            self.place_for_layout(key)
        self.root.after(2500, self.watch_screens)

    def place_for_layout(self, key):
        """把窗口摆到某套屏幕配置记住的位置

        :param key: 屏幕配置标识
        """
        layouts = dict(self.conf.get("layouts") or {})
        geom = layouts.get(key) or ""
        if not geom:
            geom = "{}x{}+{}+{}".format(self.root.winfo_width(),
                                        self.root.winfo_height(),
                                        self.root.winfo_x(),
                                        self.root.winfo_y())
        fixed = screens.fit_geom(geom) or geom
        parsed = screens.parse_geom(fixed)
        if not parsed:
            return
        width, height, x, y = parsed
        if self.collapsed and self._folded_size:
            width, height = self._folded_size
        try:
            self.root.geometry("{}x{}+{}+{}".format(width, height, x, y))
        except Exception:
            return
        self.sync_skin(x=x, y=y)
        self.round_window()
        layouts[key] = "{}x{}+{}+{}".format(width, height, x, y)
        self.conf["layouts"] = layouts
        self.conf["geom"] = layouts[key]
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
        full = os.path.join(DATA_DIR, path.replace("/", os.sep))
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
        self.font_cn = extras["font_cn"]
        self.font_latin = extras["font_latin"]
        self.scrim_mode = extras["scrim_mode"]
        self.border_mode = extras["border_mode"]
        self.border_width = extras["border_width"]
        self.border_color = extras["border_color"]
        self.border_color2 = extras["border_color2"]
        self.radius = extras["radius"]
        self.header_split = extras["header_split"]
        self.header_color = extras["header_color"]
        self.footer_split = extras["footer_split"]
        self.footer_color = extras["footer_color"]
        self.bars_split = extras["bars_split"]
        self.bars_color = extras["bars_color"]
        self.bars_color2 = extras["bars_color2"]
        self.bars_grad = extras["bars_grad"]
        self.bars_angle = extras["bars_angle"]
        self.bg_image = self.bg_image_path()

    def build_ui(self):
        # 先把自带的字体注册进来, 下面建字体时才能用它
        fonts.register_bundled()
        # 皮肤相关缓存跟着重建一起重算(透明色/底图平均色都跟主题走)
        self._skin_key = None
        self._skin_avg = None
        self._skin_avg_path = None
        self._skin_stack_job = None
        self._skin_sync_job = None
        self._skin_geom = None
        self._skin_stretched = None
        self._skin_base = None
        self._list_fonts = {}
        self._list_text_x = {}
        self._glyph_ok = {}
        self._list_paint_job = None
        self._menu_open = False
        self._screen_key = ""
        self._tab_tween = None
        self._drag_target = None
        self._drag_job = None
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

        self.f_title = pick_font(r, 11, "bold", family=self.font_cn)
        self.f_group = pick_font(r, 10, "bold", family=self.font_cn)
        self.f_group_done = pick_font(r, 10, "bold", True, family=self.font_cn)
        self.f_item = pick_font(r, 10, family=self.font_cn)
        self.f_item_done = pick_font(r, 10, overstrike=True, family=self.font_cn)
        self.f_small = pick_font(r, 8, family=self.font_cn)
        # 自绘之后文字是灰度抗锯齿, 不用再加粗; 日期稍微放大一点更好认
        self.f_item_skin = self.f_item
        self.f_item_skin_done = self.f_item_done
        self.f_group_skin = self.f_group
        self.f_group_skin_done = self.f_group_done
        if self.skin_spec() is not None:
            self.f_small_skin = pick_font(r, 9, family=self.font_cn)
        else:
            self.f_small_skin = self.f_small
        self.f_note_h1 = pick_font(r, 13, "bold", family=self.font_cn)
        self.f_note_h2 = pick_font(r, 11, "bold", family=self.font_cn)
        self.f_note_bold = pick_font(r, 10, "bold", family=self.font_cn)

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

        # 只留折叠按钮: 隐藏走右键菜单, 新建走底栏
        self.btn_fold = icon_btn("\u25b4", self.toggle_fold)

        # 总进度条
        track = tk.Frame(card, bg=P.border, height=2)
        track.pack(fill="x", side="top")
        track.pack_propagate(False)
        self._track = track
        self.pbar = tk.Frame(track, bg=P.accent, height=2)
        self.pbar.place(x=0, y=0, relheight=1, relwidth=0)

        # ---- 未完成 / 已完成 两个页签 ----
        # 整个页签区是一块画布: 底色、圆角药丸、文字都自己画,
        # 这样才做得出"药丸滑过去 + 悬停变亮"的效果
        tabbar = tk.Frame(card, bg=P.bg, height=36)
        tabbar.pack(fill="x", side="top")
        tabbar.pack_propagate(False)
        self._tabbar = tabbar
        self.f_tab = pick_font(r, 9, "bold", family=self.font_cn)
        self.f_tab_count = pick_font(r, 8, "normal", family=self.font_cn)
        self.f_switch = pick_font(r, 11, "normal", family=self.font_cn)
        self.f_switch_on = pick_font(r, 11, "bold", family=self.font_cn)
        self.tab_counts = {"pending": 0, "done": 0}
        self._tab_rects = {}
        self._tab_hover = None
        self._tab_pill = None
        self._tab_pill_key = None
        self._tab_tween = None
        self._tab_retry_job = None
        self.tab_indicator = tk.Canvas(tabbar, bg=P.bg, bd=0,
                                       highlightthickness=0, cursor="arrow")
        self.tab_indicator.place(x=0, y=0, relwidth=1, relheight=1)
        self.tab_indicator.bind("<Button-1>", self.on_tab_click)
        self.tab_indicator.bind("<Motion>", self.on_tab_motion)
        self.tab_indicator.bind("<Leave>", lambda ev: self.set_tab_hover(None))

        # 清单切换按钮: 平时只有符号, 悬停出现一圈淡淡的圆底
        self.btn_next_list = self.make_switch_button("\u203a", 1)
        self.btn_prev_list = self.make_switch_button("\u2039", -1)
        for btn in (self.btn_next_list, self.btn_prev_list):
            btn.pack(side="right", padx=(0, 4), pady=(6, 0))

        def start_drag(e):
            self._drag_from = (e.x_root, e.y_root)
            self._drag = (e.x_root - r.winfo_x(), e.y_root - r.winfo_y())
            self._drag_moved = False
            # 拖动期间不推阴影分层表面(每帧 UpdateLayeredWindow 会让整窗闪),
            # 先藏起来, 松手再按新位置摆回来
            self.hide_main_shadow()

        def on_drag(e):
            """鼠标动一下: 只记目标位置, 真正搬窗口由定时器按帧做

            高回报率的鼠标一秒钟能发几百个 motion 事件, 每个都搬一次窗口
            合成器跟不上, 看着就是闪。
            """
            if not self._drag:
                return
            move_x = abs(e.x_root - self._drag_from[0])
            move_y = abs(e.y_root - self._drag_from[1])
            if move_x > 3 or move_y > 3:
                self._drag_moved = True
            self._drag_target = (e.x_root - self._drag[0],
                                 e.y_root - self._drag[1])
            self.apply_drag_move()

        def end_drag(e, as_click=False):
            moved = getattr(self, "_drag_moved", False)
            self._drag_target = None
            self._drag = None
            self._drag_moved = False
            self.cancel_drag_move()
            self.save_geom()
            if moved:
                # 拖动期间只挪位置没动底图, 松手什么也不用补
                self.sync_skin()
            # 阴影拖动期间被 suspend 了, 用 resume 恢复(否则 sync 会因挂起直接返回)
            self.resume_main_shadow()
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
        def on_tree_scroll(first, last):
            """滚动条位置变了: 顺手把自绘的列表重画一遍

            :param first: 可见区起点比例
            :param last: 可见区终点比例
            """
            sb.set(first, last)
            self.list_paint_later()

        self.tree.configure(yscrollcommand=on_tree_scroll)
        # 不显示滚动条: 滚轮/键盘/拖动都照常, 右边不留一条竖条
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
        # 选中变了要重画自绘的底色条
        self.tree.bind("<<TreeviewSelect>>",
                       lambda e: self.list_paint_later(), add="+")
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
            self.list_paint_key_out()
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
        self.lbl_title.config(text=text, fg=self.title_fg())

    def title_fg(self):
        """标题该用的文字色: 就是用户配的文字色"""
        return P.fg

    def stop_title_fade(self):
        """停掉还没跑完的标题淡化, 颜色恢复成正常"""
        if self._title_tween is not None:
            self._title_tween.stop()
            self._title_tween = None
        self._title_target = None
        self._title_swapped = False
        try:
            self.lbl_title.config(fg=self.title_fg())
        except Exception:
            pass

    def fade_title(self):
        """标题先淡出, 换成当前该显示的文字, 再淡回来

        用按真实时间推进的补间(而不是固定几步), 中间帧够多, 看着才顺。
        """
        text, cursor = self.title_text()
        self.lbl_title.config(cursor=cursor)
        self.stop_title_fade()
        if self.skin_spec() is not None or self.bars_on_skin():
            # 顶栏是透明的(皮肤底图 / 渐变栏)时不做淡化:
            # 淡化的中间帧是往透明色键上淡的, 那一帧标题就是透明的(看着像消失)
            self.lbl_title.config(text=text, fg=self.title_fg())
            return
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
            self.lbl_title.config(fg=self.title_fg())

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

    def tab_accent(self, key):
        """这个页签自己的强调色(已完成用绿色)

        :param key: pending / done
        """
        if key == "done":
            return T.TAB_COLORS.get("done") or P.accent
        return P.accent

    def tab_layout(self):
        """算每个页签的位置: 药丸范围 + 文字起始点

        :return: {key: (药物左, 药丸右, 名字 x, 数字 x)}
        """
        rects = {}
        gap = 6
        pad = 12
        x = 10
        for key, name in (("pending", "\u672a\u5b8c\u6210"),
                          ("done", "\u5df2\u5b8c\u6210")):
            name_w = self.f_tab.measure(name)
            count_w = self.f_tab_count.measure(
                str(self.tab_counts.get(key, 0)))
            width = pad * 2 + name_w + 6 + count_w
            rects[key] = (x, x + width, x + pad, x + pad + name_w + 6)
            x += width + gap
        return rects

    def chrome_backdrop(self, x, y, width, height):
        """取窗口里某块区域当前的底色, 用来给抗锯齿做底

        图片皮肤时主窗口是透明的, 看到的是下面皮肤窗口那张底图,
        所以直接把底图上对应的一小块裁出来; 纯色主题就是主题底色。
        拿不到可靠的底色就返回 None, 调用方退回没有抗锯齿的画法。

        :param x: 窗口坐标左
        :param y: 窗口坐标上
        :param width: 宽
        :param height: 高
        """
        if Image is None:
            return None
        width = max(1, int(round(width)))
        height = max(1, int(round(height)))
        image = getattr(self, "_skin_image", None)
        if image is not None:
            try:
                left = int(round(x))
                top = int(round(y))
                right = left + width
                bottom = top + height
                if (left >= 0 and top >= 0 and right <= image.width
                        and bottom <= image.height):
                    return image.crop(
                        (left, top, right, bottom)).convert("RGB")
            except Exception:
                pass
        if self.skin_spec() is None:
            try:
                return Image.new("RGB", (width, height), hex_to_rgb(P.bg))
            except Exception:
                return None
        return None

    def tab_pill_photo(self, width, height, x, y, fill, radius=8):
        """把页签底色画成一张已经抗锯齿的图(上圆下平)

        :param width: 宽
        :param height: 高
        :param x: 这块在窗口里的左边(取底色用)
        :param y: 这块在窗口里的上边
        :param fill: 填充色
        :param radius: 上面的圆角半径
        """
        if Image is None:
            return None
        backdrop = self.chrome_backdrop(x, y, width, height)
        if backdrop is None:
            return None
        scale = 4
        mask = Image.new("L", (width * scale, height * scale), 0)
        drawer = ImageDraw.Draw(mask)
        drawer.rounded_rectangle(
            [0, 0, width * scale - 1, 2 * radius * scale - 1],
            radius=radius * scale, fill=255)
        drawer.rectangle([0, radius * scale, width * scale - 1,
                          height * scale - 1], fill=255)
        mask = mask.resize((width, height), Image.LANCZOS)
        tint = Image.new("RGB", (width, height), hex_to_rgb(fill))
        return ImageTk.PhotoImage(Image.composite(tint, backdrop, mask))

    def circle_photo(self, size, x, y, fill, ring=None):
        """画一个抗锯齿的圆底(箭头按钮的悬停底)

        :param size: 边长
        :param x: 这块在窗口里的左边(取底色用)
        :param y: 这块在窗口里的上边
        :param fill: 填充色
        :param ring: 描边色, 不传就不描
        """
        if Image is None:
            return None
        backdrop = self.chrome_backdrop(x, y, size, size)
        if backdrop is None:
            return None
        scale = 4
        layer = Image.new("RGBA", (size * scale, size * scale),
                          (0, 0, 0, 0))
        drawer = ImageDraw.Draw(layer)
        box = [0, 0, size * scale - 1, size * scale - 1]
        drawer.ellipse(box, fill=hex_to_rgb(fill) + (255,))
        if ring:
            drawer.ellipse(box, outline=hex_to_rgb(ring) + (255,),
                           width=scale)
        layer = layer.resize((size, size), Image.LANCZOS)
        merged = Image.alpha_composite(backdrop.convert("RGBA"), layer)
        return ImageTk.PhotoImage(merged.convert("RGB"))

    def tab_shape(self, canvas, x0, x1, y0, y1, fill, tag, radius=8):
        """页签底色: 上面两个角小圆, 下面两个角是直角

        :param canvas: 画布
        :param x0: 左边
        :param x1: 右边
        :param y0: 上边
        :param y1: 下边
        :param fill: 填充色
        :param tag: 标签, 方便整组删掉
        :param radius: 上面的圆角半径
        """
        height = max(2, y1 - y0)
        width = max(2, x1 - x0)
        radius = max(1, min(radius, height // 2, width // 2))
        # 上半圆: 两个整圆, 下半截会被中间那块矩形盖住
        canvas.create_oval(x0, y0, x0 + 2 * radius, y0 + 2 * radius,
                           fill=fill, outline="", tags=tag)
        canvas.create_oval(x1 - 2 * radius, y0, x1, y0 + 2 * radius,
                           fill=fill, outline="", tags=tag)
        canvas.create_rectangle(x0 + radius, y0, x1 - radius,
                                y0 + radius, fill=fill, outline="", tags=tag)
        # 下面这块是方的
        canvas.create_rectangle(x0, y0 + radius, x1, y1, fill=fill,
                                outline="", tags=tag)

    def paint_tab_pill(self, rect, color=None):
        """画当前页签的药丸底

        :param rect: (左, 右)
        :param color: 底色; 默认按当前页签取
        """
        canvas = getattr(self, "tab_indicator", None)
        if canvas is None or not rect:
            return
        try:
            self._tab_pill = (rect[0], rect[1])
            canvas.delete("pill")
            if color is None:
                ratio = 0.28 if self._tab_hover == self.tab else 0.20
                color = mix_color(self.blank_bg(),
                                  self.tab_accent(self.tab), ratio)
            width = int(round(rect[1] - rect[0]))
            photo = None
            if width >= 6:
                base_x = canvas.winfo_rootx() - self.root.winfo_rootx()
                base_y = canvas.winfo_rooty() - self.root.winfo_rooty()
                photo = self.tab_pill_photo(width, 28,
                                            base_x + int(round(rect[0])),
                                            base_y + 6, color)
            if photo is not None:
                self._tab_pill_photo = photo
                canvas.create_image(int(round(rect[0])), 6, anchor="nw",
                                    image=photo, tags="pill")
            else:
                self.tab_shape(canvas, rect[0], rect[1], 6, 34, color,
                               "pill")
                # 皮肤底图还没出来(刚启动 / 动画中), 等一会儿再画一次
                self.schedule_tab_retry()
            canvas.tag_lower("pill")
        except Exception:
            pass

    def paint_tab_hover(self):
        """悬停在未选中的页签上时, 下面给一层很淡的底"""
        canvas = getattr(self, "tab_indicator", None)
        if canvas is None:
            return
        try:
            canvas.delete("hoverpill")
            key = self._tab_hover
            if not key or key == self.tab:
                return
            rect = self._tab_rects.get(key)
            if not rect:
                return
            fill = mix_color(self.blank_bg(), P.fg, 0.08)
            width = int(round(rect[1] - rect[0]))
            photo = None
            if width >= 6:
                base_x = canvas.winfo_rootx() - self.root.winfo_rootx()
                base_y = canvas.winfo_rooty() - self.root.winfo_rooty()
                photo = self.tab_pill_photo(
                    width, 28, base_x + int(round(rect[0])), base_y + 6,
                    fill)
            if photo is not None:
                self._tab_hover_photo = photo
                canvas.create_image(int(round(rect[0])), 6, anchor="nw",
                                    image=photo, tags="hoverpill")
            else:
                self.tab_shape(canvas, rect[0], rect[1], 6, 34, fill,
                               "hoverpill")
            canvas.tag_lower("hoverpill")
        except Exception:
            pass

    def tab_text_colors(self, key):
        """页签上名字和数量各用什么颜色

        :param key: pending / done
        """
        active = (key == self.tab)
        base = self.tab_accent(key)
        if active:
            return base, mix_color(base, self.blank_bg(), 0.30)
        if key == self._tab_hover:
            return P.fg, P.fg_dim
        return P.fg_dim, P.fg_faint

    def paint_tabs_image(self, pill=None):
        """图片/渐变皮肤下, 整条页签用 PIL 画进底图

        Tk 的 create_text 在色键背景上抗锯齿只能跟色键混色, 压在图上就是
        一圈毛边(空心字); 列表行也是同样处理的, 这里照搬。

        :param pill: 药丸的位置(左, 右), 不传就用当前记录的
        :return: 画成功没有
        """
        canvas = getattr(self, "tab_indicator", None)
        if canvas is None or Image is None or not self.list_paint_active():
            return False
        rects = self._tab_rects
        if not rects:
            return False
        rect = pill or self._tab_pill
        if rect is None:
            return False
        try:
            width = int(max(item[1] for item in rects.values())) + 10
            height = 36
            base_x = canvas.winfo_rootx() - self.root.winfo_rootx()
            base_y = canvas.winfo_rooty() - self.root.winfo_rooty()
            backdrop = self.chrome_backdrop(base_x, base_y, width, height)
            if backdrop is None:
                return False
            width = backdrop.width
            height = backdrop.height
            over = 3
            layer = Image.new("RGBA", (width * over, height * over),
                              (0, 0, 0, 0))
            painter = ImageDraw.Draw(layer)

            def draw_pill(x0, x1, color):
                """上圆下平的药丸

                :param x0: 左
                :param x1: 右
                :param color: 填充色
                """
                top = 6 * over
                bottom = 34 * over
                radius = 8 * over
                left = x0 * over
                right = x1 * over - 1
                painter.rounded_rectangle(
                    [left, top, right, top + 2 * radius],
                    radius=radius, fill=color)
                painter.rectangle(
                    [left, top + radius, right, bottom], fill=color)

            hover = self._tab_hover
            if hover and hover != self.tab:
                hover_rect = rects.get(hover)
                if hover_rect:
                    draw_pill(hover_rect[0], hover_rect[1],
                              mix_color(self.blank_bg(), P.fg, 0.08))
            ratio = 0.28 if self._tab_hover == self.tab else 0.20
            active_color = mix_color(self.blank_bg(),
                                     self.tab_accent(self.tab), ratio)
            draw_pill(rect[0], rect[1], active_color)
            layer = layer.resize((width, height), Image.LANCZOS)
            image = Image.alpha_composite(backdrop.convert("RGBA"),
                                          layer).convert("RGB")
            painter = ImageDraw.Draw(image)

            def baseline_of(tk_font, bold):
                """把字在药丸高度上垂直居中时, 基线在哪

                :param tk_font: Tk 字体
                :param bold: 是否粗体
                """
                font = self.list_paint_kind_font("cn", tk_font, bold)
                if font is None:
                    return 26
                ascent, descent = font.getmetrics()
                return 20 + (ascent - descent) // 2

            baseline = baseline_of(self.f_tab, True)
            count_base = baseline_of(self.f_tab_count, False)
            for key, name in (("pending", "\u672a\u5b8c\u6210"),
                              ("done", "\u5df2\u5b8c\u6210")):
                item = rects.get(key)
                if not item:
                    continue
                name_fg, count_fg = self.tab_text_colors(key)
                self.list_paint_text(painter, item[2], baseline, name,
                                     self.f_tab, True, name_fg)
                self.list_paint_text(painter, item[3], count_base,
                                     str(self.tab_counts.get(key, 0)),
                                     self.f_tab_count, False, count_fg)
            photo = ImageTk.PhotoImage(image)
            self._tab_photo = photo
            canvas.delete("tabpaint")
            canvas.create_image(0, 0, anchor="nw", image=photo,
                                tags="tabpaint")
            canvas.tag_lower("tabpaint")
            return True
        except Exception as exc:
            print("tabs paint failed:", exc)
            return False

    def paint_tab_texts(self):
        """重画两个页签上的文字(名字 + 数量, 纯色主题走这条路)"""
        canvas = getattr(self, "tab_indicator", None)
        if canvas is None:
            return
        try:
            canvas.delete("tabtext")
            for key, name in (("pending", "\u672a\u5b8c\u6210"),
                              ("done", "\u5df2\u5b8c\u6210")):
                rect = self._tab_rects.get(key)
                if not rect:
                    continue
                name_fg, count_fg = self.tab_text_colors(key)
                canvas.create_text(rect[2], 20, text=name, anchor="w",
                                   font=self.f_tab, fill=name_fg,
                                   tags=("tabtext", key))
                canvas.create_text(rect[3], 20,
                                   text=str(self.tab_counts.get(key, 0)),
                                   anchor="w", font=self.f_tab_count,
                                   fill=count_fg, tags=("tabtext", key))
        except Exception:
            pass

    def redraw_tabs(self):
        """整块页签重画: 悬停底 + 药丸 + 文字, 切换时药丸滑过去"""
        canvas = getattr(self, "tab_indicator", None)
        if canvas is None:
            return
        previous = self._tab_pill
        previous_key = self._tab_pill_key
        self._tab_rects = self.tab_layout()
        target = self._tab_rects.get(self.tab)
        if target is None:
            return
        pill = (target[0], target[1])
        self._tab_pill = pill
        changed = previous_key is not None and previous_key != self.tab
        if not changed and getattr(self, "_tab_tween", None) is not None:
            self._tab_tween.stop()
            self._tab_tween = None
        self._tab_pill_key = self.tab
        try:
            canvas.delete("all")
        except Exception:
            return
        if self.paint_tabs_image(previous if changed and previous else pill):
            if changed and previous:
                self.slide_tabs_image(previous, pill)
            return
        self.paint_tab_hover()
        self.paint_tab_pill(previous if changed and previous else pill)
        self.paint_tab_texts()
        if changed and previous:
            self.slide_tab_pill(previous, pill)

    def slide_tabs_image(self, start, target):
        """自绘模式下药丸滑过去(每帧重画整条, 文字才不会跟药丸错开)

        :param start: 起点 (左, 右)
        :param target: 终点 (左, 右)
        """
        tween = getattr(self, "_tab_tween", None)
        if tween is not None:
            tween.stop()
        self._tab_tween = Tween(
            self.root, 0.18,
            on_frame=lambda p: self.paint_tabs_image((
                start[0] + (target[0] - start[0]) * p,
                start[1] + (target[1] - start[1]) * p)),
            on_done=lambda: setattr(self, "_tab_tween", None),
            easing=ease_in_out_cubic)
        self._tab_tween.start()

    def slide_tab_pill(self, start, target):
        """药丸从旧页签滑到新页签

        :param start: 起点 (左, 右)
        :param target: 终点 (左, 右)
        """
        tween = getattr(self, "_tab_tween", None)
        if tween is not None:
            tween.stop()
        self._tab_tween = Tween(
            self.root, 0.18,
            on_frame=lambda p: self.paint_tab_pill((
                start[0] + (target[0] - start[0]) * p,
                start[1] + (target[1] - start[1]) * p)),
            on_done=lambda: setattr(self, "_tab_tween", None),
            easing=ease_in_out_cubic)
        self._tab_tween.start()

    def tab_at(self, x):
        """鼠标 x 落在哪个页签上

        :param x: 画布坐标
        """
        for key, rect in self._tab_rects.items():
            if rect[0] <= x <= rect[1]:
                return key
        return None

    def on_tab_click(self, event):
        """点页签

        :param event: 鼠标事件
        """
        key = self.tab_at(event.x)
        if key is not None:
            self.set_tab(key)

    def on_tab_motion(self, event):
        """鼠标在页签区移动, 更新悬停状态

        :param event: 鼠标事件
        """
        self.set_tab_hover(self.tab_at(event.x))

    def set_tab_hover(self, key):
        """设置当前悬停的页签

        :param key: 页签名或 None
        """
        if key == self._tab_hover:
            return
        self._tab_hover = key
        if self.paint_tabs_image(self._tab_pill):
            return
        self.paint_tab_pill(self._tab_pill)
        self.paint_tab_hover()
        self.paint_tab_texts()

    def make_switch_button(self, symbol, step):
        """做一个清单切换箭头: 平时只有符号, 悬停时亮起来并浮出一圈圆底

        :param symbol: 显示的符号
        :param step: 1 下一个 / -1 上一个
        """
        size = 24
        canvas = tk.Canvas(self._tabbar, width=size, height=size, bg=P.bg,
                           bd=0, highlightthickness=0)
        # 图片皮肤是"抠色透明"的窗口, 没画东西的地方连鼠标事件都收不到。
        # 先铺一层几乎看不出的圆底, 让整块都能悬停/点击
        if self.skin_spec() is not None:
            base = mix_color(self.blank_bg(), P.fg, 0.035)
            canvas.create_oval(1, 1, size - 1, size - 1, fill=base,
                               outline="", tags="base")
        text = canvas.create_text(size // 2, size // 2, text=symbol,
                                  fill=P.fg_faint, font=self.f_switch)

        def enter(event):
            canvas.delete("halo")
            fill = mix_color(self.blank_bg(), P.fg, 0.24)
            ring = mix_color(self.blank_bg(), P.fg, 0.5)
            photo = self.switch_circle_photo(canvas, size, fill, ring)
            if photo is not None:
                canvas.create_image(0, 0, anchor="nw", image=photo,
                                    tags="halo")
                canvas.tag_lower("halo", text)
            else:
                canvas.create_oval(1, 1, size - 1, size - 1, fill=fill,
                                   outline=ring, width=1, tags="halo")
                canvas.tag_lower("halo", text)
            canvas.itemconfigure(text, fill=P.fg, font=self.f_switch_on)

        def leave(event):
            canvas.delete("halo")
            canvas.itemconfigure(text, fill=P.fg_faint, font=self.f_switch)

        canvas.bind("<Enter>", enter)
        canvas.bind("<Leave>", leave)
        canvas.bind("<Button-1>", lambda ev: self.cycle_list(step))
        return canvas

    def schedule_tab_retry(self):
        """底图还没准备好: 过一小会儿再重画页签, 换掉没抗锯齿的那版"""
        if getattr(self, "_tab_retry_job", None) is not None:
            return
        try:
            self._tab_retry_job = self.root.after(150, self.retry_tab_paint)
        except Exception:
            self._tab_retry_job = None

    def retry_tab_paint(self):
        """到点了, 重画页签"""
        self._tab_retry_job = None
        try:
            self.redraw_tabs()
        except Exception:
            pass

    def switch_circle_photo(self, canvas, size, fill, ring=None):
        """给箭头按钮画一颗抗锯齿圆, 位置按按钮现在在窗口里的地方算

        :param canvas: 按钮画布
        :param size: 边长
        :param fill: 填充色
        :param ring: 描边色
        """
        try:
            if not canvas.winfo_ismapped():
                return None
            base_x = canvas.winfo_rootx() - self.root.winfo_rootx()
            base_y = canvas.winfo_rooty() - self.root.winfo_rooty()
        except Exception:
            return None
        photo = self.circle_photo(size, base_x, base_y, fill, ring)
        if photo is not None:
            canvas._circle_photo = photo
        return photo

    def update_tabs(self, done, total):
        """刷新两个页签上的数量

        :param done: 已完成条数
        :param total: 总条数
        """
        try:
            self.tab_counts = {"pending": max(0, total - done), "done": done}
            self.redraw_tabs()
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
        # 圆点 padx(14, 2)、标题 padx(0, 8)、折叠按钮 padx(0, 4) 的留白
        width += 14 + 2 + 8 + 4 + 4
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
        folded_h = self.fold_bar_height() + 2 * self._frame_pad
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
            # 收起前先把内容整体藏掉: 先删再收, 中间就不会出现内容错乱的一帧
            self.stat_box.pack_forget()
            for widget in (self._track, self._tabbar, self._body,
                           self._foot, self._line):
                widget.pack_forget()
            self.root.update_idletasks()
            self.hide_list_content()
            target_w, target_h = self.folded_width(), folded_h
            self._folded_size = (target_w, target_h)
            # 收起成横条时没有页签行, 箭头也藏起来
            self.update_list_switch()
            # 下面的内容钉住不动, 跟着窗口边缘被裁掉
            if animate:
                self.freeze_content()
            animator = self.animate_collapse if animate else None
        else:
            self.restore_layout()
            self._folded_size = None
            self.update_list_switch()
            self.btn_fold.config(text="\u25b4")
            target_w, target_h = self._expanded_size or (330, 460)
            if animate:
                # 窗口马上要撑到最终大小, 显示区域得先按横条收住: 不然撑大
                # 的那一瞬还没裁, 整个大窗口会露出来一帧(皮肤还没跟上, 看着
                # 就是一块黑的)
                self.round_window(max(1, start_w), max(1, start_h),
                                  force=True)
            # 先撑到最终大小把内容排好; 无边框窗口再用显示区域把它"放"出来
            self.root.geometry("{}x{}".format(target_w, target_h))
            # 先把布局排好: 磨砂膜的矩形是按页签/列表的实际位置算的,
            # 没排好会算成 None(这一帧就没有膜, 看着像块纯色)
            self.root.update_idletasks()
            # 先只把皮肤窗口撑到目标大小, 区域留到下面按横条裁,
            # 不然这一瞬间皮肤会整个铺开闪一下
            self.sync_skin(target_w, target_h, clip=False)
            self.clip_skin(start_w, start_h)
            self.fit_width(target_w)
            # 展开不做"区域逐渐露出来"的动画: 窗口被裁小时周围会露出桌面/
            # 别的窗口, 看着就是一大块黑的; 直接显示整窗更干净
            animator = None

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
        h = self.fold_bar_height() if self.collapsed else 40
        fill = self.header_bg()
        # 复用同一个矩形, 别每帧删掉再画 —— 删掉的那一瞬间会闪一下
        if getattr(self, "_head_rect", None) is None:
            self._head_rect = canvas.create_rectangle(0, 0, w, h,
                                                      fill=fill, outline="")
            return
        canvas.coords(self._head_rect, 0, 0, w, h)
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
            head.place(x=0, y=0, width=inner_w,
                       height=self.fold_bar_height())
        steps = 6
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
                self._fold_job = self.root.after(10, tick)
                return
            self._fold_job = None
            self._animating = False
            done()
            # 刚设过 geometry, Tk 要过一轮事件才认新尺寸(这时 winfo_height
            # 还是旧值), 等 30ms 再让阴影按最终尺寸现身
            self.root.after(30, self.resume_main_shadow)

        self._animating = True
        # 阴影先退场: 跟着每帧缩放的影子会漏出一帧(大影子还留在原地),
        # 收完再按最终尺寸一次性摆好
        self.hide_main_shadow()
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
        steps = 6
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
                self._fold_job = self.root.after(10, tick)
                return
            self._fold_job = None
            self._animating = False
            done()
            # 刚设过 geometry, Tk 要过一轮事件才认新尺寸(这时 winfo_height
            # 还是旧值), 等 30ms 再让阴影按最终尺寸现身
            self.root.after(30, self.resume_main_shadow)

        self._animating = True
        self.hide_main_shadow()
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
        self.root.minsize(140, self.fold_bar_height()
                           + 2 * self._frame_pad)
        self.apply_resize_state()
        self.round_window(width, height)
        if width and height and not self._skin_layered:
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
        # 圆点 padx(14, 2)、标题 padx(0, 8)、折叠按钮 padx(0, 4) 的留白
        total += 14 + 2 + 8 + 4 + 4
        stat_width = self.stat_box.winfo_reqwidth() or 82
        return total + stat_width + 12

    def on_win_configure(self, e):
        if e.widget is not self.root:
            return
        if getattr(self, "_drag", None):
            # 拖窗口时只有位置在变, 大小/皮肤都由 apply_window_rect 逐帧处理了
            return
        # 排 z 序也会让 Windows 发 WM_WINDOWPOSCHANGED, Tk 一律当成 <Configure>。
        # 位置大小都没变就别再排同步, 否则会 "同步 → 排 z 序 → 又来事件" 死循环
        cfg = (e.width, e.height, e.x, e.y)
        if cfg == getattr(self, "_last_cfg", None):
            return
        self._last_cfg = cfg
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
        defaults = {"font_cn": "", "font_latin": "",
                    "scrim_mode": "frost", "radius": 0,
                    "border_mode": "none", "border_width": 2,
                    "border_color": "#3b7cf6", "border_color2": "#8a5cf6",
                    "bars_split": False, "bars_color": "#17181d",
                    "bars_color2": "#2b2e38", "bars_grad": False,
                    "bars_angle": "vertical",
                    "header_split": False, "header_color": "#17181d",
                    "footer_split": False, "footer_color": "#17181d"}
        custom = self.custom_theme()
        if custom is None:
            return defaults
        border = custom.get("border") or {}
        mode = border.get("mode")
        scrim = custom.get("scrim")
        # 顶栏/底栏共用一份; 老配色只存过 header_*/footer_*, 那样读出来
        if "bars_split" in custom:
            bars_split = bool(custom.get("bars_split"))
            bars_color = custom.get("bars_color") or "#17181d"
            bars_color2 = custom.get("bars_color2") or bars_color
            bars_grad = bool(custom.get("bars_grad"))
            bars_angle = custom.get("bars_angle") or "vertical"
        else:
            bars_split = bool(custom.get("header_split")
                              or custom.get("footer_split"))
            bars_color = custom.get("header_color") or "#17181d"
            bars_color2 = custom.get("footer_color") or bars_color
            bars_grad = False
            bars_angle = "vertical"
        return {
            "font_cn": custom.get("font_cn") or "",
            "font_latin": custom.get("font_latin") or "",
            "scrim_mode": scrim if scrim in ("frost", "solid", "off") else "frost",
            "border_mode": mode if mode in ("none", "solid", "gradient") else "none",
            "border_width": max(0, min(8, int(border.get("width") or 2))),
            "border_color": border.get("color") or "#3b7cf6",
            "border_color2": border.get("color2") or "#8a5cf6",
            "radius": max(0, min(14, int(custom.get("radius") or 0))),
            "bars_split": bars_split,
            "bars_color": bars_color,
            "bars_color2": bars_color2,
            "bars_grad": bars_grad,
            "bars_angle": bars_angle if bars_angle in ("vertical",
                                                       "horizontal",
                                                       "diagonal")
            else "vertical",
            "header_split": bars_split,
            "header_color": bars_color,
            "footer_split": bars_split,
            "footer_color": bars_color,
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
            self._skin_layered = False
            self._skin_surface = None
            self._skin_surface_image = None
            self._skin_mask_cache = {}
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

    def refresh_layered_surface(self, width=None, height=None):
        """按当前窗口大小重推一次分层图

        收起后皮肤图还是展开时那张(原来靠区域裁出横条), 换成 alpha 以后
        必须用裁过的图, 不然窗口里只剩左上角那个圆角。
        """
        if not self._skin_layered or self._skin_plain is None:
            return
        try:
            width = max(2, int(width or self.root.winfo_width()))
            height = max(2, int(height or self.root.winfo_height()))
            image = self._skin_plain
            if image.size != (width, height):
                image = image.crop((0, 0, min(width, image.width),
                                    min(height, image.height)))
            if self.border_active():
                # 边框要按新的一圈重画, 直接裁展开图会把右/下边裁掉
                image = self.apply_border(image, (0, 0, width, height))
            self.push_layered_skin(image)
        except Exception as exc:
            print("refresh layered failed:", exc)

    def drop_skin_regions(self):
        """分层窗口接管圆角以后, 把之前的 1 位窗口区域清掉

        区域是 1 位掩码, 留着它圆角边就还是台阶; alpha 已经画好边了,
        主窗口和皮肤窗口都可以变回方角。
        """
        if not self._skin_layered:
            return
        try:
            self._main_region_size = None
            self._skin_region_size = None
            self.round_window()
            self.clip_skin(self.root.winfo_width(), self.root.winfo_height())
        except Exception as exc:
            print("drop skin regions failed:", exc)

    def destroy_skin(self):
        """去掉皮肤窗口"""
        self._skin_layered = False
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

    def skin_click_is_double(self, event, target):
        """判这次按下是不是双击的第二下(皮肤窗口转发用)

        皮肤窗口收到的两次点击是两次独立的 <Button-1>, 靠 Tk 自己的双击判定
        不稳定, 这里按"同一控件 + 位置差不多 + 时间够近"自己判。

        :param event: 皮肤窗口上的按下事件
        :param target: 这次要转给哪个控件
        """
        now = time.time()
        last = getattr(self, "_skin_click", None)
        self._skin_click = (now, event.x_root, event.y_root, target)
        if last is None:
            return False
        if now - last[0] > 0.5:
            return False
        if last[3] is not target:
            return False
        if abs(event.x_root - last[1]) > 4:
            return False
        if abs(event.y_root - last[2]) > 4:
            return False
        # 判成双击就把记录清掉, 连点三下不会变成两次双击
        self._skin_click = None
        return True

    def dispatch_skin_double(self, target, x, y, event):
        """皮肤窗口判出双击后, 直接把双击动作跑掉

        Tk 不会把皮肤窗口里 event_generate 出去的两次按下算成双击
        (实测 <Double-1> 一次都不触发), 所以这里按控件直接调处理函数。

        :param target: 双击落在哪个控件
        :param x: 控件内横坐标
        :param y: 控件内纵坐标
        :param event: 皮肤窗口上的原始事件(取屏幕坐标用)
        """
        tree = getattr(self, "tree", None)
        if target is not None and target is tree:
            self.on_double_click(_SkinPoint(x, y))
            return
        for widget in (getattr(self, "_head", None),
                       getattr(self, "head_bg", None)):
            if widget is not None and target is widget:
                self.toggle_collapse_all()
                return
        # 其它控件没有专门的双击动作, 发个事件让它自己的绑定处理
        if target is not None:
            target.event_generate("<Double-Button-1>", x=x, y=y,
                                  rootx=event.x_root, rooty=event.y_root)

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
            doubled = False
            if sequence == "<Button-1>":
                doubled = self.skin_click_is_double(event, target)
            local_x = x - (target.winfo_rootx() - root.winfo_rootx())
            local_y = y - (target.winfo_rooty() - root.winfo_rooty())
            options = {"x": local_x, "y": local_y,
                       "rootx": event.x_root, "rooty": event.y_root}
            delta = getattr(event, "delta", 0)
            if delta:
                options["delta"] = delta
            target.event_generate(sequence, **options)
            if doubled:
                self.dispatch_skin_double(target, local_x, local_y, event)
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
            self._skin_base = image.copy()
            image = self.compose_skin(self._skin_base)
            self.skin_push_image(image)
            self._skin_size = (width, height)
        except Exception:
            pass

    def paint_bars(self, image):
        """把顶栏/底栏单独上的颜色画进底图

        这样外圈圆角能完全交给 alpha; 否则顶栏是实色的, 方角会戳出圆角,
        只能退回 1 位的窗口区域, 圆角又有台阶。

        :param image: 要画的图(RGB)
        """
        if not (self.header_split or self.footer_split):
            return image
        pad = self.border_pad()
        width, height = image.size
        if self.bars_grad:
            # 顶栏和底栏各贴一条同样的渐变带(颜色是同一份配置)
            band_w = max(1, width - 2 * pad)
            spec = {"grad_start": self.bars_color,
                    "grad_end": self.bars_color2,
                    "grad_angle": self.bars_angle}
            head_band = self.gradient_image(spec, band_w, 40)
            foot_band = self.gradient_image(spec, band_w, 32)
            image.paste(head_band, (pad, pad))
            image.paste(foot_band, (pad, max(pad, height - pad - 32)))
            return image
        from PIL import ImageDraw
        draw = ImageDraw.Draw(image)
        if self.header_split:
            draw.rectangle([pad, pad, width - 1 - pad, pad + 39],
                           fill=hex_to_rgb(self.header_color))
        if self.footer_split:
            draw.rectangle([pad, height - pad - 32, width - 1 - pad,
                            height - 1 - pad],
                           fill=hex_to_rgb(self.footer_color))
        return image

    def hide_list_content(self):
        """收起前把画在底图上的列表内容擦掉

        皮肤模式下列表文字是画进底图的, 收起动画又是一点点裁这张图;
        不擦的话文字会跟着窗口一路被裁到最后, 中间还会有错位的错乱感。
        直接用没画列表的 _skin_base 重新合一张干净的。
        """
        if self.skin_spec() is None or self._skin_base is None:
            return
        try:
            image = self._skin_base.copy()
            image = self.paint_bars(image)
            self._skin_plain = image.copy()
            if self.border_active():
                image = self.apply_border(image, None)
            self.skin_push_image(image)
            # 这张是擦过内容的, 记成「没正经裁过」, 展开时会重新合一张带列表的
            self._skin_size = None
        except Exception as exc:
            print("hide list content failed:", exc)

    def compose_skin(self, base):
        """由"底图 + 膜"合成最终皮肤图: 列表自绘 + 顶底栏 + 边框

        :param base: 已经处理好底图和膜的那张图(RGB)
        """
        image = base.copy()
        image = self.list_paint_draw(image)
        image = self.paint_bars(image)
        self._skin_plain = image.copy()
        rect = None
        if self.collapsed and self._folded_size:
            folded_w, folded_h = self._folded_size
            rect = (0, 0, folded_w, folded_h)
        return self.apply_border(image, rect)

    def skin_alpha_mask(self, width, height):
        """窗口圆角的 alpha 遮罩(3 倍超采样后缩回来)

        :param width: 宽
        :param height: 高
        """
        radius = max(2, int(self.corner_radius()))
        key = (int(width), int(height), radius)
        cached = self._skin_mask_cache.get(key)
        if cached is not None:
            return cached
        over = 3
        big = Image.new("L", (width * over, height * over), 0)
        ImageDraw.Draw(big).rounded_rectangle(
            [0, 0, width * over - 1, height * over - 1],
            radius=radius * over, fill=255)
        mask = big.resize((width, height), Image.LANCZOS)
        if len(self._skin_mask_cache) > 6:
            self._skin_mask_cache.clear()
        self._skin_mask_cache[key] = mask
        return mask

    def layered_bytes(self, image):
        """把图转成 UpdateLayeredWindow 要的 BGRA 字节(alpha 已预乘)

        :param image: 合成好的图(RGB)
        """
        width, height = image.size
        mask = self.skin_alpha_mask(width, height)
        rgba = image.convert("RGBA")
        rgba.putalpha(mask)
        red, green, blue, alpha = rgba.split()
        # 预乘: 分层窗口按 alpha 混合, RGB 要事先乘上 alpha
        red = ImageChops.multiply(red, alpha)
        green = ImageChops.multiply(green, alpha)
        blue = ImageChops.multiply(blue, alpha)
        return Image.merge("RGBA", (blue, green, red, alpha)).tobytes()

    def push_layered_skin(self, image):
        """把皮肤图按逐像素透明推到皮肤窗口上

        普通窗口只能靠 SetWindowRgn 切圆角, 而窗口区域是 1 位掩码, 圆弧
        一定是台阶; 换成 UpdateLayeredWindow 传带 alpha 的位图, 边才是
        抗锯齿的。失败就返回 False, 调用方退回贴图的老路。

        :param image: 已经合成好的图(RGB)
        """
        win = getattr(self, "skin_win", None)
        if win is None or Image is None:
            return False
        try:
            width, height = image.size
            data = self.layered_bytes(image)
        except Exception as exc:
            print("layered skin: image failed:", exc)
            return False
        try:
            user32, gdi32 = _layered_api()
            hwnd = user32.GetParent(win.winfo_id())
            if not hwnd:
                return False
            style = user32.GetWindowLongW(hwnd, -20)
            if not style & 0x00080000:  # WS_EX_LAYERED
                user32.SetWindowLongW(hwnd, -20, style | 0x00080000)
            screen = user32.GetDC(None)
            memory = gdi32.CreateCompatibleDC(screen)
            header = _BitmapHeader()
            header.biSize = ctypes.sizeof(_BitmapHeader)
            header.biWidth = width
            header.biHeight = -height
            header.biPlanes = 1
            header.biBitCount = 32
            info = _BitmapInfo()
            info.bmiHeader = header
            bits = ctypes.c_void_p()
            bitmap = gdi32.CreateDIBSection(memory, ctypes.byref(info), 0,
                                            ctypes.byref(bits), None, 0)
            if not bitmap:
                gdi32.DeleteDC(memory)
                user32.ReleaseDC(None, screen)
                return False
            ctypes.memmove(bits, data, len(data))
            old = gdi32.SelectObject(memory, bitmap)
            source = wintypes.POINT(0, 0)
            geom = self._skin_geom
            if geom:
                target = wintypes.POINT(int(geom[2]), int(geom[3]))
            else:
                target = wintypes.POINT(win.winfo_rootx(),
                                        win.winfo_rooty())
            size = wintypes.SIZE(width, height)
            blend = _BlendFunction(0, 0, 255, 1)  # AC_SRC_OVER / AC_SRC_ALPHA
            ok = user32.UpdateLayeredWindow(
                hwnd, screen, ctypes.byref(target), ctypes.byref(size),
                memory, ctypes.byref(source), 0, ctypes.byref(blend), 2)
            gdi32.SelectObject(memory, old)
            gdi32.DeleteObject(bitmap)
            gdi32.DeleteDC(memory)
            user32.ReleaseDC(None, screen)
            if not ok:
                return False
            self._skin_surface = (width, height)
            self._skin_surface_image = image
            if not self._skin_layered:
                self._skin_layered = True
                # 之前设过 1 位的圆角区域, 会让边还是台阶, 等这一轮忙完清掉
                self.root.after_idle(self.drop_skin_regions)
            return True
        except Exception as exc:
            print("layered skin failed:", exc)
            return False

    def skin_push_image(self, image):
        """把合成好的图贴到皮肤窗口上

        :param image: 要显示的图(PIL RGB)
        """
        try:
            photo = ImageTk.PhotoImage(image)
            self.skin_label.configure(image=photo)
            self.skin_photo = photo
            self._skin_image = image
        except Exception:
            pass
        self.push_layered_skin(image)
        # 底图换了, 页签是自绘的, 得跟着重画(不然字和底对不上)
        self.root.after_idle(self.redraw_tabs)

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
            self.push_layered_skin(sized)
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

    def fold_bar_height(self):
        """收起后横条的高度(不含边框留白)"""
        try:
            return max(28, min(80, int(self.conf.get("folded_height") or 42)))
        except Exception:
            return 42

    def choose_folded_height(self, value):
        """设置收起后横条的高度(34 小 / 42 标准 / 52 大)"""
        value = max(28, min(80, int(value)))
        if value == self.fold_bar_height():
            return
        self.conf["folded_height"] = value
        try:
            self.save_conf()
        except Exception:
            pass
        if self.collapsed:
            pad = self._frame_pad
            self._folded_size = (self.folded_width(), value + 2 * pad)
            try:
                self.root.minsize(140, value + 2 * pad)
                self.root.geometry("{}x{}".format(*self._folded_size))
            except Exception:
                pass
        try:
            self.restyle_group("foldh", value)
        except Exception:
            pass

    def corner_radius(self):
        """窗口圆角半径

        边框只是在圆角里再画一圈, 不再让圆角跟着边框粗细缩 —— 以前 3px
        的边框会把圆角压成 3px, 看着几乎成了直角。没指定就固定 10px。
        """
        custom = int(getattr(self, "radius", 0) or 0)
        if custom > 0:
            return max(2, min(14, custom))
        return 10

    def border_active(self):
        """是不是要画边框"""
        return self.border_mode in ("solid", "gradient") and self.border_width > 0

    def bar_color_at(self, x, y, width, height):
        """顶栏/底栏在某一格的颜色(渐变就按方向插值)

        :param x: 这一格中心的横坐标(相对栏目)
        :param y: 纵坐标
        :param width: 栏目宽
        :param height: 栏目高
        """
        if not self.bars_grad:
            return self.bars_color
        if self.bars_angle == "horizontal":
            ratio = x / float(max(1, width))
        elif self.bars_angle == "diagonal":
            ratio = (x + y) / float(max(1, width + height))
        else:
            ratio = y / float(max(1, height))
        return mix_color(self.bars_color, self.bars_color2,
                         max(0.0, min(1.0, ratio)))

    def bar_fg_colors(self):
        """顶栏/底栏上的文字色

        栏单独上色以后, 原来的文字色是按列表底色配的: 浅色栏上压白字
        会看不清(看着像空心)。这里按栏的颜色重算一套。
        """
        if not self.bars_split:
            return None
        # 渐变时按中点的颜色判断, 不然"浅→深"的栏上会挑出黑字压在深色那头
        back = self.bars_color
        if self.bars_grad:
            back = mix_color(self.bars_color, self.bars_color2, 0.5)
        # 用户自己配的文字色只要看得清就用他的; 实在糊在一起才自动换黑白
        base = str(P.fg)
        if abs(brightness(base) - brightness(back)) < 90:
            base = best_text_color(back)
        return {"fg": base,
                "dim": mix_color(base, back, 0.25),
                "faint": mix_color(base, back, 0.45)}

    def retint_bars(self):
        """把顶栏/底栏里的文字按栏的颜色重新上色"""
        colors = self.bar_fg_colors()
        if colors is None:
            return
        table = {str(P.fg).lower(): colors["fg"],
                 str(P.fg_dim).lower(): colors["dim"],
                 str(P.fg_faint).lower(): colors["faint"],
                 "#ffffff": colors["fg"]}

        def walk(widget, top, depth=0):
            if depth > 3:
                return
            try:
                current = str(widget.cget("fg")).lower()
            except Exception:
                current = ""
            if current in table:
                try:
                    widget.configure(fg=table[current])
                except Exception:
                    pass
            for child in widget.winfo_children():
                walk(child, top, depth + 1)

        for top in (getattr(self, "_head", None),
                    getattr(self, "_foot", None)):
            if top is not None:
                walk(top, top)

    def watch_bar_tint(self):
        """盯住顶栏/底栏的 hover、点击、重新映射, 事后补一次上色

        这些回调自己会用主题色重设 fg/bg(P.fg、P.head 之类), 一次性上色
        会被覆盖掉, 表现就是"颜色有时候不对"。
        """
        def again(event=None):
            self.root.after_idle(self.retint_bars)

        def walk(widget, depth=0):
            if depth > 3:
                return
            for seq in ("<Enter>", "<Leave>", "<ButtonRelease-1>", "<Map>"):
                try:
                    widget.bind(seq, again, add="+")
                except Exception:
                    pass
            for child in widget.winfo_children():
                walk(child, depth + 1)

        for top in (getattr(self, "_head", None),
                    getattr(self, "_foot", None)):
            if top is not None:
                walk(top)

    def bars_on_skin(self):
        """顶栏/底栏用渐变时只能画在皮肤底图上(纯色帧画不出渐变)"""
        return bool(self.bars_split and self.bars_grad)

    def render_spec(self):
        """画底图用的规格

        皮肤主题用它自己的; 纯色主题只开了边框时, 也给皮肤窗口一块纯色底,
        边框才有地方画。
        """
        spec = self.skin_spec()
        if spec is not None:
            return spec
        if self.border_active() or self.bars_on_skin():
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
        # 圆角半径跟边框粗细有关, 缓存作废才能按新半径重设区域
        self._main_region_size = None
        self._skin_region_size = None
        if self.collapsed:
            # 收起横条宽度是按顶栏内容算的, 留白变了要重新量一次
            folded_h = self.fold_bar_height() + 2 * pad
            try:
                self._folded_size = (self.folded_width(), folded_h)
                self.root.minsize(140, folded_h)
                self.root.geometry("{}x{}".format(*self._folded_size))
            except Exception:
                pass
        color = P.bg
        if self.render_spec() is not None:
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
            radius = max(2, int(round(self.corner_radius() * (scale or 1))))
            inner_radius = max(1, radius - thickness)
            # 超采样几倍再缩回来, 弧线才有抗锯齿
            over = 3

            def mask(inset, rad):
                """圆角遮罩: inset 往里缩多少, rad 圆角半径

                :param inset: 往里缩的像素
                :param rad: 圆角半径
                """
                big = Image.new("L", (width * over, height * over), 0)
                draw = ImageDraw.Draw(big)
                x0 = inset * over
                draw.rounded_rectangle(
                    [x0, x0, width * over - 1 - x0, height * over - 1 - x0],
                    radius=max(0, rad) * over, fill=255)
                return big.resize((width, height), Image.LANCZOS)

            # 外沿跟窗口区域同一个圆角, 内沿收一个粗细 —— 整圈等宽
            ring = ImageChops.subtract(mask(0, radius), mask(thickness, inner_radius))
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
            if self._skin_layered and self.push_layered_skin(image):
                return
            photo = ImageTk.PhotoImage(image)
            self.skin_label.configure(image=photo)
            self.skin_photo = photo
        except Exception:
            pass

    def header_bg(self):
        """顶栏底色: 皮肤模式下透明(颜色画在底图上), 纯色主题用顶栏色"""
        if self.skin_spec() is not None:
            return self.blank_bg()
        if self.bars_on_skin() and self.render_spec() is not None:
            # 渐变栏画在皮肤底图上, 这里要透明才看得见
            return self.skin_key()
        if self.bars_split:
            return self.bars_color
        return P.head

    def footer_bg(self):
        """底栏底色: 皮肤模式下透明(颜色画在底图上)"""
        if self.skin_spec() is not None:
            return self.blank_bg()
        if self.bars_on_skin() and self.render_spec() is not None:
            return self.skin_key()
        if self.bars_split:
            return self.bars_color
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

    def widget_offset(self, widget, root=None):
        """控件在窗口里的坐标, 还没映射时也算得出来

        展开的那一刻控件刚 pack 回来, 事件循环还没跑到, winfo_ismapped()
        还是 0、winfo_rooty() 也不可靠; 但几何管理器算出来的 winfo_x/y
        已经是准的, 一层层加起来就行。

        :param widget: 控件
        :param root: 顶层窗口, 不传就用主窗口
        """
        root = root or self.root
        x = 0
        y = 0
        node = widget
        while node is not None and node is not root:
            try:
                x += node.winfo_x()
                y += node.winfo_y()
            except Exception:
                return None
            node = node.master
        return x, y

    def skin_scrim_rect(self):
        """列表(页签 + 列表区)在窗口里的矩形, 拿不到就返回 None"""
        if self.collapsed:
            return None
        tabbar = getattr(self, "_tabbar", None)
        body = getattr(self, "_body", None)
        if tabbar is None or body is None:
            return None
        try:
            # 收起过程中这两块是 place 的, 那时不需要膜; 只认 pack 的时候
            if tabbar.winfo_manager() != "pack" or body.winfo_manager() != "pack":
                return None
            tab_pos = self.widget_offset(tabbar)
            body_pos = self.widget_offset(body)
            if tab_pos is None or body_pos is None:
                return None
            # 左右顶到窗口边(不再跟着列表的 padx 留缝), 上下按页签/列表算
            left = 0
            right = self.root.winfo_width()
            top = tab_pos[1]
            bottom = body_pos[1] + body.winfo_height()
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
        # 上沿是页签底下的直线, 不要圆角(圆了会在两边露出底图)
        draw.rectangle([0, 0, width * scale - 1, height * scale // 2], fill=255)
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
        if self._resizing or getattr(self, "_drag", None):
            # 拖动/改大小的时候位置是逐帧同步的, 这里再补一次纯属多干活,
            # 而且会让皮肤窗口反复重排/重画(看着一直闪)
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
        if not instant and (getattr(self, "_drag", None) or self._resizing):
            # 拖动/改大小期间位置由 apply_window_rect 逐帧处理; 皮肤窗口自己
            # 的 <Configure> 再进来重铺一遍底图, 整窗就会一黑一白地闪
            return
        if self._animating:
            # 折叠/展开动画每帧自己裁区域, 别让窗口事件用整窗大小盖回去(会闪出一帧大窗口)
            return
        if instant:
            # 拖动: 只把两个窗口一起挪过去。置顶、裁图、重推分层表面全都别做,
            # 位置变了不需要重绘内容, 做了反而整窗一黑一白地闪
            try:
                r = self.root
                w = int(width or r.winfo_width())
                h = int(height or r.winfo_height())
                if self.collapsed and self._folded_size:
                    w, h = self._folded_size
                if x is None:
                    x = r.winfo_rootx()
                if y is None:
                    y = r.winfo_rooty()
                self.apply_window_rect(max(2, w), max(2, h), int(x), int(y))
            except Exception:
                pass
            return
        root = self.root
        try:
            if root.state() in ("withdrawn", "iconic"):
                win.withdraw()
                return
            if win.state() != "normal":
                # 主窗口藏起来过又显示出来时, 皮肤窗口也要跟着回来
                win.deiconify()
                # 重新显示出来的窗口可能把分层样式丢了, 补推一次
                self.refresh_layered_surface()
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
            if clip:
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
            # 刚建出来时窗口还没显示, 拿不到顶层包装窗口, 分层推送会失败;
            # 这里等它就位了再补一次。收起 / 展开切换后窗口大小变了,
            # 推出去的图层也得跟着换, 不然会露出上一张图的残片
            if self._skin_image is not None:
                if not self._skin_layered:
                    self.push_layered_skin(self._skin_image)
                elif self._skin_surface != size:
                    self.refresh_layered_surface(size[0], size[1])
            self.sync_main_shadow(size[0], size[1], int(x), int(y))
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
            skin = self.skin_hwnd()
            # 两个窗口放进同一个"窗口位置事务"里一起提交:
            # 分两次 SetWindowPos 时, 中间那一帧会出现"主窗口已经挪走、
            # 皮肤还没跟上"的空洞, 看着就是闪
            batch = user32.BeginDeferWindowPos(2)
            if batch:
                batch = user32.DeferWindowPos(batch, main, 0, x, y,
                                              width, height,
                                              no_zorder | no_activate)
                if skin:
                    if user32.GetWindow(skin, 3) == main:
                        after = 0
                        flags = no_zorder | no_activate
                    else:
                        after = main
                        flags = no_activate
                    batch = user32.DeferWindowPos(batch, skin, after, x, y,
                                                  width, height, flags)
                user32.EndDeferWindowPos(batch)
                if skin:
                    self._skin_geom = (width, height, x, y)
            else:
                user32.SetWindowPos(main, 0, x, y, width, height,
                                    no_zorder | no_activate)
                if skin:
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

    def redraw_windows(self):
        """强制把两个窗口重画一遍(拖完窗口补一次)"""
        try:
            user32 = ctypes.windll.user32
            flags = 0x0001 | 0x0080 | 0x0100   # INVALIDATE | ALLCHILDREN | UPDATENOW
            for hwnd in (self.main_hwnd(), self.skin_hwnd()):
                if hwnd:
                    user32.RedrawWindow(hwnd, None, None, flags)
        except Exception:
            pass

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
        # 皮肤排好之后把阴影再压到皮肤下面(不然它会夹在中间蒙住背景)
        shadow = getattr(self, "_main_shadow", None)
        if shadow is not None:
            shadow.restack()

    def clip_skin(self, width, height):
        """把皮肤窗口的显示区域裁到指定大小(动画每帧用)

        :param width: 可见宽度
        :param height: 可见高度
        """
        size = (max(2, int(width)), max(2, int(height)))
        actual = (self.root.winfo_width(), self.root.winfo_height())
        if self._skin_layered and not self._animating and actual == size:
            # 窗口已经缩到位了: 圆角交给 alpha, 把区域清掉(只清一次)
            if self._skin_region_size != "alpha":
                if self.skin_round(width, height):
                    self._skin_region_size = "alpha"
            return
        if self._skin_region_size == size:
            return
        if self.skin_round(width, height):
            self._skin_region_size = size

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
            actual = (self.root.winfo_width(), self.root.winfo_height())
            if (self._skin_layered and not self._animating
                    and actual == (w, h)):
                # 圆角已经在 alpha 里了, 再切区域反而把抗锯齿的边切掉。
                # 但窗口还没缩到位时不能清, 否则会露出整张展开图
                user32.SetWindowRgn(wrapper, None, True)
                return True
            radius = self.corner_radius() * 2
            rgn = gdi32.CreateRoundRectRgn(0, 0, w + 1, h + 1, radius, radius)
            user32.SetWindowRgn(wrapper, rgn, True)
            return True
        except Exception:
            return False

    def round_window(self, width=None, height=None, force=False):
        """无边框 + 圆角, 看着像个小组件

        动画过程中传当前帧的尺寸进来, 免得 winfo_width 还是上一帧的旧值。

        :param width: 这一帧的宽, 不传就按窗口当前的
        :param height: 这一帧的高
        :param force: True 时不管是不是 alpha 模式, 都切一个区域出来
        """
        if self._animating and width is None and height is None:
            # 展开动画里窗口已经是最终大小了, 这时按窗口尺寸设区域会把
            # 整个大窗口放出来(闪一帧); 每帧的调用会自己传尺寸
            return
        try:
            w = max(2, int(width or self.root.winfo_width()))
            h = max(2, int(height or self.root.winfo_height()))
            size = (w, h)
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            if not hwnd:
                return
            if self._animating:
                self.sync_main_shadow(w, h)
            actual = (self.root.winfo_width(), self.root.winfo_height())
            if (not force and self._skin_layered and not self._animating
                    and actual == size):
                # 外圈圆角交给下面那层皮肤窗口的 alpha, 主窗口保持方角。
                # 尺寸还没到位时同样不能清, 不然会闪一帧方窗
                if self._main_region_size != "alpha":
                    if ctypes.windll.user32.SetWindowRgn(hwnd, None, True):
                        self._main_region_size = "alpha"
                return
            # 大小没变就别再设一遍区域, 每次 SetWindowRgn 都会让窗口重画
            if self._main_region_size == size:
                return
            radius = self.corner_radius() * 2
            # 纯色主题: 区域往里缩 1px, 外面那圈交给同色卡片的抗锯齿圆角
            inset = 0
            shadow = getattr(self, "_main_shadow", None)
            if shadow is not None and shadow.card:
                inset = 1
            rgn = ctypes.windll.gdi32.CreateRoundRectRgn(
                inset, inset, max(inset + 1, w - inset),
                max(inset + 1, h - inset), radius, radius)
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

    def popup_menu(self, menu, x, y):
        """弹一个菜单; 弹的时候把皮肤窗口的置顶让出来, 否则菜单会被压住

        :param menu: 已经建好的 tk.Menu
        :param x: 屏幕横坐标
        :param y: 屏幕纵坐标
        """
        self._menu_open = True
        try:
            menu.tk_popup(x, y)
        finally:
            self._menu_open = False
            self.root.after_idle(self.restack_skin)
            # 恢复 -topmost 时皮肤窗口可能被抬到主窗口上面, 底图就把顶栏/
            # 底栏的文字盖住了(看着像文字变透明), 过一会儿再摆一次
            self.root.after(150, self.restore_after_menu)

    def restore_after_menu(self):
        """菜单关掉后把层级摆回去: 主窗口在上, 皮肤窗口在下"""
        try:
            self.root.lift()
        except Exception:
            pass
        try:
            self.place_skin_below()
        except Exception:
            pass

    def popup_header(self, e):
        m = tk.Menu(self.root, tearoff=0)
        m.add_command(label="设置…", command=self.open_settings)
        m.add_separator()
        m.add_command(label="清单管理…", command=self.open_list_manager)
        m.add_command(label="隐藏", command=self.hide)
        m.add_separator()
        m.add_checkbutton(label="总在最前", command=self.toggle_topmost,
                          variable=tk.BooleanVar(value=self.topmost))
        m.add_checkbutton(label="锁定窗口大小", command=self.toggle_resize_lock,
                          variable=tk.BooleanVar(value=self.resize_locked))
        m.add_command(label="退出", command=self.quit)
        self.popup_menu(m, e.x_root, e.y_root)

    def cancel_drag_move(self):
        """松手: 取消还没执行的搬窗口任务, 并把最后位置补上"""
        if self._drag_job is not None:
            try:
                self.root.after_cancel(self._drag_job)
            except Exception:
                pass
            self._drag_job = None
        target = getattr(self, "_drag_target", None)
        if target:
            x, y = target
            if self.skin_win is None:
                self.root.geometry("+{}+{}".format(int(x), int(y)))
            else:
                self.sync_skin(x=x, y=y, instant=True)

    def apply_drag_move(self):
        """按帧搬窗口: 同一帧里的多个 motion 只搬最后一次"""
        target = getattr(self, "_drag_target", None)
        if not target or not getattr(self, "_drag", None):
            return
        if self._drag_job is not None:
            return
        self._drag_job = self.root.after(12, self.run_drag_move)

    def run_drag_move(self):
        """定时器到点: 把窗口挪到最新的目标位置"""
        self._drag_job = None
        target = getattr(self, "_drag_target", None)
        if not target or not getattr(self, "_drag", None):
            return
        x, y = target
        if self.skin_win is None:
            self.root.geometry("+{}+{}".format(int(x), int(y)))
            return
        self.sync_skin(x=x, y=y, instant=True)

    def reset_position(self):
        """把窗口夹回当前屏幕(换过显示器之后手边能救一下)"""
        geom = "{}x{}+{}+{}".format(self.root.winfo_width(),
                                    self.root.winfo_height(),
                                    self.root.winfo_x(), self.root.winfo_y())
        fixed = screens.fit_geom(geom) or geom
        parsed = screens.parse_geom(fixed)
        if not parsed:
            return
        width, height, x, y = parsed
        if self.collapsed and self._folded_size:
            width, height = self._folded_size
        self.root.geometry("{}x{}+{}+{}".format(width, height, x, y))
        self.sync_skin(x=x, y=y)
        self.round_window()
        self.save_geom()

    def shadow_anchor(self):
        """阴影应该压在哪个窗口下面

        有皮肤窗口时要压到皮肤下面: 皮肤才是整个窗口的底图, 阴影夹在主窗口
        和皮肤之间就会蒙在背景上(看着像阴影浮在上面), 拖动时还会一闪一闪。
        """
        return self.skin_hwnd() or self.main_hwnd()

    def make_main_shadow(self):
        """给主窗口建一个跟着走的阴影"""
        try:
            from .shadow import WindowShadow
        except Exception as exc:
            print("shadow import failed:", exc)
            return None
        shadow = getattr(self, "_main_shadow", None)
        if shadow is None:
            # 纯色主题没有皮肤窗口垫底, 用同色卡片把被 1 位区域切掉的圆角
            # 补成抗锯齿边; 皮肤主题已经有 alpha 圆角, 不需要卡片
            card = None
            if self.render_spec() is None:
                card = P.bg
            shadow = WindowShadow(self.root, radius=self.corner_radius(),
                                  blur=8, strength=0.5, card=card,
                                  anchor=self.shadow_anchor)
            shadow.create()
            shadow.follow(self.root)
            self._main_shadow = shadow
        else:
            shadow.radius = self.corner_radius()
            card = P.bg if self.render_spec() is None else None
            if card != shadow.card:
                shadow.card = card
                shadow._image_size = None
        return shadow

    def begin_reveal(self):
        """显示时先只露圆角背景: 把内容摘下来, 过一会儿再贴上去

        顺序是 背景 → 内容 → 阴影, 换配色/启动时就不会糊成一团。
        """
        try:
            self.inner.pack_forget()
        except Exception:
            pass

    def reveal_content(self):
        """把内容贴回来(这时圆角背景已经在屏幕上了)"""
        try:
            pad = self.border_pad()
            self.inner.pack(fill="both", expand=True, padx=pad, pady=pad)
        except Exception:
            pass

    def resume_main_shadow(self):
        """收起/展开动画收尾: 几何生效之后让阴影按最终尺寸现身"""
        if self._animating:
            # 又折叠/展开了一次, 交给下一轮收尾
            return
        shadow = getattr(self, "_main_shadow", None)
        if shadow is None or not getattr(shadow, "suspended", False):
            return
        try:
            if self.root.state() != "normal":
                # 窗口这会儿藏着, 别把阴影单独显示出来
                shadow.suspended = False
                return
        except Exception:
            pass
        shadow.resume()

    def hide_main_shadow(self):
        """收起/展开动画开始时先让阴影退场

        用 suspend(): 动画每帧窗口都会来 <Configure>, 光 hide() 的话
        阴影的自动跟随会把它又显示出来(看起来就是先收起了才消失)。
        """
        shadow = getattr(self, "_main_shadow", None)
        if shadow is not None:
            shadow.suspend()

    def sync_main_shadow(self, width=None, height=None, x=None, y=None):
        """主窗口的阴影跟着几何走

        :param width: 可见宽, 不传按窗口的
        :param height: 可见高
        :param x: 屏幕横坐标
        :param y: 屏幕纵坐标
        """
        if self._animating:
            # 收起/展开动画期间阴影已经退场, 别每帧又把它摆回来(会漏影子)
            return
        shadow = getattr(self, "_main_shadow", None)
        if shadow is None:
            return
        if getattr(shadow, "suspended", False):
            # 动画还没收尾 / 新尺寸还没生效: 先别现身,
            # 由 resume_main_shadow() 在几何生效后统一处理
            return
        shadow.sync(width, height, x, y)

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
        geom = self.pick_geom()
        if geom:
            r.geometry(geom)
        else:
            sw, sh = r.winfo_screenwidth(), r.winfo_screenheight()
            r.geometry("330x460+{}+{}".format(sw - 370, max(70, sh // 10)))
        # 先只露圆角背景, 内容 45ms 后再贴上来
        self.begin_reveal()
        r.deiconify()
        r.lift()
        self.make_main_shadow()
        # 阴影最后一个出现: 先挂起, 等皮肤/内容都摆好了再显示
        self.hide_main_shadow()
        self.apply_resize_state()
        # 栏上的文字就用用户配的文字色, 不再自动改色(自动改色踩过好几次坑)
        try:
            from . import titletrace
            titletrace.start(self)
        except Exception:
            pass
        if skin is not None:
            self.make_skin()
        else:
            self.destroy_skin()
        if not self.topmost:
            r.after(150, self.sink)
        r.after(45, self.reveal_content)
        r.after(60, self.round_window)
        r.after(80, self.sync_skin)
        # 底图摆好之后再让阴影现身(换配色时最明显: 不会先看到一个空影子)
        r.after(90, self.resume_main_shadow)
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
        # 阴影最先消失: 先把影子收掉, 再藏窗口
        self.hide_main_shadow()
        self.root.withdraw()
        self.sync_skin()

    def show(self):
        self.begin_reveal()
        self.root.deiconify()
        self.root.lift()
        self.sync_skin()
        # 阴影最后出现: 先挂起, 等窗口画好再显示
        self.hide_main_shadow()
        self.root.after(45, self.reveal_content)
        self.root.after(75, self.resume_main_shadow)
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
            pystray.MenuItem(self.tray_toggle_label,
                             lambda: self.call(self.toggle_window),
                             default=True),
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

    def window_hidden(self):
        """窗口现在是藏起来的吗(托盘菜单文案用)"""
        try:
            return self.root.state() == "withdrawn"
        except Exception:
            return False

    def tray_toggle_label(self, item=None):
        """托盘菜单里"显示/隐藏"这一项的文案

        :param item: pystray 传进来的菜单项, 用不到
        """
        return "显示窗口" if self.window_hidden() else "隐藏窗口"

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
        shadow = getattr(self, "_main_shadow", None)
        self._main_shadow = None
        if shadow is not None:
            shadow.destroy()
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
