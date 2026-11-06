# -*- coding: utf-8 -*-
"""便签窗口: Markdown 预览、自动续列表、超链接识别、钉到桌面"""

import ctypes
import os
import re
import shutil
import time
import uuid

import tkinter as tk
from tkinter import filedialog

try:
    from PIL import Image, ImageGrab, ImageTk
except Exception:  # 没装 pillow 就只是不能放图片
    Image = None
    ImageGrab = None
    ImageTk = None

from . import theme as T
from .paths import APP_DIR
from .store import walk as _walk
from .theme import P
from .utils import MonitorInfo, enable_acrylic, open_url, round_corners

LINK_RE = re.compile(r"(?:https?://|www\.)[^\s<>\"'\u3000]+")
LINK_TAIL = ".,;:!?)]}\u3002\uff0c\u3001\uff09\u300b"
IMG_RE = re.compile(r"!\[\]\(([^)]+)\)")
IMG_EXT = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp")


class NoteMixin:
    """便签相关: 一个任务可以开一张便签, 钉住的便签会留在桌面上"""

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

    # ---------------- 打开 / 关闭 ----------------
    def open_note(self, iid):
        """打开某个任务的便签; 已经开过就把窗口提到前面"""
        ref = self._refs.get(iid)
        if ref is None:
            return
        self.finish_edit()
        item = ref["item"]
        state = self.notes.get(item["id"])
        if state is not None:
            try:
                state["win"].lift()
                state["text"].focus_set()
            except Exception:
                pass
            return
        self.create_note(item)

    def create_note(self, item, restore=False):
        """真正建一个便签窗口"""
        note_id = item["id"]
        pinned = bool(item.get("note_pinned"))

        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg=P.note_edge)

        state = {"id": note_id, "item": item, "win": win, "text": None,
                 "editing": True, "raw": item.get("note") or "",
                 "pinned": pinned, "link_job": None, "mode_btn": None,
                 "pin_btn": None, "images": [], "image_map": {}}
        self.notes[note_id] = state

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
        close_btn.bind("<Button-1>", lambda ev, s=state: self.close_note(s["id"]))
        close_btn.bind("<Enter>", lambda ev: close_btn.configure(fg=P.note_fg))
        close_btn.bind("<Leave>", lambda ev: close_btn.configure(fg=P.note_dim))

        mode_btn = tk.Label(head, text="\u9884\u89c8", bg=P.note_head,
                            fg=P.note_dim, font=self.f_small,
                            cursor="hand2", padx=6)
        mode_btn.pack(side="right")
        mode_btn.bind("<Button-1>", lambda ev, s=state: self.note_toggle_mode(s))
        mode_btn.bind("<Enter>", lambda ev: mode_btn.configure(fg=P.note_fg))
        mode_btn.bind("<Leave>", lambda ev: mode_btn.configure(fg=P.note_dim))
        state["mode_btn"] = mode_btn

        pin_btn = tk.Label(head, text="\U0001F4CC", bg=P.note_head,
                           fg=P.note_dim, font=self.f_small,
                           cursor="hand2", padx=6)
        pin_btn.pack(side="right")
        pin_btn.bind("<Button-1>", lambda ev, s=state: self.toggle_note_pin(s))
        pin_btn.bind("<Enter>", lambda ev: pin_btn.configure(fg=P.note_fg))
        pin_btn.bind("<Leave>", lambda ev: pin_btn.configure(fg=P.note_dim))
        state["pin_btn"] = pin_btn

        img_btn = tk.Label(head, text="\U0001F5BC", bg=P.note_head,
                           fg=P.note_dim, font=self.f_small,
                           cursor="hand2", padx=6)
        img_btn.pack(side="right")
        img_btn.bind("<Button-1>", lambda ev, s=state: self.pick_note_image(s))
        img_btn.bind("<Enter>", lambda ev: img_btn.configure(fg=P.note_fg))
        img_btn.bind("<Leave>", lambda ev: img_btn.configure(fg=P.note_dim))

        hint = tk.Label(body, text="# 标题 · - 列表 · 1. 编号 · **加粗** · 网址可点",
                        bg=P.note_bg, fg=P.note_dim, font=self.f_small, anchor="w")
        hint.pack(fill="x", side="bottom", padx=12, pady=(0, 6))

        text = tk.Text(body, bg=P.note_bg, fg=P.note_fg, insertbackground=P.accent,
                       relief="flat", bd=0, highlightthickness=0, wrap="word",
                       font=self.f_item, padx=12, pady=10, undo=True,
                       selectbackground="#e6d7a8", selectforeground=P.note_fg)
        text.pack(fill="both", expand=True)
        state["text"] = text
        self.note_by_widget[text] = state

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

        self.note_fill_rich(state)

        drag = {"dx": 0, "dy": 0}
        def start_move(ev, w=win):
            drag["dx"] = ev.x_root - w.winfo_x()
            drag["dy"] = ev.y_root - w.winfo_y()

        def do_move(ev, w=win):
            nx = ev.x_root - drag["dx"]
            ny = ev.y_root - drag["dy"]
            w.geometry("+{}+{}".format(nx, ny))
            drag["moved"] = True

        def end_move(ev, s=state):
            if drag.get("moved"):
                drag["moved"] = False
                self.save_note_pos(s)

        for widget in (head, title, strip):
            widget.bind("<Button-1>", start_move)
            widget.bind("<B1-Motion>", do_move)
            widget.bind("<ButtonRelease-1>", end_move)

        win.bind("<Escape>", lambda ev, s=state: self.close_note(s["id"]))
        text.bind("<Escape>", lambda ev, s=state: self.close_note(s["id"]))
        text.bind("<Return>", self.note_on_return)
        text.bind("<KeyRelease>", self.note_schedule_links)
        text.bind("<Control-v>", lambda ev, s=state: self.paste_into_note(s))
        win.bind("<Control-v>", lambda ev, s=state: self.paste_into_note(s))
        text.bind("<Double-Button-1>", self.note_image_double_click)
        text.bind("<Button-1>", self.note_image_click, add="+")
        win.bind("<Configure>", lambda ev, s=state: self.round_note(s))

        self.make_note_grips(win, state)

        width, height = self.parse_note_size(item.get("note_size"))
        pos = self.parse_note_pos(item.get("note_pos"))
        if pos is None:
            pos = self.screen_center(width, height)
        win.geometry("{}x{}+{}+{}".format(width, height, pos[0], pos[1]))
        win.lift()
        win.after(30, lambda w=win: round_corners(w, 14))
        if getattr(self, "texture", "solid") == "glass":
            win.after(80, lambda w=win: enable_acrylic(w))
        self._note_opened_at = time.time()
        self.update_note_pin_button(state)

        if state["raw"].strip():
            # 有内容的便签默认直接看预览, 想看编辑再点
            self.note_toggle_mode(state)
        # 不管哪种模式都让输入框拿到焦点, Ctrl+V 才收得到
        if not restore:
            try:
                win.focus_force()
            except Exception:
                pass
        text.focus_set()

        if not restore:
            self.root.after(30, lambda s=state: self.note_mark_links(s))
        if pinned:
            win.after(60, lambda w=win: w.lift())

    # ---------------- 拖动宽高 ----------------
    def round_note(self, state):
        """改完大小重新切圆角"""
        win = state.get("win")
        if win is None:
            return
        job = state.get("round_job")
        if job is not None:
            try:
                win.after_cancel(job)
            except Exception:
                pass
        state["round_job"] = win.after(60, lambda w=win: round_corners(w, 14))

    def image_token_at(self, widget, x, y):
        """光标底下是不是一张图, 是就返回它的引用"""
        index = widget.index("@{},{}".format(x, y))
        try:
            chunks = widget.dump(index, index + " +1c", text=False,
                                 image=True, mark=False, tag=False, window=False)
        except Exception:
            return None
        if not chunks or chunks[0][0] != "image":
            return None
        state = self.note_state_of(widget)
        if state is None:
            return None
        return state["image_map"].get(chunks[0][1])

    def open_image_token(self, token):
        match = IMG_RE.match(token or "")
        if not match:
            return False
        self.show_image_preview(match.group(1))
        return True

    def note_image_click(self, event):
        """预览态单击图片就放大 (编辑态单击还是挪光标)"""
        state = self.note_state_of(event.widget)
        if state is None or state["editing"]:
            return None
        token = self.image_token_at(event.widget, event.x, event.y)
        if not token:
            return None
        return "break" if self.open_image_token(token) else None

    def note_image_double_click(self, event):
        """双击图片放大查看"""
        token = self.image_token_at(event.widget, event.x, event.y)
        if not token:
            return None
        return "break" if self.open_image_token(token) else None

    def show_image_preview(self, path):
        """大图查看窗口: 点一下或按 Esc 关掉"""
        if Image is None or ImageTk is None:
            return
        full = self.resolve_image_path(path)
        if not full:
            return
        try:
            image = Image.open(full)
        except Exception:
            return

        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        width = image.width
        height = image.height
        limit_w = int(screen_w * 0.8)
        limit_h = int(screen_h * 0.8)
        if width > limit_w or height > limit_h:
            ratio = min(limit_w / float(width), limit_h / float(height))
            width = int(width * ratio)
            height = int(height * ratio)
            image = image.resize((max(1, width), max(1, height)))

        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg="#0f1014")
        photo = ImageTk.PhotoImage(image)
        label = tk.Label(win, image=photo, bg="#0f1014", bd=0,
                         highlightthickness=0)
        label.image = photo
        label.pack(fill="both", expand=True)

        x = (screen_w - width) // 2
        y = (screen_h - height) // 2
        win.geometry("{}x{}+{}+{}".format(width, height, x, y))
        win.after(30, lambda w=win: round_corners(w, 10))
        for widget in (win, label):
            widget.bind("<Button-1>", lambda ev, w=win: w.destroy())
        win.bind("<Escape>", lambda ev, w=win: w.destroy())
        win.lift()

    def make_note_grips(self, win, state):
        """无边框窗口自己实现右下角/右边/下边的拉伸"""
        grip_color = P.note_edge

        right = tk.Frame(win, bg=grip_color, cursor="sb_h_double_arrow")
        right.place(relx=1.0, x=-4, y=0, relheight=1.0, width=4)
        bottom = tk.Frame(win, bg=grip_color, cursor="sb_v_double_arrow")
        bottom.place(relx=0, rely=1.0, y=-4, relwidth=1.0, height=4)
        corner = tk.Frame(win, bg=grip_color, cursor="sizing")
        corner.place(relx=1.0, rely=1.0, x=-14, y=-14, width=14, height=14)

        for widget, mode in ((right, "e"), (bottom, "s"), (corner, "se")):
            widget.bind("<Button-1>",
                        lambda ev, m=mode: self.start_note_resize(state, ev, m))
            widget.bind("<B1-Motion>",
                        lambda ev: self.do_note_resize(state, ev))
            widget.bind("<ButtonRelease-1>",
                        lambda ev: self.end_note_resize(state))

    def start_note_resize(self, state, event, mode):
        win = state["win"]
        state["resize"] = {"mode": mode, "x": event.x_root, "y": event.y_root,
                           "w": win.winfo_width(), "h": win.winfo_height()}

    def do_note_resize(self, state, event):
        info = state.get("resize")
        if not info:
            return
        win = state["win"]
        dx = event.x_root - info["x"]
        dy = event.y_root - info["y"]
        width = info["w"]
        height = info["h"]
        if info["mode"] in ("e", "se"):
            width = max(280, info["w"] + dx)
        if info["mode"] in ("s", "se"):
            height = max(180, info["h"] + dy)
        win.geometry("{}x{}".format(width, height))

    def end_note_resize(self, state):
        state["resize"] = None
        self.save_note_geom(state)

    def parse_note_size(self, value):
        """'420x300' -> (420, 300)"""
        if not value:
            return 400, 320
        try:
            width, height = str(value).split("x")
            return max(280, int(width)), max(180, int(height))
        except Exception:
            return 400, 320

    # ---------------- 钉在最前面 ----------------
    def toggle_note_pin(self, state):
        """钉住/取消钉住: 钉住的便签固定在最前面, 点别处也不关"""
        state["pinned"] = not state["pinned"]
        item = state["item"]
        item["note_pinned"] = state["pinned"]
        if state["pinned"]:
            item["note_pos"] = "{},{}".format(state["win"].winfo_x(),
                                              state["win"].winfo_y())
        self.store.save()
        self.update_note_pin_button(state)
        try:
            state["win"].attributes("-topmost", True)
            if state["pinned"]:
                state["win"].lift()
        except Exception:
            pass

    def update_note_pin_button(self, state):
        """图钉按钮的样子跟着状态变"""
        btn = state.get("pin_btn")
        if btn is None:
            return
        if state["pinned"]:
            btn.configure(bg=P.accent, fg="#ffffff")
        else:
            btn.configure(bg=P.note_head, fg=P.note_dim)

    def parse_note_pos(self, value):
        """'120,340' -> (120, 340)"""
        if not value:
            return None
        try:
            left, top = str(value).split(",")
            return int(left), int(top)
        except Exception:
            return None

    def save_note_pos(self, state):
        """记住便签位置和大小, 下次还开在这儿"""
        self.save_note_geom(state)

    def save_note_geom(self, state):
        win = state.get("win")
        if win is None:
            return
        try:
            item = state["item"]
            item["note_pos"] = "{},{}".format(win.winfo_x(), win.winfo_y())
            item["note_size"] = "{}x{}".format(win.winfo_width(),
                                               win.winfo_height())
            self.store.save()
        except Exception:
            pass

    # ---------------- 图片 ----------------
    def pick_note_image(self, state):
        """选一张本地图片放进便签"""
        patterns = " ".join("*" + ext for ext in IMG_EXT)
        path = filedialog.askopenfilename(
            parent=state["win"], title="选择图片",
            filetypes=[("图片", patterns), ("所有文件", "*.*")])
        if not path:
            return
        self.add_image_file(state, path)

    def add_image_file(self, state, source):
        """把图片复制到 note_images 目录, 再插入引用"""
        try:
            folder = os.path.join(APP_DIR, "note_images")
            if not os.path.isdir(folder):
                os.makedirs(folder, exist_ok=True)
            ext = os.path.splitext(source)[1].lower()
            if ext not in IMG_EXT:
                ext = ".png"
            name = uuid.uuid4().hex[:12] + ext
            shutil.copyfile(source, os.path.join(folder, name))
        except Exception:
            return
        self.insert_image_token(state, name)

    def add_image_bitmap(self, state, image):
        """把剪贴板里的位图存成文件再插入"""
        try:
            folder = os.path.join(APP_DIR, "note_images")
            if not os.path.isdir(folder):
                os.makedirs(folder, exist_ok=True)
            name = uuid.uuid4().hex[:12] + ".png"
            image.save(os.path.join(folder, name), "PNG")
        except Exception:
            return
        self.insert_image_token(state, name)

    def insert_image_token(self, state, name):
        """把刚加的图片插到光标处, 编辑态直接显示成图"""
        if not state["editing"]:
            self.note_toggle_mode(state)
        widget = state["text"]
        path = "note_images/" + name
        widget.insert("insert", "\n")
        pos = widget.index("insert")
        photo = self.insert_rich_image(widget, state, path, index=pos)
        widget.insert(pos + " + 1c", "\n")
        if photo is not None:
            widget.mark_set("insert", pos + " + 2c")
        widget.see("insert")
        self.note_mark_links(state)

    def paste_into_note(self, state):
        """Ctrl+V: 剪贴板是图片就贴图, 否则走正常粘贴"""
        if ImageGrab is None:
            return None
        data = None
        try:
            data = ImageGrab.grabclipboard()
        except Exception:
            data = None
        if data is None:
            return None
        if isinstance(data, list):
            for path in data:
                if str(path).lower().endswith(IMG_EXT):
                    self.add_image_file(state, str(path))
                    return "break"
            return None
        self.add_image_bitmap(state, data)
        return "break"

    def resolve_image_path(self, path):
        """图片路径: 绝对路径或相对项目目录"""
        if os.path.isabs(path) and os.path.exists(path):
            return path
        full = os.path.join(APP_DIR, path.replace("/", os.sep))
        if os.path.exists(full):
            return full
        return None

    def insert_note_image(self, widget, path):
        """预览里把 ![](xxx) 画成真图"""
        state = self.note_by_widget.get(widget)
        if state is None or Image is None:
            widget.insert("end", "![]({})".format(path))
            return
        photo = self.load_note_photo(state, path)
        if photo is None:
            widget.insert("end", "\uff08\u56fe\u7247\u6253\u4e0d\u5f00\uff09")
            return
        widget.image_create("end", image=photo, padx=2, pady=3)
        # 记下来, 预览态双击也能认出是哪张图
        state["image_map"][str(photo)] = "![]({})".format(path)

    # ---------------- 编辑 / 预览 ----------------
    def note_state_of(self, widget):
        """从任意子控件找到它所属的便签状态"""
        return self.note_by_widget.get(widget)

    def note_on_return(self, event):
        """回车自动续列表: - 续 - , 1. 续 2."""
        widget = event.widget
        state = self.note_state_of(widget)
        if state is None:
            return None
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

    def note_toggle_mode(self, state):
        widget = state["text"]
        if state["editing"]:
            state["raw"] = self.note_get_raw(state)
            self.note_render(state)
            state["editing"] = False
            state["mode_btn"].config(text="\u7f16\u8f91")
            return

        state["editing"] = True
        self.note_fill_rich(state)
        state["mode_btn"].config(text="\u9884\u89c8")
        widget.focus_set()

    def note_fill_rich(self, state):
        """把原始文本装进编辑框, 图片直接显示成图"""
        widget = state["text"]
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        state["images"] = []
        state["image_map"] = {}
        raw = state["raw"] or ""
        pos = 0
        for match in IMG_RE.finditer(raw):
            chunk = raw[pos:match.start()]
            if chunk:
                widget.insert("end", chunk)
            self.insert_rich_image(widget, state, match.group(1))
            pos = match.end()
        tail = raw[pos:]
        if tail:
            widget.insert("end", tail)

    def insert_rich_image(self, widget, state, path, index="end"):
        """在编辑框里直接画出图片, 同时记下对应的引用文字"""
        token = "![]({})".format(path)
        photo = self.load_note_photo(state, path)
        if photo is None:
            widget.insert(index, token)
            return None
        widget.image_create(index, image=photo, padx=2, pady=3)
        state["image_map"][str(photo)] = token
        return photo

    def load_note_photo(self, state, path):
        """读图片并按便签宽度缩放"""
        if Image is None:
            return None
        full = self.resolve_image_path(path)
        if not full:
            return None
        try:
            image = Image.open(full)
            max_width = max(200, state["win"].winfo_width() - 60)
            if image.width > max_width:
                ratio = max_width / float(image.width)
                size = (int(image.width * ratio), int(image.height * ratio))
                image = image.resize(size)
            photo = ImageTk.PhotoImage(image)
        except Exception:
            return None
        state["images"].append(photo)
        return photo

    def note_get_raw(self, state):
        """从编辑框取回原始文本, 把图片还原成 ![](path)"""
        widget = state["text"]
        if widget is None:
            return ""
        try:
            chunks = widget.dump("1.0", "end-1c", text=True, image=True)
        except Exception:
            try:
                return widget.get("1.0", "end-1c")
            except Exception:
                return ""
        parts = []
        for kind, value, index in chunks:
            if kind == "text":
                parts.append(value)
            elif kind == "image":
                parts.append(state["image_map"].get(value, ""))
        return "".join(parts)

    def note_render(self, state):
        widget = state["text"]
        raw = state["raw"] or ""
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        for line in raw.split("\n"):
            self.note_render_line(widget, line)
        widget.configure(state="disabled")

    def note_schedule_links(self, event=None):
        state = self.note_state_of(event.widget) if event is not None else None
        if state is None:
            return
        if not state["editing"]:
            return
        win = state["win"]
        job = state.get("link_job")
        if job is not None:
            try:
                win.after_cancel(job)
            except Exception:
                pass
        state["link_job"] = win.after(350, lambda: self.note_mark_links(state))

    def note_mark_links(self, state):
        """把文里的网址标出来, 变成可点的链接"""
        state["link_job"] = None
        widget = state["text"]
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

    def note_link_at(self, widget, index):
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
        widget = event.widget
        index = widget.index("@{},{}".format(event.x, event.y))
        url = self.note_link_at(widget, index)
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
        """处理 **加粗**、`代码` 和图片引用"""
        parts = re.split(r"(\*\*.+?\*\*|`[^`]+`|!\[\]\([^)]+\))", text)
        for part in parts:
            if not part:
                continue
            image = IMG_RE.match(part)
            if image:
                self.insert_note_image(widget, image.group(1))
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
                self.note_insert_text_with_links(widget, part)

    def shorten_link(self, url, limit=48):
        """长链接显示成头尾 + 省略号, 点开还是完整地址"""
        if len(url) <= limit:
            return url
        head = url[:limit - 16]
        tail = url[-10:]
        return head + "\u2026" + tail

    def note_insert_text_with_links(self, widget, text):
        """插入普通文字, 顺便把里面的网址做成可点的短链接"""
        state = self.note_by_widget.get(widget)
        if state is None:
            widget.insert("end", text)
            return
        pos = 0
        for match in LINK_RE.finditer(text):
            if match.start() > pos:
                widget.insert("end", text[pos:match.start()])
            url = match.group(0).rstrip(LINK_TAIL)
            start = widget.index("end-1c")
            widget.insert("end", self.shorten_link(url))
            end = widget.index("end-1c")
            state["link_seq"] = state.get("link_seq", 0) + 1
            tag = "noteurl{}".format(state["link_seq"])
            widget.tag_add(tag, start, end)
            widget.tag_configure(tag, foreground=P.note_link, underline=True)
            widget.tag_bind(tag, "<Button-1>",
                            lambda ev, u=url: self.note_url_click(ev, u))
            widget.tag_bind(tag, "<Enter>",
                            lambda ev, w=widget: w.configure(cursor="hand2"))
            widget.tag_bind(tag, "<Leave>",
                            lambda ev, w=widget: w.configure(cursor="xterm"))
            pos = match.end()
        if pos < len(text):
            widget.insert("end", text[pos:])

    def note_url_click(self, event, url):
        """点短链接, 打开完整地址"""
        open_url(url)
        return "break"

    # ---------------- 关闭 ----------------
    def close_note(self, note_id=None, keep_pinned=False):
        """关掉便签; 不给 id 就关全部, keep_pinned 时保留钉住的"""
        if note_id is not None:
            targets = [note_id]
        else:
            targets = list(self.notes.keys())

        for key in targets:
            state = self.notes.get(key)
            if state is None:
                continue
            if keep_pinned and state.get("pinned") and note_id is None:
                continue
            self._close_one(state)

    def _close_one(self, state):
        win = state["win"]
        text = state["text"]
        editing = state["editing"]
        raw = state["raw"]
        item = state["item"]

        if state.get("pinned"):
            self.save_note_pos(state)

        self.notes.pop(state["id"], None)
        if text is not None:
            self.note_by_widget.pop(text, None)

        content = ""
        if editing and text is not None:
            try:
                content = self.note_get_raw(state).strip()
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

    def reopen_pinned_notes(self):
        """启动或换主题后, 把钉在桌面上的便签重新摆出来"""
        for item, _ in _walk(self.store.items):
            if not item.get("note_pinned"):
                continue
            if item["id"] in self.notes:
                continue
            self.create_note(item, restore=True)
