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
from .theme import (P, apply_palette, custom_scheme, hex_to_rgb, mix_color,
                    pick_font, set_theme)
from .utils import HAS_TRAY, make_icon, place_window

if HAS_TRAY:
    from PIL import Image, ImageChops, ImageDraw, ImageTk
from .ui_list import ListViewMixin
from .ui_lists import ListMenuMixin
from .ui_note import NoteMixin
from .ui_settings import SettingsMixin


class TodoApp(ListViewMixin, ListMenuMixin, NoteMixin, SettingsMixin):
    """主窗口(按功能拆在几个 Mixin 里)"""

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
        self.resize_locked = bool(self.conf.get("resize_locked", False))
        self._resize_from = None
        self._resizing = False
        self._resize_job = None
        self._resize_target = None
        self.skin_win = None
        self.skin_label = None
        self.skin_photo = None
        self._skin_size = None
        self._skin_region_size = None
        self._skin_crop_job = None
        self._skin_source = None
        self._skin_source_path = None
        self._fold_job = None
        self._animating = False
        self._frozen = []
        self._title_job = None
        self._title_target = None
        self.tab = self.conf.get("tab", "pending")
        self.sort_mode = self.conf.get("sort_mode", "manual")
        self._day_open = {}
        self._days_collapsed = False
        self.theme = self.conf.get("theme", "dark")
        self.accent = self.conf.get("accent") or None
        self.custom_themes = self.conf.get("themes") or []
        self.show_stat = bool(self.conf.get("show_stat", True))
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
        self.conf.update(mode=self.mode, topmost=self.topmost, alpha=self.alpha,
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
        if custom is not None:
            bg = custom.get("bg") or "#17181d"
            if (custom.get("mode") or "") == "gradient":
                bg = mix_color(custom.get("grad_start") or bg,
                               custom.get("grad_end") or bg, 0.5)
            apply_palette(custom_scheme(bg, custom.get("accent") or "#5b9cff"))
            self._theme_image = custom.get("image") or ""
        else:
            set_theme(self.theme, self.accent)
        self.bg_image = self.bg_image_path()

    def build_ui(self):
        self.apply_palette_choice()
        self.stop_title_fade()
        self._frozen = []
        # 重建界面时旧的皮肤窗口已经被销毁, 这里把引用清掉
        self.skin_win = None
        self.skin_label = None
        self.skin_photo = None
        self._skin_size = None
        self._skin_region_size = None
        self._skin_crop_job = None
        r = self.root
        is_desktop = self.mode == "desktop"
        r.title("待办清单")
        r.configure(bg=P.border)
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
        inner = tk.Frame(r, bg=P.bg)
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        self.inner = inner
        self._frame_pad = 0
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
            r.geometry("+{}+{}".format(target_x, target_y))
            self.sync_skin(x=target_x, y=target_y)

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
        style.configure("Todo.Vertical.TScrollbar", background=P.border,
                        troughcolor=P.bg, bordercolor=P.bg, arrowcolor=P.fg_dim,
                        darkcolor=P.border, lightcolor=P.border,
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

        # Treeview 的 tag 优先级跟定义顺序有关, 混着用会串色,
        # 所以每行的状态只用一个 tag, 悬停/拖放都是独立的一套
        base_cfg = {
            "group": dict(font=self.f_group, foreground=P.group,
                          background=P.group_bg),
            "group_done": dict(font=self.f_group_done, foreground=P.done,
                               background=P.group_bg),
            "item": dict(font=self.f_item, foreground=P.fg),
            "item_done": dict(font=self.f_item_done, foreground=P.done),
        }
        for name, cfg in base_cfg.items():
            self.tree.tag_configure(name, **cfg)
            hover = dict(cfg, background=P.hover)
            self.tree.tag_configure(name + "_h", **hover)
            drop = dict(cfg, background="#4a3f22")
            self.tree.tag_configure("drop_" + name, **drop)
        self.tree.tag_configure("empty", font=self.f_item, foreground=P.fg_faint)
        self.tree.tag_configure("sep", font=self.f_small, foreground=P.fg_dim)
        self.tree.tag_configure("day", font=self.f_small, foreground=P.fg_dim)

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

        r.bind("<FocusOut>", self.on_focus_out)
        r.bind("<Button-1>", self.on_any_click, add="+")
        r.bind("<Configure>", self.on_win_configure, add="+")
        r.bind("<Control-q>", lambda e: self.quit())
        self.set_window_icon()
        self.apply_resize_state()
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
        if self._title_job is not None:
            # 正在淡出淡入, 让它到中间换字时再取最新文字
            self._title_target = text
            return
        self._title_target = None
        self.lbl_title.config(text=text, fg=P.fg)

    def stop_title_fade(self):
        """停掉还没跑完的标题淡化, 颜色恢复成正常"""
        if self._title_job is not None:
            try:
                self.root.after_cancel(self._title_job)
            except Exception:
                pass
            self._title_job = None
        self._title_target = None
        try:
            self.lbl_title.config(fg=P.fg)
        except Exception:
            pass

    def fade_title(self):
        """标题先淡出, 换成当前该显示的文字, 再淡回来"""
        text, cursor = self.title_text()
        self.lbl_title.config(cursor=cursor)
        self.stop_title_fade()
        head = hex_to_rgb(P.head)
        fg = hex_to_rgb(P.fg)
        steps = 5
        state = {"phase": "out", "step": 0}

        def color(ratio):
            parts = []
            for i in range(3):
                parts.append(int(round(fg[i] + (head[i] - fg[i]) * ratio)))
            return "#{:02x}{:02x}{:02x}".format(*parts)

        def tick():
            state["step"] += 1
            ratio = state["step"] / float(steps)
            if state["phase"] == "out":
                self.lbl_title.config(fg=color(ratio))
                if state["step"] >= steps:
                    state["phase"] = "in"
                    state["step"] = 0
                    self.lbl_title.config(text=self._title_target or text)
            else:
                self.lbl_title.config(fg=color(1.0 - ratio))
                if state["step"] >= steps:
                    self._title_job = None
                    self._title_target = None
                    self.lbl_title.config(fg=P.fg)
                    return
            self._title_job = self.root.after(16, tick)

        self._title_target = text
        tick()

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
            self.tab_bars["pending"].config(
                bg=pending_color if self.tab == "pending" else P.bg)
            self.tab_bars["done"].config(
                bg=done_color if self.tab == "done" else P.bg)
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
        # 外侧 1px 描边 + 图片主题时卡片四周的留白
        width += 2 + 2 * getattr(self, "_frame_pad", 0)
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
        if animate and self.mode == "desktop":
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
            # 下面的内容钉住不动, 跟着窗口边缘被裁掉
            if animate:
                self.freeze_content()
            use_anim = animate and self.mode == "desktop"
            animator = self.animate_collapse if use_anim else None
        else:
            self.restore_layout()
            self.btn_fold.config(text="\u25b4")
            target_w, target_h = self._expanded_size or (330, 460)
            # 先撑到最终大小把内容排好; 无边框窗口再用显示区域把它"放"出来
            self.root.geometry("{}x{}".format(target_w, target_h))
            self.sync_skin(target_w, target_h)
            self.clip_skin(start_w, start_h)
            self.fit_width(target_w)
            use_anim = animate and self.mode == "desktop"
            animator = self.animate_reveal if use_anim else None

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
        w = width or canvas.winfo_width()
        canvas.delete("all")
        canvas.create_rectangle(0, 0, max(1, w), 40, fill=P.head, outline="")

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
        inner_w = max(1, start_w - 2 - 2 * self._frame_pad)
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
                width=max(1, width - 2 - 2 * self._frame_pad))
            # 先把顶栏排好、重画底色, 再把显示区域收上来:
            # 不然区域比顶栏窄一帧会切掉右边的按钮, 按钮移动还会留残影
            head.update_idletasks()
            self.paint_head_bg(max(1, width - 2 - 2 * self._frame_pad))
            self.round_window(width, height)
            self.clip_skin(width, height)
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
        self.root.geometry("{}x{}".format(target[0], target[1]))
        self.sync_skin(target[0], target[1])
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
            self.root.geometry("{}x{}".format(target[0], target[1]))
        self._resize_target = None
        self._resize_from = None
        self._resizing = False
        self.round_window()
        self.refresh_skin_crop()
        self.save_geom()

    def toggle_resize_lock(self):
        """右键顶栏 / 托盘: 锁住或解开自由调节宽高"""
        self.set_resize_locked(not self.resize_locked)

    def set_resize_locked(self, locked):
        """锁住后右下角斜纹收起, 普通窗口模式也不能拖系统边框"""
        locked = bool(locked)
        if locked == self.resize_locked:
            return
        self.resize_locked = locked
        self.save_conf()
        self.apply_resize_state()

    def apply_resize_state(self):
        """按锁定 / 折叠 / 窗口模式 决定要不要显示右下角调节柄"""
        locked = bool(getattr(self, "resize_locked", False))
        # 无边框窗口本来就没系统边框可拖, 不去动 resizable:
        # 在 Windows 上改这个会重刷一遍窗口, 主界面闪一下还会丢圆角
        if self.mode == "window":
            try:
                self.root.resizable(not locked, not locked)
            except Exception:
                pass
        grip = getattr(self, "grip", None)
        if grip is None:
            return
        show = (self.mode == "desktop" and not locked and not self.collapsed)
        shown = bool(grip.winfo_manager())
        if show and not shown:
            anchor = getattr(self, "_gear", grip)
            grip.pack(side="right", padx=(0, 5), pady=(0, 3), anchor="s",
                      before=anchor)
        elif not show and shown:
            grip.pack_forget()

    def fit_width(self, width):
        """窗口拖窄时先收起次要文字, 别把折叠、齿轮这些要紧的挤掉"""
        avail = width - 2 - 2 * getattr(self, "_frame_pad", 0)
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
        # 挪窗口/改大小都用事件里的坐标立刻同步, 不然图片会慢半拍
        if self.skin_win is not None:
            self.sync_skin(e.width, e.height, e.x, e.y)
        if getattr(self, "_win_size", None) == (e.width, e.height):
            return
        self._win_size = (e.width, e.height)
        self.fit_width(e.width)
        if self.skin_win is not None:
            self.schedule_skin_crop()
        # 动画每帧自己更新圆角区域, 拖动改大小时也别每帧重切, 不然更闪
        if not self._animating and not self._resizing:
            self.root.after(15, self.round_window)

    # ---------------- 图片皮肤 ----------------

    def skin_spec(self):
        """当前是不是图片/渐变皮肤; 是的话返回那份自定义配色"""
        if not HAS_TRAY:
            return None
        custom = self.custom_theme()
        if custom is None:
            return None
        mode = custom.get("mode") or ("image" if custom.get("image") else "solid")
        if mode == "gradient":
            return custom
        if mode == "image" and custom.get("image") and self.bg_image_path():
            return custom
        return None

    def skin_hwnd(self):
        """皮肤窗口的原生句柄"""
        win = self.skin_win
        if win is None:
            return 0
        user32 = ctypes.windll.user32
        return user32.GetParent(win.winfo_id()) or win.winfo_id()

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
        path = self.bg_image_path()
        if not path:
            return None
        return self.crop_skin_image(path, width, height, spec)

    def make_skin(self):
        """建一块只显示皮肤的窗口, 垫在主窗口下面"""
        if self.skin_spec() is None:
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
            self.skin_click_through()
        self.reload_skin_image()
        try:
            self.skin_win.deiconify()
        except Exception:
            pass
        self.sync_skin()

    def destroy_skin(self):
        """去掉皮肤窗口"""
        if self._skin_crop_job is not None:
            try:
                self.root.after_cancel(self._skin_crop_job)
            except Exception:
                pass
            self._skin_crop_job = None
        win = self.skin_win
        self.skin_win = None
        self.skin_label = None
        self.skin_photo = None
        self._skin_size = None
        self._skin_region_size = None
        if win is not None:
            try:
                win.destroy()
            except Exception:
                pass

    def skin_click_through(self):
        """皮肤窗口只负责显示, 不接收点击、不抢焦点、不进 Alt+Tab"""
        try:
            user32 = ctypes.windll.user32
            hwnd = self.skin_hwnd()
            gwl_exstyle = -20
            style = user32.GetWindowLongPtrW(hwnd, gwl_exstyle)
            style |= 0x00000020      # WS_EX_TRANSPARENT
            style |= 0x08000000      # WS_EX_NOACTIVATE
            style |= 0x00000080      # WS_EX_TOOLWINDOW
            user32.SetWindowLongPtrW(hwnd, gwl_exstyle, style)
        except Exception:
            pass

    def reload_skin_image(self):
        """按窗口大小把皮肤底图弄好"""
        win = self.skin_win
        spec = self.skin_spec()
        if win is None or spec is None:
            return
        width = max(40, self.root.winfo_width())
        height = max(40, self.root.winfo_height())
        if self.collapsed and self._expanded_size:
            width, height = self._expanded_size
            width = max(40, width)
            height = max(40, height)
        if self._skin_size == (width, height) and self.skin_photo is not None:
            return
        try:
            image = self.skin_base_image(spec, width, height)
            if image is None:
                return
            photo = ImageTk.PhotoImage(image)
            self.skin_label.configure(image=photo)
            self.skin_photo = photo
            self._skin_size = (width, height)
        except Exception:
            pass

    def refresh_skin_crop(self):
        """窗口大小定下来以后重裁一次皮肤底图"""
        if self.skin_win is None or self._animating or self.collapsed:
            return
        width = max(40, self.root.winfo_width())
        height = max(40, self.root.winfo_height())
        if self._skin_size == (width, height):
            return
        self.reload_skin_image()
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

    def sync_skin(self, width=None, height=None, x=None, y=None):
        """让皮肤窗口跟着主窗口的位置/大小, 并压在主窗口下面

        :param width: 可见宽度(动画时传当前帧的值)
        :param height: 可见高度
        :param x: 主窗口左上角屏幕坐标, 不传就现取
        :param y: 同上
        """
        win = self.skin_win
        if win is None:
            return
        root = self.root
        try:
            if root.state() == "withdrawn":
                win.withdraw()
                return
            width = int(width or root.winfo_width())
            height = int(height or root.winfo_height())
            size = (max(2, width), max(2, height))
            # 区域要先裁、位置要后挪: 反过来的话 SetWindowRgn 会把刚挪好的位置作废
            if self._skin_region_size != size:
                self.clip_skin(width, height)
            if x is None:
                x = root.winfo_rootx()
            if y is None:
                y = root.winfo_rooty()
            win.geometry("{}x{}+{}+{}".format(size[0], size[1], int(x), int(y)))
            self.place_skin_below()
        except Exception:
            pass

    def place_skin_below(self):
        """把皮肤窗口排到主窗口正下方"""
        try:
            user32 = ctypes.windll.user32
            flags = 0x0001 | 0x0002 | 0x0010  # NOSIZE | NOMOVE | NOACTIVATE
            user32.SetWindowPos(self.skin_hwnd(), self.main_hwnd(),
                                0, 0, 0, 0, flags)
        except Exception:
            pass

    def clip_skin(self, width, height):
        """把皮肤窗口的显示区域裁到指定大小(动画每帧用)

        :param width: 可见宽度
        :param height: 可见高度
        """
        self.skin_round(width, height)
        self._skin_region_size = (max(2, int(width)), max(2, int(height)))

    def skin_round(self, width, height):
        """皮肤窗口也切圆角, 免得从主窗口四角露出来"""
        try:
            gdi32 = ctypes.windll.gdi32
            user32 = ctypes.windll.user32
            w = max(2, int(width))
            h = max(2, int(height))
            rgn = gdi32.CreateRoundRectRgn(0, 0, w + 1, h + 1, 20, 20)
            user32.SetWindowRgn(self.skin_hwnd(), rgn, True)
        except Exception:
            pass

    def round_window(self, width=None, height=None):
        """无边框 + 圆角, 看着像个小组件

        动画过程中传当前帧的尺寸进来, 免得 winfo_width 还是上一帧的旧值。
        """
        if self.mode != "desktop":
            return
        try:
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            w = max(2, int(width or self.root.winfo_width()))
            h = max(2, int(height or self.root.winfo_height()))
            rgn = ctypes.windll.gdi32.CreateRoundRectRgn(0, 0, w + 1, h + 1, 20, 20)
            ctypes.windll.user32.SetWindowRgn(hwnd, rgn, True)
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
        r.overrideredirect(self.mode == "desktop")
        skin = self.skin_spec()
        alpha = float(self.alpha)
        if skin is not None:
            # 图片皮肤: 主窗口半透明, 让后面的图透出来
            strength = float(skin.get("alpha") or 0.2)
            strength = max(0.05, min(0.45, strength))
            alpha = alpha * (1.0 - strength)
        try:
            r.attributes("-topmost", bool(self.topmost))
            r.attributes("-alpha", alpha)
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
        if self.mode == "desktop" and not self.topmost:
            r.after(150, self.sink)
        r.after(60, self.round_window)
        r.after(80, self.sync_skin)
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
        self.place_skin_below()
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
        if self.mode != "desktop":
            return
        self.root.after(250, self.maybe_sink)

    def maybe_sink(self):
        if self.mode != "desktop" or self.topmost or self._dragging:
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
        if self._tray is None:  # 没有托盘就别真藏起来, 最小化到任务栏
            self.set_mode("window")
            self.root.iconify()
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
            pystray.MenuItem("贴到桌面（占桌面, 不占任务栏）",
                             lambda: self.call(self.set_mode, "desktop"),
                             checked=lambda i: self.mode == "desktop", radio=True),
            pystray.MenuItem("普通窗口（占任务栏）",
                             lambda: self.call(self.set_mode, "window"),
                             checked=lambda i: self.mode == "window", radio=True),
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
