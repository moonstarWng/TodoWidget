# -*- coding: utf-8 -*-
"""设置窗口: 左边分类、右边选项, 外加检查更新"""

import ctypes
import os
import subprocess
import queue
import shutil
import threading
import tkinter as tk
import tkinter.font as tkfont
import uuid
from tkinter import colorchooser, filedialog, messagebox, ttk

try:
    from PIL import Image, ImageFilter, ImageFont, ImageGrab, ImageTk
except Exception:
    Image = None
    ImageFilter = None
    ImageFont = None
    ImageGrab = None
    ImageTk = None

from . import fonts, paths, updater
from .paths import DATA_DIR
from .theme import (P, GRADIENTS, THEMES, THEME_NAMES, auto_text_color,
                    best_text_color, mix_color, set_theme)
from .utils import make_icon, round_corners

# 设置窗口里各分类
SETTINGS_TABS = (("look", "外观"), ("sort", "排序"),
                 ("window", "窗口"), ("about", "关于与更新"))


class SettingsMixin:
    """设置窗口(按功能拆成几块面板)"""

    # ---------------- 窗口骨架 ----------------

    def open_settings(self, pos=None, scroll_pos=None):
        """打开设置窗口; 已经开着就抬起来

        :param pos: 窗口位置, 不传就摆到主窗口中间
        :param scroll_pos: 内容滚动位置, 重建后接着原来的地方
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
        if scroll_pos:
            # 等滚动区域算好再跳回去, 内容高度是异步算的, 多试两次
            def restore_scroll():
                try:
                    self._settings_scroll.update_idletasks()
                    self._settings_scroll.yview_moveto(scroll_pos)
                except Exception:
                    pass
            win.after(60, restore_scroll)
            win.after(200, restore_scroll)
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
        self._settings_chips = {}
        if win is not None:
            try:
                win.grab_release()
            except Exception:
                pass
            try:
                win.destroy()
            except Exception:
                pass

    def settings_state(self):
        """记下设置窗口的位置和滚动位置, 重建界面后原样恢复"""
        win = self.settings_win
        if win is None:
            return {}
        state = {}
        try:
            state["pos"] = (win.winfo_x(), win.winfo_y())
        except Exception:
            pass
        try:
            state["scroll_pos"] = self._settings_scroll.yview()[0]
        except Exception:
            pass
        return state

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
        chips = getattr(self, "_settings_chips", None) or {}
        for chip, chip_value in chips.get(group, []):
            chosen = (chip_value == value)
            chip._chosen = chosen
            chip.configure(bg=P.accent if chosen else P.bg_alt,
                           fg=best_text_color(P.accent) if chosen else P.fg_dim)

    def pick_screen_color(self, parent, on_pick):
        """全屏吸管: 在屏幕上点一下, 取那个像素的颜色

        先抓一张全屏截图当底, 点了直接在图里取像素, 所以在别的窗口、
        网页、图片上都能取。

        :param parent: 父窗口
        :param on_pick: 取到颜色后的回调, 参数是 '#rrggbb'
        """
        if Image is None or ImageTk is None:
            return
        try:
            shot = ImageGrab.grab(all_screens=True)
        except Exception:
            return
        win = tk.Toplevel(parent)
        win.withdraw()
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg="#000000")
        # 铺满整个虚拟桌面: 尺寸直接按截图来, 位置用虚拟桌面的原点
        vx = win.winfo_vrootx()
        vy = win.winfo_vrooty()
        vw = max(200, shot.width)
        vh = max(200, shot.height)
        win.geometry("{}x{}+{}+{}".format(vw, vh, vx, vy))
        canvas = tk.Canvas(win, width=vw, height=vh, highlightthickness=0,
                           bd=0, cursor="crosshair")
        canvas.pack()
        photo = ImageTk.PhotoImage(shot)
        canvas.create_image(0, 0, anchor="nw", image=photo)
        canvas.image = photo
        canvas.create_rectangle(0, 0, vw, vh, fill="#000000", outline="",
                                stipple="gray25")
        canvas.create_text(vw // 2, 26, text="点一下取色 · Esc 取消",
                           fill="#ffffff", font=self.f_small)
        ring = canvas.create_rectangle(0, 0, 0, 0, outline="#ffffff", width=2)
        chip = canvas.create_rectangle(0, 0, 0, 0, outline="#ffffff")
        label = canvas.create_text(0, 0, text="", fill="#ffffff", anchor="nw",
                                   font=self.f_small)

        def sample(ev):
            """按光标位置取色并更新放大镜

            :param ev: 鼠标事件
            """
            x = max(0, min(shot.width - 1, ev.x_root - vx))
            y = max(0, min(shot.height - 1, ev.y_root - vy))
            try:
                rgb = shot.getpixel((x, y))[:3]
            except Exception:
                return None
            color = "#{:02x}{:02x}{:02x}".format(*rgb)
            px, py = ev.x_root - vx, ev.y_root - vy
            canvas.coords(ring, px - 7, py - 7, px + 7, py + 7)
            canvas.coords(chip, px + 16, py + 12, px + 40, py + 36)
            canvas.itemconfigure(chip, fill=color)
            canvas.coords(label, px + 46, py + 14)
            canvas.itemconfigure(label, text=color)
            return color

        def close():
            """关掉吸管"""
            try:
                win.grab_release()
            except Exception:
                pass
            try:
                win.destroy()
            except Exception:
                pass

        def on_click(ev):
            color = sample(ev)
            close()
            if color:
                try:
                    on_pick(color)
                except Exception:
                    pass

        canvas.bind("<Button-1>", on_click)
        canvas.bind("<Motion>", sample)
        canvas.bind("<Button-3>", lambda ev: close())
        win.bind("<Escape>", lambda ev: close())
        win.deiconify()
        win.lift()
        try:
            win.grab_set()
        except Exception:
            pass
        win.focus_force()

    def settings_note(self, parent, text):
        """一行灰色小字说明"""
        label = tk.Label(parent, text=text, bg=P.bg, fg=P.fg_faint,
                         font=self.f_small, justify="left", wraplength=380,
                         anchor="w")
        label.pack(fill="x", pady=(6, 0))
        return label

    # ---------------- 外观 ----------------

    def favorite_keys(self):
        """收藏里现在还有效的配色键(自定义配色可能被删了)"""
        keys = []
        for key in self.favorite_themes:
            if self.theme_exists(key):
                keys.append(key)
        return keys

    def theme_exists(self, key):
        """这个配色键现在还有效吗

        :param key: 配色键, 比如 dark / custom:xxx / gradient:xxx
        """
        if key.startswith("gradient:"):
            return key.split(":", 1)[1] in GRADIENTS
        if key.startswith("custom:"):
            return self.custom_theme(key) is not None
        return key in THEMES

    def is_favorite_theme(self, key):
        """这个配色收藏了没有

        :param key: 配色键
        """
        return key in self.favorite_themes

    def toggle_favorite_theme(self, key):
        """收藏 / 取消收藏一个配色, 然后重建配色列表

        :param key: 配色键
        """
        if key in self.favorite_themes:
            self.favorite_themes.remove(key)
        else:
            self.favorite_themes.append(key)
        self.conf["favorites"] = list(self.favorite_themes)
        state = self.settings_state()
        self.close_settings()
        self.save_conf()
        self.open_settings(**state)

    def add_favorite_menu(self, menu, key):
        """右键菜单里加一条 收藏 / 取消收藏

        :param menu: tk.Menu
        :param key: 配色键
        """
        if self.is_favorite_theme(key):
            label = "取消收藏"
        else:
            label = "收藏到「我的收藏」"
        menu.add_command(label=label,
                         command=lambda k=key: self.toggle_favorite_theme(k))

    def make_theme_chip_by_key(self, parent, key):
        """按配色键画一个格子(收藏区用)

        :param parent: 放在哪一行
        :param key: 配色键, 比如 dark / custom:xxx / gradient:xxx
        """
        if key.startswith("gradient:"):
            short = key.split(":", 1)[1]
            spec = GRADIENTS.get(short)
            if spec is not None:
                self.make_gradient_chip(parent, short, spec)
            return
        custom = self.custom_theme(key)
        if custom is not None:
            self.make_custom_theme_chip(parent, custom)
            return
        if key in THEMES:
            self.make_theme_chip(parent, key, THEME_NAMES.get(key, key))

    def build_look_panel(self, panel):
        """配色 / 自定义配色 / 强调色 / 质感 / 统计"""
        holder = self.settings_block(
            panel, "我的收藏", "右键任意配色, 可以收藏到这里")
        favorites = self.favorite_keys()
        if favorites:
            grid = tk.Frame(holder, bg=P.bg)
            grid.pack(fill="x")
            row = None
            for index, key in enumerate(favorites):
                if index % 4 == 0:
                    row = tk.Frame(grid, bg=P.bg)
                    row.pack(fill="x", pady=(0, 6))
                self.make_theme_chip_by_key(row, key)
        else:
            tk.Label(holder, text="还没有收藏", bg=P.bg, fg=P.fg_faint,
                     font=self.f_small).pack(anchor="w")

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
        if kind == "gradient":
            full_key = "gradient:" + key
        else:
            full_key = key
        self.add_favorite_menu(menu, full_key)
        self.popup_menu(menu, event.x_root, event.y_root)

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
        self.add_favorite_menu(menu, "custom:" + str(theme.get("id")))
        self.popup_menu(menu, event.x_root, event.y_root)

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
        state = self.settings_state()
        self.close_settings()
        self.reload_ui()
        self.open_settings(**state)

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
        state = self.settings_state()
        self.close_settings()
        self.theme = key
        self.accent = None
        self.save_conf()
        self.reload_ui()
        self.open_settings(**state)

    def pick_accent(self):
        """自定义强调色"""
        rgb, picked = colorchooser.askcolor(color=P.accent, parent=self.settings_win,
                                            title="选择强调色")
        if not picked:
            return
        state = self.settings_state()
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
        self.open_settings(**state)

    # ---------------- 自定义配色编辑器 ----------------

    def copy_theme_image(self, source):
        """把选的背景图复制到 theme_bg 目录, 返回相对路径"""
        folder = os.path.join(DATA_DIR, "theme_bg")
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
            "font_cn": existing.get("font_cn") or "",
            "font_latin": existing.get("font_latin") or "",
            "scrim_mode": existing.get("scrim") or "frost",
            "radius": int(existing.get("radius") or 0),
            "border_mode": (existing.get("border") or {}).get("mode") or "none",
            "border_width": int((existing.get("border") or {}).get("width") or 2),
            "border_color": (existing.get("border") or {}).get("color") or "#3b7cf6",
            "border_color2": (existing.get("border") or {}).get("color2") or "#8a5cf6",
            "header_split": bool(existing.get("header_split")),
            "header_color": existing.get("header_color") or "#17181d",
            "footer_split": bool(existing.get("footer_split")),
            "footer_color": existing.get("footer_color") or "#17181d",
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

        # 保存/取消 先占住底部, 内容再多也不会把它挤出窗口
        buttons = tk.Frame(body, bg=P.bg)
        buttons.pack(side="bottom", fill="x", padx=16, pady=12)

        columns = tk.Frame(body, bg=P.bg)
        columns.pack(fill="both", expand=True, padx=16, pady=(12, 0))
        form = tk.Frame(columns, bg=P.bg)          # 左栏: 名称 / 模式 / 预览
        form.pack(side="left", fill="y")
        right = tk.Frame(columns, bg=P.bg)          # 右栏: 颜色 / 文字 / 边框
        right.pack(side="left", fill="both", expand=True, padx=(18, 0))
        tab_row = tk.Frame(right, bg=P.bg)
        tab_row.pack(fill="x")
        pages = tk.Frame(right, bg=P.bg)
        pages.pack(fill="both", expand=True, pady=(10, 0))
        page_color = tk.Frame(pages, bg=P.bg)
        page_look = tk.Frame(pages, bg=P.bg)
        page_font = tk.Frame(pages, bg=P.bg)
        tab_chips = {}

        for key, label in (("color", "颜色"), ("look", "外观"),
                           ("font", "字体")):
            chip = tk.Label(tab_row, text=label, bg=P.bg_alt, fg=P.fg_dim,
                            font=self.f_small, padx=16, pady=6, cursor="hand2")
            chip.pack(side="left", padx=(0, 8))
            chip.bind("<Button-1>", lambda ev, k=key: show_page(k))
            tab_chips[key] = chip

        def row(parent, label, width=8):
            line = tk.Frame(parent, bg=P.bg)
            line.pack(fill="x", pady=(0, 8))
            tk.Label(line, text=label, bg=P.bg, fg=P.fg_dim,
                     font=self.f_small, anchor="w", width=width).pack(side="left")
            return line

        def section(parent, title, desc="", wrap=280):
            """带细边框的区块, 返回里面放控件的容器

            :param parent: 放在哪个页
            :param title: 区块标题
            :param desc: 一行说明
            :param wrap: 说明文字的折行宽度
            """
            box = tk.Frame(parent, bg=P.bg, highlightthickness=1,
                           highlightbackground=P.border)
            box.pack(fill="x", pady=(0, 10))
            inner = tk.Frame(box, bg=P.bg)
            inner.pack(fill="x", padx=10, pady=8)
            tk.Label(inner, text=title, bg=P.bg, fg=P.fg,
                     font=self.f_group).pack(anchor="w")
            if desc:
                tk.Label(inner, text=desc, bg=P.bg, fg=P.fg_dim,
                         font=self.f_small, anchor="w", justify="left",
                         wraplength=wrap).pack(fill="x", pady=(2, 0))
            holder = tk.Frame(inner, bg=P.bg)
            holder.pack(fill="x", pady=(8, 0))
            # 外框挂在容器上, 需要整块显示/隐藏时用它
            holder.box = box
            return holder

        def dropper(parent, callback):
            """一行里放个吸管按钮, 点了进全屏取色

            :param parent: 放在哪一行
            :param callback: 取到颜色后怎么用
            """
            btn = tk.Label(parent, text="吸管", bg=P.bg, fg=P.fg_faint,
                           font=self.f_small, padx=6, cursor="hand2")
            btn.pack(side="left", padx=(4, 0))
            btn.bind("<Button-1>",
                     lambda ev: self.pick_screen_color(win, callback))
            return btn


        name_row = row(columns, "名称")
        name_row.pack_configure(before=form)
        name_var = tk.StringVar(value=existing.get("name") or
                               "我的配色 {}".format(len(self.custom_themes) + 1))
        name_box = tk.Frame(name_row, bg=P.bg)
        name_box.pack(side="left", fill="x", expand=True)
        # 平时显示成文字, 点一下才变成输入框
        name_label = tk.Label(name_box, textvariable=name_var, bg=P.bg_alt,
                              fg=P.fg, font=self.f_item, anchor="w", padx=8,
                              pady=4, highlightthickness=1,
                              highlightbackground=P.border, cursor="hand2")
        name_label.pack(fill="x")
        entry = tk.Entry(name_box, textvariable=name_var, bg=P.bg_alt, fg=P.fg,
                         insertbackground=P.accent, relief="flat", bd=0,
                         highlightthickness=1, highlightbackground=P.border,
                         highlightcolor=P.accent, font=self.f_item)
        rename_state = {"before": ""}

        def start_rename(event=None):
            """点名称: 换成输入框, 光标放到最后

            :param event: 鼠标事件
            """
            if entry.winfo_manager():
                return "break"
            rename_state["before"] = name_var.get()
            name_label.pack_forget()
            entry.pack(fill="x", ipady=4)
            entry.focus_set()
            entry.icursor("end")
            entry.select_clear()
            entry.xview_moveto(1)
            return "break"

        def end_rename(event=None, cancel=False):
            """收起输入框, 变回文字

            :param event: 事件(回车 / 失焦)
            :param cancel: True 表示按了 Esc, 恢复原名
            """
            if not entry.winfo_manager():
                return "break"
            if cancel:
                name_var.set(rename_state["before"] or name_var.get())
            if not name_var.get().strip():
                name_var.set(rename_state["before"] or "我的配色")
            entry.pack_forget()
            name_label.pack(fill="x")
            return "break"

        name_label.bind("<Button-1>", start_rename)
        entry.bind("<Return>", end_rename)
        entry.bind("<Escape>", lambda ev: end_rename(cancel=True))
        entry.bind("<FocusOut>", end_rename)
        edit_hint = tk.Label(name_row, text="\u270e", bg=P.bg, fg=P.fg_faint,
                             font=self.f_small, cursor="hand2")
        edit_hint.pack(side="left", padx=(8, 0))
        edit_hint.bind("<Button-1>", start_rename)

        mode_box = section(form, "模式", wrap=210)
        mode_row = tk.Frame(mode_box, bg=P.bg)
        mode_row.pack(fill="x", pady=(0, 6))
        mode_chips = {}
        for key, label in (("solid", "纯色"), ("gradient", "渐变"),
                           ("image", "图片")):
            chip = tk.Label(mode_row, text=label, bg=P.bg_alt, fg=P.fg_dim,
                            font=self.f_small, padx=14, pady=5, cursor="hand2")
            chip.pack(side="left", padx=(0, 8))
            chip.bind("<Button-1>", lambda ev, k=key: set_mode(k))
            mode_chips[key] = chip

        mode_area = tk.Frame(mode_box, bg=P.bg)
        mode_area.pack(fill="x")

        # 纯色模式: 只挑底色
        solid_frame = tk.Frame(mode_area, bg=P.bg)
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
        gradient_frame = tk.Frame(mode_area, bg=P.bg)
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
        ph = 206
        pw = int(round(ph * float(win_w) / float(win_h)))
        pw = max(120, min(214, pw))

        # 图片模式: 底图 + 列表底图 + 缩放 + 透明度
        image_frame = section(form, "图片", "底图怎么裁、列表怎么衬", wrap=210)
        image_card = image_frame.box
        image_row = row(image_frame, "图片")
        image_label = tk.Label(image_row,
                               text=os.path.basename(state["image"]) or "没有",
                               bg=P.bg, fg=P.fg_dim, font=self.f_small,
                               anchor="w")
        image_label.pack(side="left", fill="x", expand=True)
        image_btn = tk.Label(image_row, text="选图…", bg=P.bg_alt,
                             fg=P.fg_dim, font=self.f_small, padx=8, pady=2,
                             cursor="hand2")
        image_btn.pack(side="left", padx=(6, 4))
        image_btn.bind("<Button-1>", lambda ev: pick_image())
        clear_btn = tk.Label(image_row, text="清除", bg=P.bg, fg=P.fg_faint,
                             font=self.f_small, padx=4, pady=2, cursor="hand2")
        clear_btn.pack(side="left")
        clear_btn.bind("<Button-1>", lambda ev: clear_image())
        reset_btn = tk.Label(image_row, text="重置", bg=P.bg, fg=P.fg_faint,
                             font=self.f_small, padx=4, pady=2, cursor="hand2")
        reset_btn.pack(side="left")
        reset_btn.bind("<Button-1>", lambda ev: reset_view())

        # 列表区怎么衬: 磨砂膜 / 纯色 / 不铺
        tk.Frame(image_frame, bg=P.border, height=1).pack(fill="x", pady=(6, 8))
        tk.Label(image_frame, text="列表底图", bg=P.bg, fg=P.fg_dim,
                 font=self.f_small, anchor="w").pack(anchor="w")
        scrim_row = tk.Frame(image_frame, bg=P.bg)
        scrim_row.pack(fill="x", pady=(6, 0))
        scrim_chips = {}
        for key, label in (("frost", "磨砂"), ("solid", "纯色"),
                           ("off", "不铺")):
            chip = tk.Label(scrim_row, text=label, bg=P.bg_alt, fg=P.fg_dim,
                            font=self.f_small, padx=12, pady=5, cursor="hand2")
            chip.pack(side="left", padx=(0, 8))
            chip.bind("<Button-1>", lambda ev, k=key: set_scrim(k))
            scrim_chips[key] = chip

        # 预览对所有模式都显示: 纯色/渐变也能先看效果
        preview_frame = section(form, "预览", wrap=210)
        preview_card = preview_frame.box
        preview = tk.Canvas(preview_frame, width=pw, height=ph, bg=P.bg_alt,
                            highlightthickness=1, highlightbackground=P.border,
                            cursor="fleur")
        preview.pack(anchor="w")
        preview_hint = tk.Label(preview_frame, text="", bg=P.bg, fg=P.fg_faint,
                                font=self.f_small, anchor="w")
        preview_hint.pack(fill="x", pady=(4, 0))

        zoom_row = row(image_frame, "缩放", width=6)
        zoom_scale = tk.Scale(zoom_row, from_=100, to=250, resolution=5,
                              orient="horizontal", bg=P.bg, fg=P.fg_dim,
                              troughcolor=P.bg_alt, highlightthickness=1,
                              highlightbackground=P.border, bd=0,
                              sliderrelief="flat", showvalue=False, length=200,
                              command=lambda v: set_zoom(v))
        zoom_scale.pack(side="left")
        zoom_value = tk.Label(zoom_row, text="{}%".format(int(state["zoom"] * 100)),
                              bg=P.bg, fg=P.fg_faint, font=self.f_small)
        zoom_value.pack(side="left", padx=8)

        alpha_row = row(image_frame, "透明度", width=6)
        alpha_scale = tk.Scale(alpha_row, from_=0, to=60, resolution=5,
                               orient="horizontal", bg=P.bg, fg=P.fg_dim,
                               troughcolor=P.bg_alt, highlightthickness=1,
                               highlightbackground=P.border, bd=0,
                               sliderrelief="flat", showvalue=False, length=200,
                               command=lambda v: set_alpha(v))
        alpha_scale.pack(side="left")
        alpha_value = tk.Label(alpha_row,
                               text="{}%".format(int(state["alpha"] * 100)),
                               bg=P.bg, fg=P.fg_faint, font=self.f_small)
        alpha_value.pack(side="left", padx=8)

        def auto_bg():
            """自动文字色按哪个底色推: 图片按平均色, 渐变按中间色"""
            if state.get("mode") == "gradient":
                return mix_color(state["grad_start"], state["grad_end"], 0.5)
            if (state.get("mode") != "image" or not state.get("image")
                    or Image is None):
                return state["bg"]
            image = state.get("_pil")
            if image is None:
                try:
                    path = state["image"]
                    if not os.path.isabs(path):
                        path = os.path.join(DATA_DIR, path.replace("/", os.sep))
                    image = Image.open(path).convert("RGB")
                    image.thumbnail((1600, 1600), Image.LANCZOS)
                    state["_pil"] = image
                except Exception:
                    return state["bg"]
            pixel = image.resize((1, 1), Image.BILINEAR).getpixel((0, 0))
            return "#{:02x}{:02x}{:02x}".format(*pixel[:3])

        def suggest_fg():
            """按当前背景推一个文字颜色"""
            return auto_text_color(auto_bg())

        def refresh_fg_swatch():
            """背景变了: 自动色的小样跟着更新"""
            fg_swatch.configure(bg=state["fg"] or suggest_fg())

        accent_box = section(page_color, "强调色",
                             "勾选框、进度条、选中项跟着它变")
        accent_row = row(accent_box, "颜色")
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
        dropper(accent_row, lambda c: apply_accent(c))

        # ---- 外观页: 边框 ----
        border_box = section(page_look, "边框",
                             "外圈那一条: 无 / 单色 / 渐变, 粗细和圆角都能调")
        border_row = tk.Frame(border_box, bg=P.bg)
        border_row.pack(fill="x")
        border_chips = {}
        for key, label in (("none", "无"), ("solid", "单色"),
                           ("gradient", "渐变")):
            chip = tk.Label(border_row, text=label, bg=P.bg_alt,
                            fg=P.fg_dim, font=self.f_small, padx=12, pady=5,
                            cursor="hand2")
            chip.pack(side="left", padx=(0, 8))
            chip.bind("<Button-1>", lambda ev, k=key: set_border_mode(k))
            border_chips[key] = chip

        width_row = tk.Frame(border_box, bg=P.bg)
        width_row.pack(fill="x", pady=(8, 0))
        tk.Label(width_row, text="粗细", bg=P.bg, fg=P.fg_dim,
                 font=self.f_small, width=6, anchor="w").pack(side="left")
        border_scale = tk.Scale(width_row, from_=1, to=6, resolution=1,
                                orient="horizontal", bg=P.bg, fg=P.fg_dim,
                                troughcolor=P.bg_alt, highlightthickness=1,
                                highlightbackground=P.border,
                                bd=0, sliderrelief="flat", showvalue=False,
                                length=130,
                                command=lambda v: set_border_width(v))
        border_scale.pack(side="left")
        tk.Label(width_row, text="px", bg=P.bg, fg=P.fg_faint,
                 font=self.f_small).pack(side="left", padx=6)

        radius_row = tk.Frame(border_box, bg=P.bg)
        radius_row.pack(fill="x", pady=(6, 0))
        tk.Label(radius_row, text="圆角", bg=P.bg, fg=P.fg_dim,
                 font=self.f_small, width=6, anchor="w").pack(side="left")
        radius_scale = tk.Scale(radius_row, from_=0, to=14, resolution=1,
                                orient="horizontal", bg=P.bg, fg=P.fg_dim,
                                troughcolor=P.bg_alt, highlightthickness=1,
                                highlightbackground=P.border, bd=0,
                                sliderrelief="flat", showvalue=False,
                                length=130,
                                command=lambda v: set_radius(v))
        radius_scale.pack(side="left")
        radius_value = tk.Label(radius_row, text="自动", bg=P.bg,
                                fg=P.fg_faint, font=self.f_small, width=4,
                                anchor="w")
        radius_value.pack(side="left", padx=6)

        color_row = tk.Frame(border_box, bg=P.bg)
        color_row.pack(fill="x", pady=(6, 0))
        tk.Label(color_row, text="颜色", bg=P.bg, fg=P.fg_dim,
                 font=self.f_small, width=6, anchor="w").pack(side="left")
        border_swatch = tk.Frame(color_row, bg=state["border_color"], width=36,
                                 height=22, highlightthickness=1,
                                 highlightbackground=P.border, cursor="hand2")
        border_swatch.pack(side="left")
        border_swatch.pack_propagate(False)
        border_swatch.bind("<Button-1>", lambda ev: pick_border(1))
        border_swatch2 = tk.Frame(color_row, bg=state["border_color2"],
                                  width=36, height=22, highlightthickness=1,
                                  highlightbackground=P.border, cursor="hand2")
        border_swatch2.pack(side="left", padx=(6, 0))
        border_swatch2.pack_propagate(False)
        border_swatch2.bind("<Button-1>", lambda ev: pick_border(2))
        dropper(color_row, lambda c: apply_border_color(c))

        # ---- 外观页: 顶栏 / 底栏 ----
        bars_box = section(page_look, "顶栏 / 底栏",
                           "勾上「单独上色」就不再透出底图")
        bar_rows = {}
        for key, label in (("header", "顶栏"), ("footer", "底栏")):
            line = tk.Frame(bars_box, bg=P.bg)
            line.pack(fill="x", pady=(0, 6))
            tk.Label(line, text=label, bg=P.bg, fg=P.fg_dim,
                     font=self.f_small, width=6, anchor="w").pack(side="left")
            swatch = tk.Frame(line, bg=state[key + "_color"], width=36,
                              height=22, highlightthickness=1,
                              highlightbackground=P.border, cursor="hand2")
            swatch.pack(side="left")
            swatch.pack_propagate(False)
            swatch.bind("<Button-1>", lambda ev, k=key: pick_bar(k))
            chip = tk.Label(line, text="单独上色", bg=P.bg_alt, fg=P.fg_dim,
                            font=self.f_small, padx=10, pady=4, cursor="hand2")
            chip.pack(side="left", padx=(10, 0))
            chip.bind("<Button-1>", lambda ev, k=key: toggle_split(k))
            dropper(line, lambda c, k=key: apply_bar_color(k, c))
            bar_rows[key] = (swatch, chip)

        # ---- 字体页 ----
        font_box = section(page_font, "字体",
                           "中文和西文可以分开选；列表按字符自动用对应字体")
        default_label = "（默认）"
        try:
            tk_fonts = sorted(tkfont.families(win))
        except Exception:
            tk_fonts = list(fonts.registry_families())
        cn_values = [default_label] + fonts.cjk_families(tk_fonts)
        latin_values = [default_label] + [name for name in tk_fonts
                                          if not name.startswith("@")]
        for key, label, values in (("font_cn", "中文", cn_values),
                                   ("font_latin", "西文", latin_values)):
            line = tk.Frame(font_box, bg=P.bg)
            line.pack(fill="x", pady=(0, 6))
            tk.Label(line, text=label, bg=P.bg, fg=P.fg_dim,
                     font=self.f_small, width=6, anchor="w").pack(side="left")
            combo = ttk.Combobox(line, values=values, state="readonly",
                                 width=18, font=self.f_small)
            current = state.get(key) or default_label
            combo.set(current if current in values else default_label)
            combo.pack(side="left", fill="x", expand=True)
            combo.bind("<<ComboboxSelected>>",
                       lambda ev, k=key, b=combo: set_font(k, b))

        fg_box = section(page_font, "文字颜色",
                         "选完背景点「自动推荐」，按底色配一个")
        fg_row = row(fg_box, "文字色")
        fg_swatch = tk.Frame(fg_row, bg=state["fg"] or auto_text_color(auto_bg()),
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
        fg_suggest = tk.Label(fg_row, text="自动推荐", bg=P.bg, fg=P.fg_faint,
                              font=self.f_small, padx=6, pady=2,
                              cursor="hand2")
        fg_suggest.pack(side="left")
        fg_suggest.bind("<Button-1>", lambda ev: apply_fg(suggest_fg()))
        fg_suggest.bind("<Enter>",
                        lambda ev, w=fg_suggest: w.configure(fg=P.fg))
        fg_suggest.bind("<Leave>",
                        lambda ev, w=fg_suggest: w.configure(fg=P.fg_faint))
        dropper(fg_row, lambda c: apply_fg(c))
        fg_row.pack(fill="x")

        def set_font(key, box):
            """下拉选完字体: 存进草稿并刷新小样

            :param key: font_cn / font_latin
            :param box: 下拉框
            """
            value = box.get()
            state[key] = "" if value == default_label else value
            refresh_preview()

        def mock_font(kind, size, bold=False):
            """小样里按选中的字体画

            :param kind: "cn" 或 "latin"
            :param size: 像素大小
            :param bold: 是否粗体
            """
            family = state.get("font_cn" if kind == "cn" else "font_latin") or ""
            if family:
                font = fonts.load(family, size, bold)
                if font is not None:
                    return font
            return preview_font(size, bold)

        def pick_bg():
            _, picked = colorchooser.askcolor(color=state["bg"], parent=win,
                                              title="选择底色")
            if picked:
                state["bg"] = picked
                bg_swatch.configure(bg=picked)
                refresh_fg_swatch()
                refresh_preview()

        def pick_fg():
            _, picked = colorchooser.askcolor(
                color=state["fg"] or auto_text_color(auto_bg()), parent=win,
                title="选择文字颜色")
            if picked:
                state["fg"] = picked
                fg_swatch.configure(bg=picked)
                refresh_preview()

        def reset_fg():
            state["fg"] = ""
            fg_swatch.configure(bg=auto_text_color(auto_bg()))
            refresh_preview()

        def pick_accent():
            _, picked = colorchooser.askcolor(color=state["accent"], parent=win,
                                              title="选择强调色")
            if picked:
                state["accent"] = picked
                accent_swatch.configure(bg=picked)
                refresh_preview()

        def pick_grad(which):
            """渐变模式选起始色 / 结束色"""
            key = "grad_start" if which == "start" else "grad_end"
            swatch = start_swatch if which == "start" else end_swatch
            _, picked = colorchooser.askcolor(color=state[key], parent=win,
                                              title="选择渐变颜色")
            if picked:
                state[key] = picked
                swatch.configure(bg=picked)
                refresh_fg_swatch()
                refresh_preview()

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
            full = os.path.join(DATA_DIR, path.replace("/", os.sep))
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
            refresh_fg_swatch()
            render_preview()

        def clear_image():
            state["image"] = ""
            state["_pil"] = None
            image_label.config(text="没有")
            refresh_fg_swatch()
            render_preview()

        def apply_fg(color):
            """吸管取到的文字色"""
            state["fg"] = color
            fg_swatch.configure(bg=color)
            refresh_preview()

        def apply_accent(color):
            """吸管取到的强调色"""
            state["accent"] = color
            accent_swatch.configure(bg=color)
            refresh_preview()

        def apply_border_color(color):
            """吸管取到的边框色(先用主色)"""
            state["border_color"] = color
            border_swatch.configure(bg=color)
            refresh_preview()

        def apply_bar_color(key, color):
            """吸管取到的顶栏/底栏颜色"""
            state[key + "_color"] = color
            bar_rows[key][0].configure(bg=color)
            refresh_preview()

        def set_scrim(key):
            """列表底图三档"""
            state["scrim_mode"] = key
            for chip_key, chip in scrim_chips.items():
                chosen = (chip_key == key)
                chip.configure(bg=P.accent if chosen else P.bg_alt,
                               fg=best_text_color(P.accent) if chosen
                               else P.fg_dim)
            refresh_preview()

        def set_border_mode(key):
            """边框三选一"""
            state["border_mode"] = key
            for chip_key, chip in border_chips.items():
                chosen = (chip_key == key)
                chip.configure(bg=P.accent if chosen else P.bg_alt,
                               fg=best_text_color(P.accent) if chosen
                               else P.fg_dim)
            refresh_preview()

        def set_radius(value):
            """圆角大小; 0 = 自动(有边框时跟随粗细)"""
            try:
                radius = max(0, min(14, int(float(value))))
            except Exception:
                return
            state["radius"] = radius
            radius_value.config(text="自动" if radius == 0 else "{}px".format(radius))
            refresh_preview()

        def set_border_width(value):
            """拖边框粗细"""
            try:
                state["border_width"] = max(1, min(6, int(float(value))))
            except Exception:
                pass
            refresh_preview()

        def pick_border(which):
            """选边框颜色; which=1 主色, 2 渐变的第二个色"""
            field = "border_color" if which == 1 else "border_color2"
            _, picked = colorchooser.askcolor(color=state[field], parent=win,
                                              title="选择边框颜色")
            if not picked:
                return
            state[field] = picked
            if which == 1:
                border_swatch.configure(bg=picked)
            else:
                border_swatch2.configure(bg=picked)
            refresh_preview()

        def paint_split(key):
            """刷新"单独上色"按钮的选中态"""
            chip = bar_rows[key][1]
            chosen = bool(state[key + "_split"])
            chip.configure(bg=P.accent if chosen else P.bg_alt,
                           fg=best_text_color(P.accent) if chosen else P.fg_dim)

        def toggle_split(key):
            """顶栏 / 底栏 是否单独上色"""
            state[key + "_split"] = not bool(state[key + "_split"])
            paint_split(key)
            refresh_preview()

        def pick_bar(key):
            """选顶栏 / 底栏的颜色"""
            field = key + "_color"
            _, picked = colorchooser.askcolor(color=state[field], parent=win,
                                              title="选择颜色")
            if not picked:
                return
            state[field] = picked
            bar_rows[key][0].configure(bg=picked)
            refresh_preview()

        def update_hint_text():
            """预览下面的小提示, 跟着模式变"""
            if state.get("mode") == "image":
                text = "拖动挪位置 · 滚轮缩放 · 比例与实际窗口一致"
            elif state.get("mode") == "gradient":
                text = "示意图: 渐变底 + 列表底图 + 边框 + 示例行"
            else:
                text = "示意图: 纯色底 + 列表底图 + 边框 + 示例行"
            try:
                preview_hint.config(text=text)
            except Exception:
                pass

        def set_mode(key):
            state["mode"] = key
            for chip_key, chip in mode_chips.items():
                chosen = (chip_key == key)
                chip.configure(bg=P.accent if chosen else P.bg_alt,
                               fg=best_text_color(P.accent) if chosen else P.fg_dim)
            solid_frame.pack_forget()
            gradient_frame.pack_forget()
            image_card.pack_forget()
            if key == "image":
                image_card.pack(fill="x", before=preview_card)
            elif key == "gradient":
                gradient_frame.pack(fill="x")
            else:
                solid_frame.pack(fill="x")
            update_hint_text()
            refresh_fg_swatch()
            render_preview()
            resize_window()

        def show_page(name):
            """切换右栏页签

            :param name: "color" 或 "look"
            """
            page_color.pack_forget()
            page_look.pack_forget()
            page_font.pack_forget()
            target = {"look": page_look, "font": page_font}.get(name,
                                                               page_color)
            target.pack(fill="both", expand=True)
            for key, chip in tab_chips.items():
                chosen = (key == name)
                chip.configure(bg=P.accent if chosen else P.bg_alt,
                               fg=best_text_color(P.accent) if chosen
                               else P.fg_dim)
            win.after_idle(fit_height)

        def fit_height():
            """按内容实际需要多高就摆多高

            各模式的内容长度不一样(图片模式多了预览/缩放/透明度),
            写死高度不是切掉内容就是留一大片空白。
            """
            try:
                win.update_idletasks()
                need = body.winfo_reqheight()
            except Exception:
                return
            limit = max(420, win.winfo_screenheight() - 120)
            height = max(380, min(need, limit))
            try:
                x = win.winfo_x()
                y = win.winfo_y()
                if y + height > win.winfo_screenheight() - 40:
                    y = max(20, win.winfo_screenheight() - height - 40)
                win.geometry("{}x{}+{}+{}".format(710, height, x, y))
                win.after(20, lambda w=win: round_corners(w, 12))
            except Exception:
                pass

        def resize_window(height=None):
            """切模式后重新量一次高度(参数保留只是兼容旧调用)"""
            win.after_idle(fit_height)

        def set_zoom(value):
            state["zoom"] = max(1.0, min(2.5, float(value) / 100.0))
            zoom_value.config(text="{}%".format(int(round(state["zoom"] * 100))))
            render_preview()

        def set_alpha(value):
            state["alpha"] = max(0.0, min(0.6, float(value) / 100.0))
            refresh_preview()
            alpha_value.config(
                text="{}%".format(int(round(state["alpha"] * 100))))

        def reset_view():
            state["offset"] = [0.0, 0.0]
            state["zoom"] = 1.0
            zoom_scale.set(100)
            render_preview()

        def preview_wheel(ev):
            if state.get("mode") != "image":
                return "break"
            step = 5 if ev.delta > 0 else -5
            value = max(100, min(250, int(round(state["zoom"] * 100)) + step))
            zoom_scale.set(value)
            return "break"

        preview_job = {"id": None}
        font_dir = "C:/Windows/Fonts/"

        def preview_font(size, bold=False):
            """挑一个能给 PIL 用的雅黑, 拿不到就返回 None"""
            if ImageFont is None:
                return None
            names = ("msyhbd.ttc", "msyh.ttc") if bold else ("msyh.ttc",)
            for name in names:
                try:
                    return ImageFont.truetype(font_dir + name, size, index=1)
                except Exception:
                    continue
            return None

        def draw_mock(mock):
            """在小样上补上顶栏/底栏/列表底图/边框/示例行

            :param mock: 已经画好底色的图(RGB)
            """
            from PIL import ImageDraw
            draw = ImageDraw.Draw(mock, "RGBA")
            w, h = mock.size
            # 图片模式下"底色"其实是图上的平均色, 算一次给面板/分组条用
            base_color = auto_bg()
            head_h = max(12, int(round(h * 0.085)))
            tab_h = max(10, int(round(h * 0.07)))
            foot_h = max(10, int(round(h * 0.075)))
            body_top = head_h + tab_h
            body_bottom = h - foot_h
            panel = mix_color(base_color, "#000000", 0.05)
            # 列表底图
            if state["scrim_mode"] == "solid":
                draw.rectangle([0, head_h, w, body_bottom], fill=panel)
            elif state["scrim_mode"] == "frost":
                box = (0, head_h, w, body_bottom)
                region = mock.crop(box)
                small = region.resize((max(2, w // 6), max(2, (body_bottom - head_h) // 6)),
                                      Image.BILINEAR)
                small = small.filter(ImageFilter.GaussianBlur(1.6))
                frost = small.resize(region.size, Image.BILINEAR)
                frost = Image.blend(frost, Image.new("RGB", region.size, panel), 0.3)
                mock.paste(frost, box[:2])
                draw = ImageDraw.Draw(mock, "RGBA")
            # 顶栏 / 底栏
            if state["header_split"]:
                draw.rectangle([0, 0, w, head_h], fill=state["header_color"])
            if state["footer_split"]:
                draw.rectangle([0, body_bottom, w, h], fill=state["footer_color"])
            # 示例行
            fg = state["fg"] or auto_text_color(auto_bg())
            small_font = mock_font("cn", 9)
            tiny_font = mock_font("cn", 8)
            y = body_top + 4
            row_h = max(11, int(round(h * 0.055)))
            draw.rectangle([2, y, w - 2, y + row_h - 2],
                           fill=mix_color(base_color, fg, 0.10))
            if small_font is not None:
                draw.text((6, y + 1), "开始使用 · 0/3", font=small_font, fill=fg)
            for i, label in enumerate(("点左边的框勾选", "双击任务写便签")):
                y += row_h
                box = [6, y + 2, 14, y + 10]
                draw.rounded_rectangle(box, radius=2, outline=fg, width=1)
                if small_font is not None:
                    draw.text((18, y), label, font=small_font, fill=fg)
            # 页签
            if tiny_font is not None:
                draw.text((8, head_h + 3), "未完成", font=tiny_font,
                          fill=state["accent"])
                draw.text((int(w * 0.38), head_h + 3), "已完成",
                          font=tiny_font, fill=mix_color(fg, state["bg"], 0.4))
            # 边框: 直接借用真实那套画法, 按缩放比例把粗细/圆角也一起缩
            if state["border_mode"] != "none":
                try:
                    ratio = float(w) / float(max(1, self.root.winfo_width()))
                except Exception:
                    ratio = 1.0
                ratio = max(0.3, min(1.0, ratio))
                thick = max(1, int(round(state["border_width"] * ratio)))
                custom_radius = int(state.get("radius") or 0)
                keep = (self.border_mode, self.border_width,
                        self.border_color, self.border_color2, self.radius)
                self.border_mode = state["border_mode"]
                self.border_width = thick
                self.border_color = state["border_color"]
                self.border_color2 = state["border_color2"]
                self.radius = int(round((custom_radius or
                                         state["border_width"]) * ratio))
                try:
                    mock = self.apply_border(mock, None, scale=ratio)
                except Exception:
                    pass
                finally:
                    (self.border_mode, self.border_width,
                     self.border_color, self.border_color2,
                     self.radius) = keep
            return mock

        def render_preview():
            """按当前设置画一张小样(底图 + 顶底栏 + 列表底图 + 边框 + 示例行)"""
            preview.delete("all")
            if Image is None:
                return
            mock = None
            state["_span"] = (0, 0)
            if state["mode"] == "image" and state["image"]:
                path = image_path()
                if path:
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
                        mock = scaled.crop((left, top, left + pw, top + ph))
                        state["_span"] = (span_x, span_y)
                    except Exception:
                        mock = None
            if mock is None:
                if state["mode"] == "gradient":
                    mock = self.gradient_image(
                        {"grad_start": state["grad_start"],
                         "grad_end": state["grad_end"],
                         "grad_angle": state["grad_angle"]}, pw, ph)
                else:
                    mock = Image.new("RGB", (pw, ph), state["bg"])
            else:
                mock = mock.copy()
            mock = draw_mock(mock)
            photo = ImageTk.PhotoImage(mock)
            preview.create_image(0, 0, anchor="nw", image=photo)
            preview.image = photo

        def refresh_preview():
            """改一下看一次: 攒 90ms 再画, 别拖滑块时一直重画"""
            if preview_job["id"] is not None:
                try:
                    win.after_cancel(preview_job["id"])
                except Exception:
                    pass
            preview_job["id"] = win.after(90, run_preview)

        def run_preview():
            preview_job["id"] = None
            render_preview()

        preview_drag = {}

        def preview_press(ev):
            preview_drag["x"] = ev.x
            preview_drag["y"] = ev.y

        def preview_move(ev):
            if state.get("mode") != "image":
                return
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
        show_page("color")
        set_scrim(state["scrim_mode"])
        set_border_mode(state["border_mode"])
        border_scale.set(int(state["border_width"]))
        radius_scale.set(int(state.get("radius") or 0))
        paint_split("header")
        paint_split("footer")
        set_mode(state["mode"])
        render_preview()

        width, height = 710, 620
        base = self.settings_win or self.root
        x = base.winfo_rootx() + (base.winfo_width() - width) // 2
        y = base.winfo_rooty() + (base.winfo_height() - height) // 2
        left, top, right, bottom = self.settings_bounds()
        x = max(left + 8, min(x, right - width - 8))
        y = max(top + 8, min(y, bottom - height - 8))
        win.geometry("{}x{}+{}+{}".format(width, height, x, y))
        win.deiconify()
        win.after(20, lambda w=win: round_corners(w, 12))
        win.after(30, fit_height)
        win.lift()
        win.focus_force()
        if not editing:
            # 新建时名字默认是"我的配色 N", 直接进编辑态方便改
            start_rename()
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
                     alpha=round(float(state.get("alpha") or 0.0), 3),
                     font_cn=state.get("font_cn") or "",
                     font_latin=state.get("font_latin") or "",
                     scrim=state.get("scrim_mode") or "frost",
                     radius=int(state.get("radius") or 0),
                     border=dict(mode=state.get("border_mode") or "none",
                                 width=int(state.get("border_width") or 2),
                                 color=state.get("border_color") or "#3b7cf6",
                                 color2=state.get("border_color2") or "#8a5cf6"),
                     header_split=bool(state.get("header_split")),
                     header_color=state.get("header_color") or "#17181d",
                     footer_split=bool(state.get("footer_split")),
                     footer_color=state.get("footer_color") or "#17181d")
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
        state = self.settings_state()
        self.close_settings()
        self.reload_ui()
        self.open_settings(**state)

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
        """总在最前 / 窗口大小"""
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


        holder = self.settings_block(
            panel, "数据位置",
            "任务、配色、便签图片都放在这个文件夹；换电脑或备份拷它就行")
        tk.Label(holder, text=paths.DATA_DIR, bg=P.bg, fg=P.fg_dim,
                 font=self.f_small, justify="left", wraplength=360,
                 anchor="w").pack(fill="x")
        data_row = tk.Frame(holder, bg=P.bg)
        data_row.pack(fill="x", pady=(8, 0))
        open_btn = tk.Label(data_row, text="打开目录", bg=P.bg_alt, fg=P.fg_dim,
                            font=self.f_small, padx=12, pady=5, cursor="hand2")
        open_btn.pack(side="left", padx=(0, 8))
        open_btn.bind("<Button-1>", lambda ev: self.open_data_folder())
        change_btn = tk.Label(data_row, text="更改…", bg=P.bg_alt, fg=P.fg_dim,
                              font=self.f_small, padx=12, pady=5, cursor="hand2")
        change_btn.pack(side="left")
        change_btn.bind("<Button-1>", lambda ev: self.change_data_folder())

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

    def open_data_folder(self):
        """打开数据目录"""
        if paths.open_data_dir():
            return
        messagebox.showerror("打开目录", "没打开成功，路径是：\n" + paths.DATA_DIR,
                             parent=self.settings_win)

    def change_data_folder(self):
        """改数据目录: 复制一份过去, 然后重启"""
        target = filedialog.askdirectory(
            parent=self.settings_win, title="选择数据存放目录",
            mustexist=False)
        if not target:
            return
        target = os.path.normpath(target)
        if target == os.path.normpath(paths.DATA_DIR):
            return
        if not paths.switch_data_dir(target):
            messagebox.showerror("数据位置", "这个目录没法写入：\n" + target,
                                 parent=self.settings_win)
            return
        messagebox.showinfo(
            "数据位置",
            "已经复制到：\n{}\n\n马上重启，之后就从新位置读写。\n"
            "原来的文件没删，确认没问题可以自己删掉。".format(target),
            parent=self.settings_win)
        self.restart_app()

    def restart_app(self):
        """重启自己(先拉起新进程, 再退掉旧的)"""
        try:
            self.save_conf()
        except Exception:
            pass
        target = updater.exe_path()
        if target is None:
            messagebox.showinfo("重启", "源码运行时请手动重启。",
                                parent=self.settings_win)
            return
        flags = getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
        flags |= getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        command = 'ping -n 4 127.0.0.1 >nul & start "" "{}"'.format(target)
        try:
            subprocess.Popen(command, shell=True, creationflags=flags,
                             stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        except Exception as exc:
            messagebox.showerror("重启", "重启失败：{}".format(exc),
                                 parent=self.settings_win)
            return
        self.quit()

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
        # 重建会按"上次保存的几何"重新摆窗口, 不先把当前位置存下来的话
        # 窗口会跳回之前的位置(用户刚拖到别处就会看到它自己跑回去)
        self.save_geom()
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
