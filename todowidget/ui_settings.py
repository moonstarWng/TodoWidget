# -*- coding: utf-8 -*-
"""设置窗口: 左边分类、右边选项, 外加检查更新"""

import ctypes
import os
import queue
import threading
import tkinter as tk
from tkinter import colorchooser, messagebox

from . import updater
from .paths import APP_DIR
from .theme import (P, TEXTURE_NAMES, THEMES, THEME_NAMES, best_text_color,
                    set_theme)
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
        pane = tk.Frame(content, bg=P.bg)
        pane.pack(side="left", fill="both", expand=True)
        self._settings_pane = pane

        for key, label in SETTINGS_TABS:
            self.make_settings_tab(side, key, label)

        builder = {"look": self.build_look_panel,
                   "sort": self.build_sort_panel,
                   "window": self.build_window_panel,
                   "about": self.build_about_panel}
        for key, _label in SETTINGS_TABS:
            panel = tk.Frame(pane, bg=P.bg)
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
        """配色 / 强调色 / 质感"""
        holder = self.settings_block(panel, "配色", "整套界面的颜色")
        for key, label in THEME_NAMES:
            self.make_theme_chip(holder, key, label)

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

        holder = self.settings_block(panel, "质感", "窗口的底子材质")
        for key, label in TEXTURE_NAMES:
            self.settings_chip(holder, label, key == self.texture,
                               lambda k=key: self.set_texture(k),
                               group="texture", value=key)
        self.settings_note(panel, "磨砂要 Win10 1803 以上，系统不支持会自动退回纯色。")

    def make_theme_chip(self, parent, key, label):
        """配色色块 + 名字"""
        theme = THEMES[key]
        chosen = (key == self.theme)
        cell = tk.Frame(parent, bg=P.bg, cursor="hand2")
        cell.pack(side="left", padx=(0, 16))
        border = P.fg if chosen else P.border
        swatch = tk.Frame(cell, bg=theme["accent"], width=38, height=24,
                          highlightthickness=2 if chosen else 1,
                          highlightbackground=border)
        swatch.pack()
        swatch.pack_propagate(False)
        name = tk.Label(cell, text=label, bg=P.bg,
                        fg=P.fg if chosen else P.fg_dim, font=self.f_small)
        name.pack(pady=(4, 0))
        for widget in (cell, swatch, name):
            widget.bind("<Button-1>", lambda ev, k=key: self.choose_theme(k))

    def choose_theme(self, key):
        """换配色(整块界面重建)"""
        if key == self.theme:
            return
        pos = self.settings_pos()
        self.close_settings()
        self.theme = key
        self.accent = None
        set_theme(key, None)
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
        set_theme(self.theme, picked)
        self.save_conf()
        self.reload_ui()
        self.open_settings(pos)

    def set_texture(self, key):
        """换质感(整块界面重建)"""
        if key == self.texture:
            return
        pos = self.settings_pos()
        self.close_settings()
        self.texture = key
        self.save_conf()
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
