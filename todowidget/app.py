# -*- coding: utf-8 -*-
"""主窗口外壳: 布局、页签、折叠、窗口形态、托盘"""

import ctypes
import json
import threading
import time

import tkinter as tk
from tkinter import ttk

try:
    import pystray
except Exception:
    pystray = None

from .paths import CONF_FILE
from .store import Store
from .theme import P, hex_to_rgb, pick_font, set_theme
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
        self.tab = self.conf.get("tab", "pending")
        self.sort_mode = self.conf.get("sort_mode", "manual")
        self.theme = self.conf.get("theme", "dark")
        self.accent = self.conf.get("accent") or None
        self.settings_win = None
        self.notes = {}
        self.note_by_widget = {}
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
        self.root.after(300, self.reopen_pinned_notes)

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

        # 勾选框用小图片画, 比字符清楚, 也方便只点框勾选
        self.img_on = self.make_box(True)
        self.img_off = self.make_box(False)

        # ---- 顶栏 ----
        head = tk.Frame(inner, bg=P.head, height=40)
        head.pack(fill="x", side="top")
        head.pack_propagate(False)
        self._head = head

        self.lbl_title = tk.Label(head, text="待办", bg=P.head, fg=P.fg,
                                  font=self.f_title, cursor="hand2")
        self.lbl_title.pack(side="left", padx=(14, 8))
        self.lbl_stat = tk.Label(head, text="", bg=P.head, fg=P.fg_dim,
                                 font=self.f_small)
        self.lbl_stat.pack(side="left", pady=(3, 0))

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
        track = tk.Frame(inner, bg=P.border, height=2)
        track.pack(fill="x", side="top")
        track.pack_propagate(False)
        self._track = track
        self.pbar = tk.Frame(track, bg=P.accent, height=2)
        self.pbar.place(x=0, y=0, relheight=1, relwidth=0)

        # ---- 未完成 / 已完成 两个页签 ----
        tabbar = tk.Frame(inner, bg=P.bg, height=34)
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
        body = tk.Frame(inner, bg=P.bg)
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
        for w in (r, inner, body, self.tree):
            w.bind("<Button-1>", self.grab_focus, add="+")

        # ---- 底栏 ----
        foot = tk.Frame(inner, bg=P.bg, height=32)
        foot.pack(fill="x", side="bottom")
        foot.pack_propagate(False)
        self._foot = foot
        line = tk.Frame(inner, bg=P.border, height=1)
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
        self.tip = tk.Label(foot, text=tip_text, bg=P.bg,
                            fg=P.fg_faint, font=self.f_small)
        self.tip.pack(side="right", padx=(4, 2))

        gear = tk.Label(foot, text="\u2699", bg=P.bg, fg=P.fg_faint,
                        font=self.f_item, cursor="hand2", width=2)
        gear.pack(side="right", padx=(0, 6))
        gear.bind("<Button-1>", lambda e: self.open_settings())
        gear.bind("<Enter>", lambda e, w=gear: w.configure(fg=P.fg))
        gear.bind("<Leave>", lambda e, w=gear: w.configure(fg=P.fg_faint))

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
                fg=P.fg if self.tab == "pending" else P.fg_dim)
            self.tab_labels["done"].config(
                text="已完成 {}".format(done),
                fg=P.fg if self.tab == "done" else P.fg_dim)
            self.tab_bars["pending"].config(
                bg=P.accent if self.tab == "pending" else P.bg)
            self.tab_bars["done"].config(
                bg=P.accent if self.tab == "done" else P.bg)
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
        m.add_command(label="显示 / 隐藏", command=self.hide)
        m.add_separator()
        m.add_checkbutton(label="总在最前", command=self.toggle_topmost,
                          variable=tk.BooleanVar(value=self.topmost))
        m.add_command(label="退出", command=self.quit)
        m.tk_popup(e.x_root, e.y_root)

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
