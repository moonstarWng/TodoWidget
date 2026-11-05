# -*- coding: utf-8 -*-
"""设置窗口: 主题色块、自定义强调色"""

import tkinter as tk
from tkinter import colorchooser

from .theme import P, THEMES, THEME_NAMES, set_theme
from .utils import make_icon

class SettingsMixin:
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
        win.configure(bg=P.border)
        self.settings_win = win

        body = tk.Frame(win, bg=P.bg)
        body.pack(fill="both", expand=True, padx=1, pady=1)

        head = tk.Frame(body, bg=P.head, height=30)
        head.pack(fill="x")
        head.pack_propagate(False)
        tk.Label(head, text="设置", bg=P.head, fg=P.fg,
                 font=self.f_small).pack(side="left", padx=10)
        close = tk.Label(head, text="\u2715", bg=P.head, fg=P.fg_dim,
                         font=self.f_small, width=2, cursor="hand2")
        close.pack(side="right", padx=4)
        close.bind("<Button-1>", lambda ev: self.close_settings())

        tk.Label(body, text="配色", bg=P.bg, fg=P.fg_dim,
                 font=self.f_small).pack(anchor="w", padx=12, pady=(10, 4))

        chips = tk.Frame(body, bg=P.bg)
        chips.pack(fill="x", padx=12)
        for key, label in THEME_NAMES:
            self.make_theme_chip(chips, key, label)

        accent_row = tk.Frame(body, bg=P.bg, cursor="hand2")
        accent_row.pack(fill="x", padx=12, pady=(14, 10))
        tk.Label(accent_row, text="强调色", bg=P.bg, fg=P.fg_dim,
                 font=self.f_small).pack(side="left")
        swatch = tk.Frame(accent_row, bg=P.accent, width=26, height=16,
                          highlightthickness=1,
                          highlightbackground=P.border)
        swatch.pack(side="left", padx=8)
        swatch.pack_propagate(False)
        tk.Label(accent_row, text="点这里自定义", bg=P.bg, fg=P.fg_faint,
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

        cell = tk.Frame(parent, bg=P.bg, cursor="hand2")
        cell.pack(side="left", padx=(0, 12))

        border = P.fg if chosen else P.border
        swatch = tk.Frame(cell, bg=theme["accent"], width=30, height=20,
                          highlightthickness=1 if not chosen else 2,
                          highlightbackground=border)
        swatch.pack()
        swatch.pack_propagate(False)

        name_color = P.fg if chosen else P.fg_dim
        name = tk.Label(cell, text=label, bg=P.bg, fg=name_color,
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
        rgb, picked = colorchooser.askcolor(color=P.accent, parent=self.root,
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
