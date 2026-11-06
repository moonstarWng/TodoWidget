# -*- coding: utf-8 -*-
"""多清单: 左上角下拉菜单、新建/重命名/删除、通用输入弹窗"""

import tkinter as tk
from tkinter import messagebox

from . import theme as T
from .theme import P, best_text_color
from .utils import round_corners

class ListMenuMixin:
    def build_list_menu(self):
        menu = tk.Menu(self.root, tearoff=0)
        for lst in self.store.lists:
            label = lst["name"]
            if lst["id"] == self.store.current:
                label = "\u2713  " + label
            else:
                label = "    " + label
            menu.add_command(label=label,
                             command=lambda lid=lst["id"]: self.switch_list(lid))
        menu.add_separator()
        menu.add_command(label="新建清单…", command=self.new_list)
        menu.add_command(label="重命名当前清单…", command=self.rename_list)
        menu.add_command(label="删除当前清单…", command=self.delete_list)
        return menu

    def open_list_menu(self, event=None):
        self.finish_edit()
        menu = self.build_list_menu()
        x = self.lbl_title.winfo_rootx()
        y = self.lbl_title.winfo_rooty() + self.lbl_title.winfo_height() + 2
        try:
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def switch_list(self, list_id):
        if list_id == self.store.current:
            return
        self.finish_edit()
        self.close_note(keep_pinned=True)
        self.store.select(list_id)
        self.store.save()
        self.refresh()

    def new_list(self):
        def create(name):
            self.store.add_list(name)
            self.store.save()
            self.refresh()

        self.prompt_text("新建清单", "新清单", create)

    def rename_list(self):
        def apply(name):
            self.store.rename_list(self.store.current, name)
            self.store.save()
            self.refresh()

        self.prompt_text("重命名清单", self.store.current_name(), apply)

    def delete_list(self):
        if len(self.store.lists) <= 1:
            messagebox.showinfo("删除清单", "至少要保留一份清单。",
                                parent=self.root)
            return
        name = self.store.current_name()
        try:
            self.root.attributes("-topmost", True)
        except Exception:
            pass
        confirmed = messagebox.askyesno(
            "删除清单", "删除清单「{}」以及里面的所有任务？".format(name),
            parent=self.root)
        try:
            self.root.attributes("-topmost", bool(self.topmost))
        except Exception:
            pass
        if not confirmed:
            return
        self.close_note(keep_pinned=True)
        self.store.delete_list(self.store.current)
        self.store.save()
        self.refresh()

    def prompt_text(self, title, initial, on_ok):
        """一个小的输入弹窗, 风格跟主界面一致"""
        if self.prompt_win is not None:
            try:
                self.prompt_win.destroy()
            except Exception:
                pass
            self.prompt_win = None

        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg=P.border)
        self.prompt_win = win

        body = tk.Frame(win, bg=P.bg)
        body.pack(fill="both", expand=True, padx=1, pady=1)

        head = tk.Frame(body, bg=P.head, height=28)
        head.pack(fill="x")
        head.pack_propagate(False)
        tk.Label(head, text=title, bg=P.head, fg=P.fg,
                 font=self.f_small).pack(side="left", padx=10)

        entry = tk.Entry(body, bg=P.bg_alt, fg=P.fg,
                         insertbackground=P.accent, relief="flat", bd=0,
                         highlightthickness=1, highlightbackground=P.accent,
                         highlightcolor=P.accent, font=self.f_item)
        entry.pack(fill="x", padx=10, pady=10)
        entry.insert(0, initial or "")
        entry.select_range(0, "end")

        row = tk.Frame(body, bg=P.bg)
        row.pack(fill="x", padx=10, pady=(0, 10))

        state = {"done": False}

        def close(commit):
            if state["done"]:
                return
            state["done"] = True
            value = entry.get().strip()
            self.prompt_win = None
            try:
                win.destroy()
            except Exception:
                pass
            if commit and value:
                on_ok(value)

        ok_btn = tk.Label(row, text="确定", bg=P.accent,
                          fg=best_text_color(P.accent), font=self.f_small,
                          cursor="hand2", padx=12, pady=3)
        ok_btn.pack(side="right")
        ok_btn.bind("<Button-1>", lambda ev: close(True))

        cancel_btn = tk.Label(row, text="取消", bg=P.bg, fg=P.fg_dim,
                              font=self.f_small, cursor="hand2", padx=10, pady=3)
        cancel_btn.pack(side="right", padx=(0, 6))
        cancel_btn.bind("<Button-1>", lambda ev: close(False))

        entry.bind("<Return>", lambda ev: close(True))
        entry.bind("<Escape>", lambda ev: close(False))
        win.bind("<Escape>", lambda ev: close(False))

        width, height = 260, 108
        base_x = self.root.winfo_rootx() + (self.root.winfo_width() - width) // 2
        base_y = self.root.winfo_rooty() + (self.root.winfo_height() - height) // 2
        win.geometry("{}x{}+{}+{}".format(width, height, base_x, base_y))
        win.after(30, lambda w=win: round_corners(w, 12))
        win.lift()
        entry.focus_set()

    # ---------------- 便签 ----------------
