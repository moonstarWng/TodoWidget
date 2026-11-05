# -*- coding: utf-8 -*-
"""便签窗口: Markdown 预览、自动续列表、超链接识别"""

import ctypes
import re
import time

import tkinter as tk

from . import theme as T
from .theme import P
from .utils import MonitorInfo, open_url

LINK_RE = re.compile(r"(?:https?://|www\.)[^\s<>\"'\u3000]+")
LINK_TAIL = ".,;:!?)]}\u3002\uff0c\u3001\uff09\u300b"

class NoteMixin:
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
        win.configure(bg=P.note_edge)
        self.note_win = win

        body = tk.Frame(win, bg=P.note_bg)
        body.pack(fill="both", expand=True, padx=1, pady=1)

        strip = tk.Frame(body, bg=P.accent, height=3)
        strip.pack(fill="x", side="top")

        head = tk.Frame(body, bg=P.note_head, height=32)
        head.pack(fill="x", side="top")
        head.pack_propagate(False)

        title_text = item["text"] or "(未命名)"
        if len(title_text) > 14:
            title_text = title_text[:13] + "\u2026"
        title = tk.Label(head, text="\u270e  " + title_text, bg=P.note_head,
                         fg=P.note_fg, font=self.f_small, anchor="w")
        title.pack(side="left", padx=10)

        close_btn = tk.Label(head, text="\u2715", bg=P.note_head, fg=P.note_dim,
                             font=self.f_item, width=2, cursor="hand2")
        close_btn.pack(side="right", padx=4)
        close_btn.bind("<Button-1>", lambda ev: self.close_note())
        close_btn.bind("<Enter>", lambda ev: close_btn.configure(fg=P.note_fg))
        close_btn.bind("<Leave>", lambda ev: close_btn.configure(fg=P.note_dim))

        self.btn_note_mode = tk.Label(head, text="\u9884\u89c8", bg=P.note_head,
                                      fg=P.note_dim, font=self.f_small,
                                      cursor="hand2", padx=6)
        self.btn_note_mode.pack(side="right")
        self.btn_note_mode.bind("<Button-1>", lambda ev: self.note_toggle_mode())
        self.btn_note_mode.bind("<Enter>",
                                lambda ev: self.btn_note_mode.configure(fg=P.note_fg))
        self.btn_note_mode.bind("<Leave>",
                                lambda ev: self.btn_note_mode.configure(fg=P.note_dim))

        hint = tk.Label(body, text="# 标题 · - 列表 · 1. 编号 · **加粗** · 网址可点",
                        bg=P.note_bg, fg=P.note_dim, font=self.f_small, anchor="w")
        hint.pack(fill="x", side="bottom", padx=12, pady=(0, 6))

        text = tk.Text(body, bg=P.note_bg, fg=P.note_fg, insertbackground=P.accent,
                       relief="flat", bd=0, highlightthickness=0, wrap="word",
                       font=self.f_item, padx=12, pady=10, undo=True,
                       selectbackground="#e6d7a8", selectforeground=P.note_fg)
        text.pack(fill="both", expand=True)
        self.note_text = text

        text.tag_configure("h1", font=self.f_note_h1, foreground=P.note_fg,
                           spacing1=8, spacing3=4)
        text.tag_configure("h2", font=self.f_note_h2, foreground=P.note_fg,
                           spacing1=6, spacing3=2)
        text.tag_configure("li", lmargin1=16, lmargin2=30)
        text.tag_configure("mark", foreground=P.note_mark)
        text.tag_configure("quote", lmargin1=16, lmargin2=16, foreground=P.note_dim)
        text.tag_configure("bold", font=self.f_note_bold)
        text.tag_configure("code", background=P.note_code, foreground="#7a5c1f")
        text.tag_configure("link", foreground=P.note_link, underline=True)
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
