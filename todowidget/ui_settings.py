# -*- coding: utf-8 -*-
"""设置窗口: 左边分类、右边选项, 外加检查更新"""

import ctypes
import os
import queue
import shutil
import threading
import tkinter as tk
import uuid
from tkinter import colorchooser, filedialog, messagebox, ttk

try:
    from PIL import Image, ImageTk
except Exception:
    Image = None
    ImageTk = None

from . import updater
from .paths import APP_DIR
from .theme import (P, GRADIENTS, THEMES, THEME_NAMES, auto_text_color,
                    best_text_color, mix_color, set_theme)
from .utils import make_icon, round_corners

# 设置窗口里各分类
SETTINGS_TABS = (("look", "外观"), ("sort", "排序"),
                 ("window", "窗口"), ("about", "关于与更新"))


class SettingsMixin:
    """设置窗口(按功能拆成几块面板)"""

    # ---------------- 窗口骨架 ----------------

    def open_settings(self, pos=None):
        """打开设置窗口; 已经开着就抬起来

        :param pos: 窗口位置, 不传就摆到主窗口中间
        """
        if self.settings_win is not None:
            try:
                self.settings_win.deiconify()
                self.settings_win.lift()
                return
            except Exception:
                self.settings_win = None

        win = tk.Toplevel(self.root)
        win.withdraw()
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg=P.border)
        self.settings_win = win
        self._settings_chips = {}
        self._settings_panels = {}
        self._settings_tab_buttons = {}
        self._update_busy = False
        self._update_queue = queue.Queue()

        body = tk.Frame(win, bg=P.bg)
        body.pack(fill="both", expand=True, padx=1, pady=1)

        self.build_settings_head(body)

        content = tk.Frame(body, bg=P.bg)
        content.pack(fill="both", expand=True)
        side = tk.Frame(content, bg=P.bg_alt, width=116)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        # 内容多了可以滚, 配色一多一屏放不下
        scroll = tk.Canvas(content, bg=P.bg, highlightthickness=0, bd=0)
        bar = ttk.Scrollbar(content, orient="vertical",
                            command=scroll.yview,
                            style="Todo.Vertical.TScrollbar")
        bar.pack(side="right", fill="y")
        scroll.pack(side="left", fill="both", expand=True)
        scroll.configure(yscrollcommand=bar.set)
        self._settings_scroll = scroll
        holder = tk.Frame(scroll, bg=P.bg)
        self._settings_holder = holder
        holder_id = scroll.create_window((0, 0), window=holder, anchor="nw")
        holder.bind("<Configure>",
                    lambda ev: scroll.configure(scrollregion=scroll.bbox("all")))
        scroll.bind("<Configure>",
                    lambda ev: scroll.itemconfigure(holder_id, width=ev.width))
        win.bind("<MouseWheel>", self.scroll_settings)

        for key, label in SETTINGS_TABS:
            self.make_settings_tab(side, key, label)

        builder = {"look": self.build_look_panel,
                   "sort": self.build_sort_panel,
                   "window": self.build_window_panel,
                   "about": self.build_about_panel}
        for key, _label in SETTINGS_TABS:
            panel = tk.Frame(holder, bg=P.bg)
            builder[key](panel)
            self._settings_panels[key] = panel

        current = getattr(self, "settings_tab", "look")
        if current not in self._settings_panels:
            current = "look"
        self.show_settings_tab(current)

        width, height = 560, 500
        if pos is None:
            # 直接摆到主窗口那块屏幕的正中间
            x, y = self.screen_center(width, height)
        else:
            x, y = pos
        left, top, right, bottom = self.settings_bounds()
        x = max(left + 8, min(x, right - width - 8))
        y = max(top + 8, min(y, bottom - height - 8))
        win.geometry("{}x{}+{}+{}".format(width, height, x, y))

        win.bind("<Escape>", lambda ev: self.close_settings())
        win.deiconify()
        win.after(30, lambda w=win: round_corners(w, 12))
        win.lift()
        win.focus_force()
        # 模态: 设置关掉之前, 点主界面不会起作用
        try:
            win.grab_set()
        except Exception:
            pass

    def build_settings_head(self, body):
        """窗口顶栏: 标题 + 关闭按钮, 按住可以挪窗口"""
        head = tk.Frame(body, bg=P.head, height=46)
        head.pack(fill="x")
        head.pack_propagate(False)
        tk.Label(head, text="设置", bg=P.head, fg=P.fg,
                 font=self.f_title).pack(side="left", padx=16)
        close = tk.Label(head, text="\u2715", bg=P.head, fg=P.fg_dim,
                         font=self.f_item, width=2, cursor="hand2")
        close.pack(side="right", padx=(0, 10))
        close.bind("<Button-1>", lambda ev: self.close_settings())
        close.bind("<Enter>", lambda ev, w=close: w.configure(fg=P.fg))
        close.bind("<Leave>", lambda ev, w=close: w.configure(fg=P.fg_dim))

        drag = {}

        def start_move(ev):
            drag["dx"] = ev.x_root - self.settings_win.winfo_x()
            drag["dy"] = ev.y_root - self.settings_win.winfo_y()

        def do_move(ev):
            if "dx" not in drag:
                return
            self.settings_win.geometry("+{}+{}".format(
                ev.x_root - drag["dx"], ev.y_root - drag["dy"]))

        for widget in (head,):
            widget.bind("<Button-1>", start_move)
            widget.bind("<B1-Motion>", do_move)

    def settings_bounds(self):
        """整个虚拟桌面的范围, 多显示器时也对"""
        try:
            user32 = ctypes.windll.user32
            left = user32.GetSystemMetrics(76)
            top = user32.GetSystemMetrics(77)
            width = user32.GetSystemMetrics(78)
            height = user32.GetSystemMetrics(79)
            if width and height:
                return left, top, left + width, top + height
        except Exception:
            pass
        return 0, 0, self.root.winfo_screenwidth(), self.root.winfo_screenheight()

    def close_settings(self):
        """关掉设置窗口, 顺便把模态抓取放开"""
        self.close_theme_editor()
        win = self.settings_win
        self.settings_win = None
        if win is not None:
            try:
                win.grab_release()
            except Exception:
                pass
            try:
                win.destroy()
            except Exception:
                pass

    def settings_pos(self):
        """设置窗口当前的位置, 重新打开时接着用"""
        win = self.settings_win
        if win is None:
            return None
        try:
            return (win.winfo_x(), win.winfo_y())
        except Exception:
            return None

    # ---------------- 左侧分类 ----------------

    def make_settings_tab(self, parent, key, label):
        """左边的一个分类按钮"""
        cell = tk.Frame(parent, bg=P.bg_alt, cursor="hand2")
        cell.pack(fill="x")
        bar = tk.Frame(cell, bg=P.bg_alt, width=3)
        bar.pack(side="left", fill="y")
        text = tk.Label(cell, text=label, bg=P.bg_alt, fg=P.fg_dim,
                        font=self.f_item, anchor="w", padx=14, pady=9,
                        cursor="hand2")
        text.pack(side="left", fill="x", expand=True)
        for widget in (cell, text):
            widget.bind("<Button-1>", lambda ev, k=key: self.show_settings_tab(k))
        self._settings_tab_buttons[key] = (cell, bar, text)

    def show_settings_tab(self, key):
        """切到某个分类"""
        self.settings_tab = key
        for panel_key, panel in self._settings_panels.items():
            if panel_key == key:
                panel.pack(fill="both", expand=True, padx=22, pady=18)
            else:
                panel.pack_forget()
        for tab_key, (cell, bar, text) in self._settings_tab_buttons.items():
            chosen = (tab_key == key)
            cell.configure(bg=P.bg if chosen else P.bg_alt)
            text.configure(bg=P.bg if chosen else P.bg_alt,
                           fg=P.fg if chosen else P.fg_dim)
            bar.configure(bg=P.accent if chosen else P.bg_alt)
        try:
            self._settings_scroll.yview_moveto(0)
        except Exception:
            pass

    def scroll_settings(self, event):
        """鼠标滚轮滚动设置内容"""
        try:
            step = int(-event.delta / 120) * 3
            self._settings_scroll.yview_scroll(step, "units")
        except Exception:
            pass

    # ---------------- 通用小部件 ----------------

    def settings_block(self, parent, title, desc=None):
        """分区标题 + 说明, 返回下面放控件的容器"""
        block = tk.Frame(parent, bg=P.bg)
        block.pack(fill="x", pady=(0, 20))
        tk.Label(block, text=title, bg=P.bg, fg=P.fg,
                 font=self.f_group).pack(anchor="w")
        if desc:
            tk.Label(block, text=desc, bg=P.bg, fg=P.fg_dim, font=self.f_small,
                     justify="left", wraplength=380).pack(anchor="w", pady=(3, 0))
        holder = tk.Frame(block, bg=P.bg)
        holder.pack(fill="x", pady=(9, 0))
        return holder

    def settings_chip(self, parent, label, chosen, command,
                      group=None, value=None):
        """一个选项按钮; 传 group/value 后可以原地切换选中态

        :param parent: 放按钮的容器
        :param label: 按钮文字
        :param chosen: 现在是不是选中的
        :param command: 点击后执行
        :param group: 同一组按钮的名字
        :param value: 这个按钮代表的值
        """
        bg = P.accent if chosen else P.bg_alt
        fg = best_text_color(P.accent) if chosen else P.fg_dim
        chip = tk.Label(parent, text=label, bg=bg, fg=fg, font=self.f_small,
                        padx=14, pady=6, cursor="hand2")
        chip.pack(side="left", padx=(0, 8))
        chip._chosen = chosen
        chip.bind("<Button-1>", lambda ev: command())
        chip.bind("<Enter>", lambda ev, w=chip: self.hover_chip(w, True))
        chip.bind("<Leave>", lambda ev, w=chip: self.hover_chip(w, False))
        if group is not None:
            self._settings_chips.setdefault(group, []).append((chip, value))
        return chip

    def hover_chip(self, chip, entering):
        """选项按钮的悬停效果"""
        chosen = bool(getattr(chip, "_chosen", False))
        if entering and not chosen:
            chip.configure(bg=P.hover)
            return
        chip.configure(bg=P.accent if chosen else P.bg_alt,
                       fg=best_text_color(P.accent) if chosen else P.fg_dim)

    def restyle_group(self, group, value):
        """把某一组选项的选中态换成 value"""
        for chip, chip_value in self._settings_chips.get(group, []):
            chosen = (chip_value == value)
            chip._chosen = chosen
            chip.configure(bg=P.accent if chosen else P.bg_alt,
                           fg=best_text_color(P.accent) if chosen else P.fg_dim)

    def settings_note(self, parent, text):
        """一行灰色小字说明"""
        label = tk.Label(parent, text=text, bg=P.bg, fg=P.fg_faint,
                         font=self.f_small, justify="left", wraplength=380,
                         anchor="w")
        label.pack(fill="x", pady=(6, 0))
        return label

    # ---------------- 外观 ----------------

    def build_look_panel(self, panel):
        """配色 / 自定义配色 / 强调色 / 质感 / 统计"""
        holder = self.settings_block(
            panel, "配色",
            "点色块直接换；自定义配色可以右键编辑或删除")
        grid = tk.Frame(holder, bg=P.bg)
        grid.pack(fill="x")
        items = list(THEME_NAMES)
        for theme in self.custom_themes:
            items.append(("custom:" + str(theme.get("id")), theme.get("name") or "自定义"))
        row = None
        for index, (key, label) in enumerate(items):
            if index % 4 == 0:
                row = tk.Frame(grid, bg=P.bg)
                row.pack(fill="x", pady=(0, 6))
            custom = self.custom_theme(key)
            if custom is not None:
                self.make_custom_theme_chip(row, custom)
            else:
                self.make_theme_chip(row, key, label)

        add_row = tk.Frame(holder, bg=P.bg)
        add_row.pack(fill="x", pady=(6, 0))
        add = tk.Label(add_row, text="\uff0b 自定义配色…", bg=P.bg_alt,
                       fg=P.fg_dim, font=self.f_small, padx=12, pady=5,
                       cursor="hand2")
        add.pack(side="left")
        add.bind("<Button-1>", lambda ev: self.open_theme_editor())
        add.bind("<Enter>", lambda ev, w=add: w.configure(bg=P.hover))
        add.bind("<Leave>", lambda ev, w=add: w.configure(bg=P.bg_alt))

        holder = self.settings_block(
            panel, "渐变配色", "点一下换，右键可以复制成自己的配色")
        grid = tk.Frame(holder, bg=P.bg)
        grid.pack(fill="x")
        row = None
        for index, key in enumerate(GRADIENTS):
            if index % 4 == 0:
                row = tk.Frame(grid, bg=P.bg)
                row.pack(fill="x", pady=(0, 6))
            self.make_gradient_chip(row, key, GRADIENTS[key])

        holder = self.settings_block(panel, "强调色",
                                     "勾选框、进度条、选中项会跟着变")
        row = tk.Frame(holder, bg=P.bg, cursor="hand2")
        row.pack(side="left")
        swatch = tk.Frame(row, bg=P.accent, width=36, height=22,
                          highlightthickness=1, highlightbackground=P.border)
        swatch.pack(side="left")
        swatch.pack_propagate(False)
        tk.Label(row, text="自定义…", bg=P.bg, fg=P.fg_dim,
                 font=self.f_small).pack(side="left", padx=10)
        for widget in (row, swatch):
            widget.bind("<Button-1>", lambda ev: self.pick_accent())

        holder = self.settings_block(panel, "统计", "顶栏显示还剩多少条没做")
        self.settings_chip(holder, "显示", self.show_stat,
                           lambda: self.choose_show_stat(True),
                           group="stat", value=True)
        self.settings_chip(holder, "隐藏", not self.show_stat,
                           lambda: self.choose_show_stat(False),
                           group="stat", value=False)

    THEME_CELL_WIDTH = 78
    THEME_CELL_HEIGHT = 50

    def theme_cell(self, parent):
        """配色格子的固定大小, 保证横竖对齐"""
        cell = tk.Frame(parent, bg=P.bg, cursor="hand2",
                        width=self.THEME_CELL_WIDTH,
                        height=self.THEME_CELL_HEIGHT)
        cell.pack(side="left", padx=(0, 10))
        cell.pack_propagate(False)
        return cell

    def theme_swatch(self, cell, bg, accent, chosen):
        """格子里的色块: 底色 + 中间一小块强调色

        强调色那一小块也要绑点击, 不然点正中间没反应。
        """
        border = P.fg if chosen else P.border
        swatch = tk.Frame(cell, bg=bg, width=38, height=24,
                          highlightthickness=2 if chosen else 1,
                          highlightbackground=border)
        swatch.place(relx=0.5, y=0, anchor="n")
        dot = tk.Frame(swatch, bg=accent, width=12, height=12)
        dot.place(x=13, y=6)
        return swatch, dot

    def theme_name(self, cell, text, chosen, limit=9):
        """格子下面的名字; 太长的名字截一下"""
        if len(text) > limit:
            text = text[:limit - 1] + "\u2026"
        name = tk.Label(cell, text=text, bg=P.bg,
                        fg=P.fg if chosen else P.fg_dim, font=self.f_small)
        name.place(x=0, y=29, relwidth=1)
        return name

    def make_theme_chip(self, parent, key, label):
        """内置配色的格子"""
        theme = THEMES[key]
        chosen = (key == self.theme)
        cell = self.theme_cell(parent)
        swatch, dot = self.theme_swatch(cell, theme["bg"], theme["accent"],
                                        chosen)
        name = self.theme_name(cell, label, chosen)
        for widget in (cell, swatch, dot, name):
            widget.bind("<Button-1>", lambda ev, k=key: self.choose_theme(k))
            widget.bind("<Button-3>",
                        lambda ev, k=key: self.popup_builtin_theme(ev, "solid", k))

    def make_gradient_chip(self, parent, key, spec):
        """内置渐变配色的格子"""
        full_key = "gradient:" + key
        chosen = (self.theme == full_key)
        cell = self.theme_cell(parent)
        canvas = tk.Canvas(cell, width=38, height=24, bd=0,
                           bg=spec["start"], highlightthickness=2 if chosen else 1,
                           highlightbackground=P.fg if chosen else P.border)
        canvas.place(relx=0.5, y=0, anchor="n")
        start, end = spec["start"], spec["end"]
        angle = spec.get("angle") or "vertical"
        if angle == "horizontal":
            for x in range(38):
                color = mix_color(start, end, x / 37.0)
                canvas.create_line(x, 0, x, 24, fill=color)
        elif angle == "diagonal":
            for offset in range(-24, 62):
                color = mix_color(start, end, (offset + 24) / 86.0)
                canvas.create_line(offset, 0, offset + 24, 24, fill=color)
        else:
            for y in range(24):
                color = mix_color(start, end, y / 23.0)
                canvas.create_line(0, y, 38, y, fill=color)
        name = self.theme_name(cell, spec.get("name") or key, chosen)
        for widget in (cell, canvas, name):
            widget.bind("<Button-1>",
                        lambda ev, k=full_key: self.choose_theme(k))
            widget.bind("<Button-3>",
                        lambda ev, k=key: self.popup_builtin_theme(ev, "gradient", k))

    def popup_builtin_theme(self, event, kind, key):
        """右键内置配色: 只能复制, 不能删"""
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="复制为自定义配色…",
                         command=lambda: self.copy_theme(kind, key))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def copy_theme(self, kind, key):
        """把内置配色复制一份出来做自定义

        :param kind: 'solid' 或 'gradient'
        :param key: 配色键
        """
        base = {"image": "", "zoom": 1.0, "offset": [0.0, 0.0],
                "grad_angle": "vertical", "alpha": 0.0}
        if kind == "gradient":
            spec = GRADIENTS[key]
            seed = dict(base)
            seed.update(name=spec["name"] + " 副本", mode="gradient",
                        bg=mix_color(spec["start"], spec["end"], 0.5),
                        accent=spec["accent"], fg=spec["fg"],
                        grad_start=spec["start"], grad_end=spec["end"],
                        grad_angle=spec.get("angle") or "vertical")
        else:
            scheme = THEMES[key]
            label = dict(THEME_NAMES).get(key, key)
            seed = dict(base)
            seed.update(name=label + " 副本", mode="solid",
                        bg=scheme["bg"], accent=scheme["accent"],
                        fg=scheme["fg"])
        self.open_theme_editor(seed)

    def copy_custom_theme(self, theme):
        """把一份自定义配色复制一份"""
        seed = dict(theme)
        seed.pop("id", None)
        seed.pop("_pil", None)
        seed["name"] = (seed.get("name") or "自定义") + " 副本"
        self.open_theme_editor(seed)

    def make_custom_theme_chip(self, parent, theme):
        """自定义配色的格子, 右键可以编辑或删除"""
        key = "custom:" + str(theme.get("id"))
        chosen = (key == self.theme)
        cell = self.theme_cell(parent)
        base = theme.get("bg") or P.bg
        if theme.get("mode") == "gradient":
            base = theme.get("grad_start") or base
        swatch, dot = self.theme_swatch(cell, base,
                                        theme.get("accent") or P.accent,
                                        chosen)
        name = self.theme_name(cell, theme.get("name") or "自定义", chosen)
        for widget in (cell, swatch, dot, name):
            widget.bind("<Button-1>", lambda ev, k=key: self.choose_theme(k))
            widget.bind("<Button-3>",
                        lambda ev, t=theme: self.popup_custom_theme(ev, t))

    def popup_custom_theme(self, event, theme):
        """右键自定义配色: 编辑 / 删除"""
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="编辑配色…",
                         command=lambda: self.open_theme_editor(theme))
        menu.add_command(label="复制一份",
                         command=lambda: self.copy_custom_theme(theme))
        menu.add_command(label="删除配色",
                         command=lambda: self.delete_custom_theme(theme))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def delete_custom_theme(self, theme):
        """删掉一份自定义配色"""
        name = theme.get("name") or "自定义"
        confirmed = messagebox.askyesno(
            "删除配色", "删除配色「{}」？".format(name), parent=self.settings_win)
        if not confirmed:
            return
        keep = []
        for item in self.custom_themes:
            if item.get("id") != theme.get("id"):
                keep.append(item)
        self.custom_themes = keep
        if self.theme == "custom:" + str(theme.get("id")):
            self.theme = "dark"
            self.accent = None
        self.save_conf()
        pos = self.settings_pos()
        self.close_settings()
        self.reload_ui()
        self.open_settings(pos)

    def choose_show_stat(self, value):
        """顶栏统计显示 / 隐藏"""
        self.show_stat = bool(value)
        self.save_conf()
        pending = sum(1 for it in self.store.items if not it.get("done"))
        self.update_stat(pending)
        self.fit_width(self.root.winfo_width())
        self.restyle_group("stat", self.show_stat)

    def choose_theme(self, key):
        """换配色(整块界面重建)"""
        if key == self.theme:
            return
        pos = self.settings_pos()
        self.close_settings()
        self.theme = key
        self.accent = None
        self.save_conf()
        self.reload_ui()
        self.open_settings(pos)

    def pick_accent(self):
        """自定义强调色"""
        rgb, picked = colorchooser.askcolor(color=P.accent, parent=self.settings_win,
                                            title="选择强调色")
        if not picked:
            return
        pos = self.settings_pos()
        self.close_settings()
        self.accent = picked
        custom = self.custom_theme()
        if custom is not None:
            # 自定义配色的强调色存在它自己身上
            custom["accent"] = picked
        else:
            set_theme(self.theme, picked)
        self.save_conf()
        self.reload_ui()
        self.open_settings(pos)

    # ---------------- 自定义配色编辑器 ----------------

    def copy_theme_image(self, source):
        """把选的背景图复制到 theme_bg 目录, 返回相对路径"""
        folder = os.path.join(APP_DIR, "theme_bg")
        if not os.path.isdir(folder):
            os.makedirs(folder)
        ext = os.path.splitext(source)[1].lower() or ".png"
        name = uuid.uuid4().hex[:10] + ext
        shutil.copyfile(source, os.path.join(folder, name))
        return "theme_bg/" + name

    def open_theme_editor(self, theme=None):
        """新建 / 编辑一份自定义配色

        :param theme: 要编辑的配色字典; 不传就是新建
        """
        existing = dict(theme) if theme else {}
        mode = existing.get("mode") or ("image" if existing.get("image") else "solid")
        state = {
            "bg": existing.get("bg") or "#1b1d24",
            "accent": existing.get("accent") or P.accent,
            "image": existing.get("image") or "",
            "mode": mode,
            "zoom": float(existing.get("zoom") or 1.0),
            "offset": list(existing.get("offset") or [0.0, 0.0]),
            "alpha": float(existing.get("alpha") or 0.0),
            "grad_start": existing.get("grad_start") or "#1b2030",
            "grad_end": existing.get("grad_end") or "#3a2a52",
            "grad_angle": existing.get("grad_angle") or "vertical",
            "fg": existing.get("fg") or "",
        }

        win = tk.Toplevel(self.settings_win or self.root)
        win.withdraw()
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg=P.border)
        self.theme_editor = win

        body = tk.Frame(win, bg=P.bg)
        body.pack(fill="both", expand=True, padx=1, pady=1)
        head = tk.Frame(body, bg=P.head, height=38)
        head.pack(fill="x")
        head.pack_propagate(False)
        editing = theme is not None and any(t is theme
                                            for t in self.custom_themes)
        if editing:
            title = "编辑配色"
        elif theme:
            title = "复制配色"
        else:
            title = "新建配色"
        tk.Label(head, text=title, bg=P.head, fg=P.fg,
                 font=self.f_group).pack(side="left", padx=14)
        close = tk.Label(head, text="\u2715", bg=P.head, fg=P.fg_dim,
                         font=self.f_small, width=2, cursor="hand2")
        close.pack(side="right", padx=6)
        close.bind("<Button-1>", lambda ev: self.close_theme_editor())

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

        form = tk.Frame(body, bg=P.bg)
        form.pack(fill="both", expand=True, padx=16, pady=(12, 0))

        def row(parent, label, width=8):
            line = tk.Frame(parent, bg=P.bg)
            line.pack(fill="x", pady=(0, 8))
            tk.Label(line, text=label, bg=P.bg, fg=P.fg_dim,
                     font=self.f_small, anchor="w", width=width).pack(side="left")
            return line

        name_row = row(form, "名称")
        name_var = tk.StringVar(value=existing.get("name") or
                               "我的配色 {}".format(len(self.custom_themes) + 1))
        entry = tk.Entry(name_row, textvariable=name_var, bg=P.bg_alt, fg=P.fg,
                         insertbackground=P.accent, relief="flat", bd=0,
                         highlightthickness=1, highlightbackground=P.border,
                         highlightcolor=P.accent, font=self.f_item)
        entry.pack(side="left", fill="x", expand=True, ipady=4)

        mode_row = row(form, "模式")
        mode_chips = {}
        for key, label in (("solid", "纯色"), ("gradient", "渐变"), ("image", "图片")):
            chip = tk.Label(mode_row, text=label, bg=P.bg_alt, fg=P.fg_dim,
                            font=self.f_small, padx=14, pady=5, cursor="hand2")
            chip.pack(side="left", padx=(0, 8))
            chip.bind("<Button-1>", lambda ev, k=key: set_mode(k))
            mode_chips[key] = chip

        # 纯色模式: 只挑底色
        solid_frame = tk.Frame(form, bg=P.bg)
        bg_row = row(solid_frame, "底色")
        bg_swatch = tk.Frame(bg_row, bg=state["bg"], width=36, height=22,
                             highlightthickness=1, highlightbackground=P.border)
        bg_swatch.pack(side="left")
        bg_swatch.pack_propagate(False)
        bg_btn = tk.Label(bg_row, text="选择…", bg=P.bg_alt, fg=P.fg_dim,
                          font=self.f_small, padx=10, pady=2, cursor="hand2")
        bg_btn.pack(side="left", padx=8)
        bg_btn.bind("<Button-1>", lambda ev: pick_bg())

        # 渐变模式: 起止两个颜色 + 方向
        gradient_frame = tk.Frame(form, bg=P.bg)
        start_row = row(gradient_frame, "起始色")
        start_swatch = tk.Frame(start_row, bg=state["grad_start"], width=36,
                                height=22, highlightthickness=1,
                                highlightbackground=P.border)
        start_swatch.pack(side="left")
        start_swatch.pack_propagate(False)
        start_btn = tk.Label(start_row, text="选择…", bg=P.bg_alt, fg=P.fg_dim,
                             font=self.f_small, padx=10, pady=2, cursor="hand2")
        start_btn.pack(side="left", padx=8)
        start_btn.bind("<Button-1>", lambda ev: pick_grad("start"))

        end_row = row(gradient_frame, "结束色")
        end_swatch = tk.Frame(end_row, bg=state["grad_end"], width=36,
                              height=22, highlightthickness=1,
                              highlightbackground=P.border)
        end_swatch.pack(side="left")
        end_swatch.pack_propagate(False)
        end_btn = tk.Label(end_row, text="选择…", bg=P.bg_alt, fg=P.fg_dim,
                           font=self.f_small, padx=10, pady=2, cursor="hand2")
        end_btn.pack(side="left", padx=8)
        end_btn.bind("<Button-1>", lambda ev: pick_grad("end"))

        angle_row = row(gradient_frame, "方向")
        angle_chips = {}
        for key, label in (("vertical", "竖向"), ("horizontal", "横向"),
                           ("diagonal", "斜向")):
            chip = tk.Label(angle_row, text=label, bg=P.bg_alt, fg=P.fg_dim,
                            font=self.f_small, padx=12, pady=4, cursor="hand2")
            chip.pack(side="left", padx=(0, 8))
            chip.bind("<Button-1>", lambda ev, k=key: set_angle(k))
            angle_chips[key] = chip

        # 预览按主窗口的宽高比来, 看到的就是实际会露出来的那一块
        try:
            win_w = self.root.winfo_width() or 330
            win_h = self.root.winfo_height() or 460
        except Exception:
            win_w, win_h = 330, 460
        ph = 260
        pw = int(round(ph * float(win_w) / float(win_h)))
        pw = max(130, min(400, pw))

        # 图片模式: 图片 + 拖动裁剪 + 缩放 + 透明度
        image_frame = tk.Frame(form, bg=P.bg)
        image_row = row(image_frame, "图片")
        image_label = tk.Label(image_row,
                               text=os.path.basename(state["image"]) or "没有",
                               bg=P.bg, fg=P.fg_dim, font=self.f_small,
                               anchor="w")
        image_label.pack(side="left", fill="x", expand=True)
        image_btn = tk.Label(image_row, text="选图片…", bg=P.bg_alt,
                             fg=P.fg_dim, font=self.f_small, padx=10, pady=2,
                             cursor="hand2")
        image_btn.pack(side="left", padx=8)
        image_btn.bind("<Button-1>", lambda ev: pick_image())
        clear_btn = tk.Label(image_row, text="清除", bg=P.bg, fg=P.fg_faint,
                             font=self.f_small, padx=6, pady=2, cursor="hand2")
        clear_btn.pack(side="left")
        clear_btn.bind("<Button-1>", lambda ev: clear_image())
        reset_btn = tk.Label(image_row, text="重置", bg=P.bg, fg=P.fg_faint,
                             font=self.f_small, padx=6, pady=2, cursor="hand2")
        reset_btn.pack(side="left")
        reset_btn.bind("<Button-1>", lambda ev: reset_view())

        preview = tk.Canvas(image_frame, width=pw, height=ph, bg=P.bg_alt,
                            highlightthickness=1, highlightbackground=P.border,
                            cursor="fleur")
        preview.pack(anchor="w", pady=(0, 8))

        zoom_row = row(image_frame, "缩放", width=6)
        zoom_scale = tk.Scale(zoom_row, from_=100, to=250, resolution=5,
                              orient="horizontal", bg=P.bg, fg=P.fg_dim,
                              troughcolor=P.bg_alt, highlightthickness=0, bd=0,
                              sliderrelief="flat", showvalue=False, length=220,
                              command=lambda v: set_zoom(v))
        zoom_scale.pack(side="left")
        zoom_value = tk.Label(zoom_row, text="{}%".format(int(state["zoom"] * 100)),
                              bg=P.bg, fg=P.fg_faint, font=self.f_small)
        zoom_value.pack(side="left", padx=8)

        alpha_row = row(form, "透明度", width=6)
        alpha_scale = tk.Scale(alpha_row, from_=0, to=60, resolution=5,
                               orient="horizontal", bg=P.bg, fg=P.fg_dim,
                               troughcolor=P.bg_alt, highlightthickness=0, bd=0,
                               sliderrelief="flat", showvalue=False, length=220,
                               command=lambda v: set_alpha(v))
        alpha_scale.pack(side="left")
        alpha_value = tk.Label(alpha_row,
                               text="{}%".format(int(state["alpha"] * 100)),
                               bg=P.bg, fg=P.fg_faint, font=self.f_small)
        alpha_value.pack(side="left", padx=8)
        alpha_row.pack_forget()

        fg_row = row(form, "文字色")
        fg_swatch = tk.Frame(fg_row, bg=state["fg"] or auto_text_color(state["bg"]),
                             width=36, height=22, highlightthickness=1,
                             highlightbackground=P.border)
        fg_swatch.pack(side="left")
        fg_swatch.pack_propagate(False)
        fg_btn = tk.Label(fg_row, text="选择…", bg=P.bg_alt, fg=P.fg_dim,
                          font=self.f_small, padx=10, pady=2, cursor="hand2")
        fg_btn.pack(side="left", padx=8)
        fg_btn.bind("<Button-1>", lambda ev: pick_fg())
        fg_auto_btn = tk.Label(fg_row, text="自动", bg=P.bg, fg=P.fg_faint,
                               font=self.f_small, padx=6, pady=2, cursor="hand2")
        fg_auto_btn.pack(side="left")
        fg_auto_btn.bind("<Button-1>", lambda ev: reset_fg())
        fg_row.pack_forget()

        accent_row = row(form, "强调色")
        accent_swatch = tk.Frame(accent_row, bg=state["accent"], width=36,
                                 height=22, highlightthickness=1,
                                 highlightbackground=P.border)
        accent_swatch.pack(side="left")
        accent_swatch.pack_propagate(False)
        accent_btn = tk.Label(accent_row, text="选择…", bg=P.bg_alt,
                              fg=P.fg_dim, font=self.f_small, padx=10, pady=2,
                              cursor="hand2")
        accent_btn.pack(side="left", padx=8)
        accent_btn.bind("<Button-1>", lambda ev: pick_accent())

        note = self.settings_note(
            body, "渐变 / 图片模式：底图铺满整个窗口，文字保持不透明。"
                  "「透明度」是把底图往底色里混，0% 就是原图满色。"
                  "文字色不选就按底色自动配，「自动」按钮可以恢复。"
                  "图片模式可以在预览里拖动挪位置、滚轮缩放，比例跟实际窗口一致。")
        note.pack(fill="x", padx=18, pady=(8, 0))

        def pick_bg():
            _, picked = colorchooser.askcolor(color=state["bg"], parent=win,
                                              title="选择底色")
            if picked:
                state["bg"] = picked
                bg_swatch.configure(bg=picked)
                if not state["fg"]:
                    fg_swatch.configure(bg=auto_text_color(picked))

        def pick_fg():
            _, picked = colorchooser.askcolor(
                color=state["fg"] or auto_text_color(state["bg"]), parent=win,
                title="选择文字颜色")
            if picked:
                state["fg"] = picked
                fg_swatch.configure(bg=picked)

        def reset_fg():
            state["fg"] = ""
            fg_swatch.configure(bg=auto_text_color(state["bg"]))

        def pick_accent():
            _, picked = colorchooser.askcolor(color=state["accent"], parent=win,
                                              title="选择强调色")
            if picked:
                state["accent"] = picked
                accent_swatch.configure(bg=picked)

        def pick_grad(which):
            """渐变模式选起始色 / 结束色"""
            key = "grad_start" if which == "start" else "grad_end"
            swatch = start_swatch if which == "start" else end_swatch
            _, picked = colorchooser.askcolor(color=state[key], parent=win,
                                              title="选择渐变颜色")
            if picked:
                state[key] = picked
                swatch.configure(bg=picked)

        def set_angle(key):
            state["grad_angle"] = key
            for chip_key, chip in angle_chips.items():
                chosen = (chip_key == key)
                chip.configure(bg=P.accent if chosen else P.bg_alt,
                               fg=best_text_color(P.accent) if chosen else P.fg_dim)

        def image_path():
            path = state["image"]
            if not path:
                return ""
            if os.path.isabs(path):
                return path if os.path.exists(path) else ""
            full = os.path.join(APP_DIR, path.replace("/", os.sep))
            return full if os.path.exists(full) else ""

        def pick_image():
            path = filedialog.askopenfilename(
                parent=win, title="选择背景图片",
                filetypes=[("图片", "*.png *.jpg *.jpeg *.bmp *.gif *.webp"),
                           ("所有文件", "*.*")])
            if not path:
                return
            try:
                state["image"] = self.copy_theme_image(path)
            except Exception as exc:
                messagebox.showerror("选择图片", "复制图片失败：{}".format(exc),
                                     parent=win)
                return
            state["_pil"] = None
            state["offset"] = [0.0, 0.0]
            image_label.config(text=os.path.basename(state["image"]))
            render_preview()

        def clear_image():
            state["image"] = ""
            state["_pil"] = None
            image_label.config(text="没有")
            render_preview()

        def set_mode(key):
            state["mode"] = key
            for chip_key, chip in mode_chips.items():
                chosen = (chip_key == key)
                chip.configure(bg=P.accent if chosen else P.bg_alt,
                               fg=best_text_color(P.accent) if chosen else P.fg_dim)
            solid_frame.pack_forget()
            gradient_frame.pack_forget()
            image_frame.pack_forget()
            alpha_row.pack_forget()
            fg_row.pack_forget()
            if key == "image":
                image_frame.pack(fill="x", before=accent_row)
                alpha_row.pack(fill="x", before=accent_row)
                resize_window(680)
                render_preview()
            elif key == "gradient":
                gradient_frame.pack(fill="x", before=accent_row)
                alpha_row.pack(fill="x", before=accent_row)
                resize_window(460)
            else:
                solid_frame.pack(fill="x", before=accent_row)
                resize_window(396)
            fg_row.pack(fill="x", before=accent_row)

        def resize_window(height):
            """按模式把编辑框调高/调矮, 别留一大片空白"""
            try:
                x = win.winfo_x()
                y = win.winfo_y()
                win.geometry("{}x{}+{}+{}".format(470, height, x, y))
                win.after(20, lambda w=win: round_corners(w, 12))
            except Exception:
                pass

        def set_zoom(value):
            state["zoom"] = max(1.0, min(2.5, float(value) / 100.0))
            zoom_value.config(text="{}%".format(int(round(state["zoom"] * 100))))
            render_preview()

        def set_alpha(value):
            state["alpha"] = max(0.0, min(0.6, float(value) / 100.0))
            alpha_value.config(
                text="{}%".format(int(round(state["alpha"] * 100))))

        def reset_view():
            state["offset"] = [0.0, 0.0]
            state["zoom"] = 1.0
            zoom_scale.set(100)
            render_preview()

        def preview_wheel(ev):
            step = 5 if ev.delta > 0 else -5
            value = max(100, min(250, int(round(state["zoom"] * 100)) + step))
            zoom_scale.set(value)
            return "break"

        def render_preview():
            preview.delete("all")
            if not state["image"] or Image is None:
                preview.create_text(pw // 2, ph // 2,
                                    text="选一张图片后在这里拖动调整位置",
                                    fill=P.fg_faint, font=self.f_small)
                return
            path = image_path()
            if not path:
                return
            try:
                image = state.get("_pil")
                if image is None:
                    image = Image.open(path).convert("RGB")
                    image.thumbnail((1600, 1600), Image.LANCZOS)
                    state["_pil"] = image
                zoom = max(1.0, min(3.0, float(state["zoom"])))
                scale = max(pw / float(image.width),
                            ph / float(image.height)) * zoom
                new_w = max(pw, int(round(image.width * scale)))
                new_h = max(ph, int(round(image.height * scale)))
                scaled = image.resize((new_w, new_h), Image.BILINEAR)
                span_x = new_w - pw
                span_y = new_h - ph
                left = int(round((state["offset"][0] + 1.0) / 2.0 * span_x))
                top = int(round((state["offset"][1] + 1.0) / 2.0 * span_y))
                crop = scaled.crop((left, top, left + pw, top + ph))
                photo = ImageTk.PhotoImage(crop)
                preview.create_image(0, 0, anchor="nw", image=photo)
                preview.image = photo
                state["_span"] = (span_x, span_y)
            except Exception:
                pass

        preview_drag = {}

        def preview_press(ev):
            preview_drag["x"] = ev.x
            preview_drag["y"] = ev.y

        def preview_move(ev):
            if "x" not in preview_drag:
                return
            span_x, span_y = state.get("_span") or (0, 0)
            dx = ev.x - preview_drag["x"]
            dy = ev.y - preview_drag["y"]
            preview_drag["x"] = ev.x
            preview_drag["y"] = ev.y
            if span_x > 0:
                value = state["offset"][0] - dx * 2.0 / span_x
                state["offset"][0] = max(-1.0, min(1.0, value))
            if span_y > 0:
                value = state["offset"][1] - dy * 2.0 / span_y
                state["offset"][1] = max(-1.0, min(1.0, value))
            render_preview()

        def preview_release(ev):
            preview_drag.pop("x", None)
            preview_drag.pop("y", None)

        preview.bind("<ButtonPress-1>", preview_press)
        preview.bind("<B1-Motion>", preview_move)
        preview.bind("<ButtonRelease-1>", preview_release)
        preview.bind("<MouseWheel>", preview_wheel)

        buttons = tk.Frame(body, bg=P.bg)
        buttons.pack(fill="x", padx=16, pady=14)
        cancel = tk.Label(buttons, text="取消", bg=P.bg_alt, fg=P.fg_dim,
                          font=self.f_small, padx=14, pady=6, cursor="hand2")
        cancel.pack(side="right")
        cancel.bind("<Button-1>", lambda ev: self.close_theme_editor())
        save = tk.Label(buttons, text="保存", bg=P.accent,
                        fg=best_text_color(P.accent), font=self.f_small,
                        padx=16, pady=6, cursor="hand2")
        save.pack(side="right", padx=(0, 8))
        save.bind("<Button-1>", lambda ev: self.save_custom_theme(
            state, name_var, theme, win))

        win.bind("<Escape>", lambda ev: self.close_theme_editor())
        zoom_scale.set(int(round(state["zoom"] * 100)))
        alpha_scale.set(int(round(state["alpha"] * 100)))
        set_angle(state["grad_angle"])
        set_mode(state["mode"])
        render_preview()

        sizes = {"solid": 396, "gradient": 460, "image": 680}
        width, height = 470, sizes.get(state["mode"], 360)
        base = self.settings_win or self.root
        x = base.winfo_rootx() + (base.winfo_width() - width) // 2
        y = base.winfo_rooty() + (base.winfo_height() - height) // 2
        left, top, right, bottom = self.settings_bounds()
        x = max(left + 8, min(x, right - width - 8))
        y = max(top + 8, min(y, bottom - height - 8))
        win.geometry("{}x{}+{}+{}".format(width, height, x, y))
        win.deiconify()
        win.after(20, lambda w=win: round_corners(w, 12))
        win.lift()
        win.focus_force()
        entry.focus_set()
        try:
            win.grab_set()
        except Exception:
            pass

    def close_theme_editor(self):
        """关掉配色编辑框"""
        win = getattr(self, "theme_editor", None)
        self.theme_editor = None
        if win is not None:
            try:
                win.grab_release()
            except Exception:
                pass
            try:
                win.destroy()
            except Exception:
                pass

    def save_custom_theme(self, state, name_var, theme, win):
        """保存自定义配色并马上用上

        :param state: 里面是 bg / accent / image
        :param name_var: 名称输入框
        :param theme: 原来的配色字典; 新建时是 None
        :param win: 编辑框窗口
        """
        name = name_var.get().strip() or "我的配色"
        if theme is None:
            theme = {"id": uuid.uuid4().hex[:8]}
            self.custom_themes.append(theme)
        elif not any(item is theme for item in self.custom_themes):
            # 复制出来的草稿, 保存时当成新的一份
            theme["id"] = uuid.uuid4().hex[:8]
            self.custom_themes.append(theme)
        theme.update(name=name, bg=state["bg"], accent=state["accent"],
                     image=state["image"], mode=state.get("mode", "solid"),
                     fg=state.get("fg") or "",
                     grad_start=state.get("grad_start") or "#1b2030",
                     grad_end=state.get("grad_end") or "#2a2a40",
                     grad_angle=state.get("grad_angle") or "vertical",
                     zoom=round(float(state.get("zoom") or 1.0), 3),
                     offset=[round(float(state.get("offset", [0.0, 0.0])[0]), 3),
                             round(float(state.get("offset", [0.0, 0.0])[1]), 3)],
                     alpha=round(float(state.get("alpha") or 0.0), 3))
        self.theme = "custom:" + theme["id"]
        self.accent = None
        self.save_conf()
        try:
            win.grab_release()
        except Exception:
            pass
        try:
            win.destroy()
        except Exception:
            pass
        self.theme_editor = None
        pos = self.settings_pos()
        self.close_settings()
        self.reload_ui()
        self.open_settings(pos)

    # ---------------- 排序 ----------------

    def build_sort_panel(self, panel):
        """手动拖动 / 按时间"""
        holder = self.settings_block(panel, "排序方式")
        self.settings_chip(holder, "手动拖动", self.sort_mode == "manual",
                           lambda: self.choose_sort("manual"),
                           group="sort", value="manual")
        self.settings_chip(holder, "按时间", self.sort_mode == "time",
                           lambda: self.choose_sort("time"),
                           group="sort", value="time")
        self._sort_note = self.settings_note(panel, "")
        self.update_sort_note()

    def update_sort_note(self):
        """按当前排序方式刷新说明"""
        if self.sort_mode == "time":
            text = ("按创建时间从早到晚排；已完成页按完成日期分组，可以折叠。"
                    "这个模式下不能手动拖动。")
        else:
            text = ("按住任务行上下拖动就能排序；拖到某个组中间会收进那个组。"
                    "也可以右键用 上移 / 下移。")
        try:
            self._sort_note.config(text=text)
        except Exception:
            pass

    def choose_sort(self, mode):
        """切换排序方式"""
        if mode == self.sort_mode:
            return
        self.sort_mode = mode
        self.save_conf()
        self.refresh()
        try:
            tip = "按时间排序" if mode == "time" else "双击便签 · 拖动排序"
            self.tip.config(text=tip)
        except Exception:
            pass
        self.restyle_group("sort", mode)
        self.update_sort_note()

    # ---------------- 窗口 ----------------

    def build_window_panel(self, panel):
        """显示方式 / 总在最前 / 窗口大小"""
        holder = self.settings_block(panel, "显示方式",
                                     "贴桌面：不占任务栏，藏在别的窗口下面")
        self.settings_chip(holder, "贴桌面", self.mode == "desktop",
                           lambda: self.choose_mode("desktop"),
                           group="mode", value="desktop")
        self.settings_chip(holder, "普通窗口", self.mode == "window",
                           lambda: self.choose_mode("window"),
                           group="mode", value="window")

        holder = self.settings_block(panel, "总在最前", "盖在别的窗口上面")
        self.settings_chip(holder, "开", self.topmost,
                           lambda: self.choose_topmost(True),
                           group="topmost", value=True)
        self.settings_chip(holder, "关", not self.topmost,
                           lambda: self.choose_topmost(False),
                           group="topmost", value=False)

        holder = self.settings_block(panel, "窗口大小",
                                     "自由调节时可以拖右下角的小斜纹改宽高")
        self.settings_chip(holder, "自由调节", not self.resize_locked,
                           lambda: self.choose_resize_lock(False),
                           group="size", value=False)
        self.settings_chip(holder, "锁定", bool(self.resize_locked),
                           lambda: self.choose_resize_lock(True),
                           group="size", value=True)

    def choose_mode(self, mode):
        """切换贴桌面 / 普通窗口; 窗口要重摆, 设置窗口跟着重开一次"""
        if mode == self.mode:
            return
        pos = self.settings_pos()
        self.close_settings()
        self.set_mode(mode)
        self.open_settings(pos)

    def choose_topmost(self, value):
        """切换总在最前"""
        value = bool(value)
        if value == self.topmost:
            return
        self.toggle_topmost()
        self.restyle_group("topmost", value)

    def choose_resize_lock(self, locked):
        """锁定 / 解开拖动改宽高"""
        locked = bool(locked)
        if locked == self.resize_locked:
            return
        self.set_resize_locked(locked)
        self.restyle_group("size", locked)

    # ---------------- 关于与更新 ----------------

    def build_about_panel(self, panel):
        """版本信息和检查更新"""
        block = tk.Frame(panel, bg=P.bg)
        block.pack(fill="x", pady=(0, 20))
        tk.Label(block, text="待办清单", bg=P.bg, fg=P.fg,
                 font=self.f_note_h1).pack(anchor="w")
        tk.Label(block, text="版本 {}   构建于 {}".format(
            updater.version_text(), updater.build_text()),
                 bg=P.bg, fg=P.fg_dim, font=self.f_small).pack(anchor="w",
                                                               pady=(6, 0))
        tk.Label(block, text="数据都在程序目录：{}".format(APP_DIR),
                 bg=P.bg, fg=P.fg_faint, font=self.f_small,
                 justify="left", wraplength=380).pack(anchor="w", pady=(6, 0))

        holder = self.settings_block(panel, "更新",
                                     "从 GitHub 上下载最新打包好的版本")
        row = tk.Frame(holder, bg=P.bg)
        row.pack(fill="x")
        self._update_btn = tk.Label(row, text="检查更新", bg=P.accent,
                                    fg=best_text_color(P.accent),
                                    font=self.f_small, padx=16, pady=7,
                                    cursor="hand2")
        self._update_btn.pack(side="left")
        self._update_btn.bind("<Button-1>",
                              lambda ev: self.start_update_check())
        self._update_btn.bind("<Enter>", lambda ev: self.hover_update_btn(True))
        self._update_btn.bind("<Leave>", lambda ev: self.hover_update_btn(False))

        self._update_status = tk.Label(panel, text="", bg=P.bg, fg=P.fg_dim,
                                       font=self.f_small, justify="left",
                                       anchor="w", wraplength=380)
        self._update_status.pack(fill="x")

    def hover_update_btn(self, entering):
        """更新按钮的悬停效果 (下载中不让点)"""
        if self._update_busy:
            return
        self._update_btn.configure(bg=P.accent if not entering else P.hover,
                                   fg=best_text_color(P.accent))

    def update_status(self, text, color=None):
        """改更新状态那一行字"""
        try:
            self._update_status.config(text=text, fg=color or P.fg_dim)
        except Exception:
            pass

    def set_update_button(self, text, enabled):
        """更新按钮的文字和可用状态"""
        self._update_busy = not enabled
        try:
            self._update_btn.config(
                text=text,
                bg=P.accent if enabled else P.bg_alt,
                fg=best_text_color(P.accent) if enabled else P.fg_faint,
                cursor="hand2" if enabled else "arrow")
        except Exception:
            pass

    def start_update_check(self):
        """点"检查更新": 后台查一下有没有新版本"""
        if self._update_busy:
            return
        self._update_busy = True
        self.set_update_button("检查中…", False)
        self.update_status("正在检查更新…", P.fg_dim)
        threading.Thread(target=self.update_worker, daemon=True).start()
        self.root.after(60, self.poll_update_events)

    def poll_update_events(self):
        """主线程里取后台线程的进度消息

        后台线程只往队列里放东西, 不直接碰 Tk, 免得线程不安全。
        """
        while True:
            try:
                event = self._update_queue.get_nowait()
            except queue.Empty:
                break
            self.handle_update_event(event)
        if self._update_busy or not self._update_queue.empty():
            self.root.after(60, self.poll_update_events)

    def handle_update_event(self, event):
        """处理一条后台消息: (类型, 内容...)"""
        kind = event[0]
        if kind == "status":
            self.update_status(event[1], event[2])
        elif kind == "progress":
            self.update_progress(event[1])
        elif kind == "done":
            self.finish_update(event[1], event[2])
        elif kind == "apply":
            self.ask_apply_update(event[1])

    def update_worker(self):
        """后台线程: 查版本 -> 下载 -> 把结果丢进队列"""
        events = self._update_queue
        try:
            latest = updater.fetch_latest()
            if not updater.is_newer(latest):
                events.put(("done", "已经是最新版本", True))
                return
            events.put(("status",
                        "发现新版本 {}，正在下载…".format(latest), P.accent))
            path = updater.download(
                progress=lambda ratio: events.put(("progress", ratio)))
            if path is None:
                events.put(("done", "已经是最新版本", True))
                return
            events.put(("apply", path))
        except Exception as exc:
            message = str(exc) or "更新失败"
            events.put(("done", "更新失败：" + message, False))

    def update_progress(self, ratio):
        """下载进度"""
        self.update_status("正在下载… {}%".format(int(ratio * 100)), P.accent)

    def finish_update(self, message, ok):
        """一次检查结束, 恢复按钮"""
        self.update_status(message, P.accent if ok else P.fg_dim)
        self.set_update_button("检查更新", True)

    def ask_apply_update(self, path):
        """下载好了, 问一句要不要马上重启换上新版本"""
        self.set_update_button("已下载", False)
        self.update_status("新版本已经下载好", P.accent)
        try:
            confirmed = messagebox.askyesno(
                "更新待办清单", "新版本已经下载好，现在重启完成更新？",
                parent=self.settings_win)
        except Exception:
            confirmed = False
        if not confirmed:
            updater.remove_quietly(path)
            self.finish_update("已取消更新", True)
            return
        try:
            updater.apply_and_restart(path)
        except Exception as exc:
            updater.remove_quietly(path)
            self.finish_update("更新失败：" + str(exc), False)
            return
        self.update_status("正在重启…", P.accent)
        self.root.after(400, self.quit)

    # ---------------- 整块重建 ----------------

    def reload_ui(self):
        """配色变了就整块重建界面, 省得一个个去改颜色"""
        self.finish_edit()
        pinned_ids = []
        for note_id, state in self.notes.items():
            if state.get("pinned"):
                pinned_ids.append(note_id)
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
            self.set_folded(True, animate=False)

        for note_id in pinned_ids:
            item = self.store.find_item(note_id)
            if item is not None:
                self.create_note(item, restore=True)

        if self._tray is not None:
            try:
                self._tray.icon = make_icon()
            except Exception:
                pass
