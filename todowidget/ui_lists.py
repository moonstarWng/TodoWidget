# -*- coding: utf-8 -*-
"""多清单: 左上角下拉菜单、新建/重命名/删除、通用输入弹窗"""

import tkinter as tk
from tkinter import messagebox

try:
    from PIL import Image, ImageDraw, ImageTk
except Exception:
    Image = None

from . import theme as T
from .shadow import attach_shadow
from .theme import P, best_text_color, hex_to_rgb, mix_color
from .utils import round_corners

class ListMenuMixin:
    def dot_photo(self, color, size=10):
        """画一个抗锯齿的彩色小圆点

        Tk 自己的 create_oval 是 GDI 画的, 没有抗锯齿, 小圆点放大看是方的;
        这里用 PIL 画好再当图片贴上去。

        :param color: 圆点颜色
        :param size: 边长
        """
        if Image is None:
            return None
        try:
            scale = 4
            big = Image.new("RGBA", (size * scale, size * scale),
                            (0, 0, 0, 0))
            draw = ImageDraw.Draw(big)
            draw.ellipse([0, 0, size * scale - 1, size * scale - 1],
                         fill=hex_to_rgb(color) + (255,))
            image = big.resize((size, size), Image.LANCZOS)
            return ImageTk.PhotoImage(image)
        except Exception:
            return None

    def make_dot_image(self, color, size=10):
        """菜单里清单前面那个彩色小圆点"""
        photo = self.dot_photo(color, size)
        if photo is None:
            return None
        self._menu_dots.append(photo)
        return photo

    def build_list_menu(self):
        menu = tk.Menu(self.root, tearoff=0)
        self._menu_dots = []
        for lst in self.store.visible_lists():
            label = lst["name"]
            if lst["id"] == self.store.current:
                label = "\u2713  " + label
            else:
                label = "    " + label
            dot = self.make_dot_image(lst.get("color") or P.accent)
            if dot is not None:
                menu.add_command(label=label, image=dot, compound="left",
                                 command=lambda lid=lst["id"]: self.switch_list(lid))
            else:
                menu.add_command(label=label,
                                 command=lambda lid=lst["id"]: self.switch_list(lid))
        menu.add_separator()
        menu.add_command(label="新建清单…", command=self.new_list)
        menu.add_command(label="重命名当前清单…", command=self.rename_list)
        menu.add_command(label="删除当前清单…", command=self.delete_list)
        menu.add_separator()
        if self.store.hidden_lists() or self.store.deleted_lists():
            label = "清单管理…（{} 项已隐藏/删除）".format(
                len(self.store.hidden_lists()) + len(self.store.deleted_lists()))
        else:
            label = "清单管理…"
        menu.add_command(label=label, command=self.open_list_manager)
        return menu

    def open_list_menu(self, event=None):
        # 收起成横条时标题是固定的"待办清单", 不弹清单菜单
        if self.collapsed:
            return
        self.finish_edit()
        menu = self.build_list_menu()
        x = self.lbl_title.winfo_rootx()
        y = self.lbl_title.winfo_rooty() + self.lbl_title.winfo_height() + 2
        try:
            self.popup_menu(menu, x, y)
        finally:
            menu.grab_release()

    def cycle_list(self, step):
        """切到下一个 / 上一个清单(首尾循环)

        :param step: 1 下一个, -1 上一个
        """
        lists = self.store.visible_lists()
        if len(lists) < 2:
            return
        ids = [item.get("id") for item in lists]
        try:
            index = ids.index(self.store.current)
        except ValueError:
            index = 0
        target = ids[(index + step) % len(ids)]
        if target == self.store.current:
            return
        # 先起标题动画, 换清单时 update_title 会把新名字塞进去
        self.fade_title()
        self.switch_list(target)

    def update_list_switch(self):
        """清单数量 / 收起状态变了, 决定那两个箭头显不显示"""
        buttons = (self.btn_next_list, self.btn_prev_list)
        if not all(buttons):
            return
        show = len(self.store.visible_lists()) > 1 and not self.collapsed
        for btn in buttons:
            mapped = bool(btn.winfo_manager())
            if show and not mapped:
                btn.pack(side="right", padx=(0, 4), pady=(6, 0))
            elif not show and mapped:
                btn.pack_forget()

    def open_list_manager(self):
        """清单管理: 隐藏 / 删除(保留 30 天) / 恢复"""
        if getattr(self, "manage_win", None) is not None:
            try:
                self.manage_win.lift()
                self.refresh_list_manager()
                return
            except Exception:
                self.manage_win = None

        win = tk.Toplevel(self.root)
        win.withdraw()
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg=P.bg)
        self.manage_win = win

        body = tk.Frame(win, bg=P.bg)
        body.pack(fill="both", expand=True, padx=1, pady=1)
        head = tk.Frame(body, bg=P.head, height=38)
        head.pack(fill="x")
        head.pack_propagate(False)
        tk.Label(head, text="清单管理", bg=P.head, fg=P.fg,
                 font=self.f_group).pack(side="left", padx=14)
        close = tk.Label(head, text="\u2715", bg=P.head, fg=P.fg_dim,
                         font=self.f_small, width=2, cursor="hand2")
        close.pack(side="right", padx=6)
        close.bind("<Button-1>", lambda ev: self.close_list_manager())

        self._manage_canvas = tk.Canvas(body, bg=P.bg, bd=0,
                                        highlightthickness=0)
        self._manage_canvas.pack(fill="both", expand=True, padx=12,
                                 pady=(10, 4))
        self._manage_list = tk.Frame(self._manage_canvas, bg=P.bg)
        self._manage_item = self._manage_canvas.create_window(
            (0, 0), window=self._manage_list, anchor="nw")
        self._manage_list.bind("<Configure>", self.sync_manage_scroll)
        self._manage_canvas.bind(
            "<Configure>",
            lambda ev: self._manage_canvas.itemconfigure(
                self._manage_item, width=max(10, ev.width)))

        note = tk.Label(
            body, text="隐藏的清单不会出现在下拉和左右切换里；删除的清单会保留 30 天，"
                       "过期后自动清理。",
            bg=P.bg, fg=P.fg_faint, font=self.f_small, justify="left",
            wraplength=400, anchor="w")
        note.pack(fill="x", padx=14)
        footer = tk.Frame(body, bg=P.bg)
        footer.pack(fill="x", side="bottom", padx=12, pady=(6, 10))
        close = tk.Label(footer, text="关闭", bg=P.bg_alt, fg=P.fg_dim,
                         font=self.f_small, padx=16, pady=6, cursor="hand2")
        close.pack(side="right")
        close.bind("<Button-1>", lambda ev: self.close_list_manager())
        self._manage_close = close
        for widget, normal, hover in ((close, P.bg_alt, P.hover),):
            widget.bind("<Enter>",
                        lambda ev, w=widget, c=hover: w.configure(bg=c))
            widget.bind("<Leave>",
                        lambda ev, w=widget, c=normal: w.configure(bg=c))
        self.root.bind_all("<MouseWheel>", self.manage_wheel)

        def drag_start(ev):
            self._manage_drag = (ev.x_root - win.winfo_x(),
                                 ev.y_root - win.winfo_y())

        def drag_move(ev):
            point = getattr(self, "_manage_drag", None)
            if not point:
                return
            win.geometry("+{}+{}".format(ev.x_root - point[0],
                                         ev.y_root - point[1]))

        head.bind("<Button-1>", drag_start)
        head.bind("<B1-Motion>", drag_move)
        win.bind("<Escape>", lambda ev: self.close_list_manager())

        self.refresh_list_manager()
        width, height = 440, 460
        x, y = self.screen_center(width, height)
        win.geometry("{}x{}+{}+{}".format(width, height, x, y))
        win.deiconify()
        self.fit_manager_height(center=True)
        self._manage_shadow = attach_shadow(win, radius=12, card=P.bg,
                                            ring=P.border)
        win.lift()
        try:
            win.grab_set()
        except Exception:
            pass

    def close_list_manager(self):
        """关掉清单管理窗口"""
        win = getattr(self, "manage_win", None)
        self.manage_win = None
        shadow = getattr(self, "_manage_shadow", None)
        self._manage_shadow = None
        if shadow is not None:
            shadow.destroy()
        if win is None:
            return
        try:
            self.root.unbind_all("<MouseWheel>")
        except Exception:
            pass
        try:
            win.grab_release()
        except Exception:
            pass
        try:
            win.destroy()
        except Exception:
            pass

    def manage_wheel(self, event):
        """清单管理里滚轮翻列表

        :param event: 滚轮事件
        """
        canvas = getattr(self, "_manage_canvas", None)
        if canvas is None:
            return
        try:
            step = -1 if event.delta > 0 else 1
            canvas.yview_scroll(step * 2, "units")
        except Exception:
            pass

    def sync_manage_scroll(self, event=None):
        """列表内容变了, 更新滚动范围"""
        canvas = getattr(self, "_manage_canvas", None)
        if canvas is None:
            return
        try:
            canvas.configure(scrollregion=canvas.bbox("all"))
        except Exception:
            pass

    def fit_manager_height(self, center=False):
        """窗口高度跟着内容走, 太高就滚动(最多 620)

        :param center: 要不要按新高度重新摆到屏幕中间(第一次打开时)
        """
        win = getattr(self, "manage_win", None)
        holder = getattr(self, "_manage_list", None)
        if win is None or holder is None:
            return
        try:
            win.update_idletasks()
            content = holder.winfo_reqheight()
            height = min(620, max(300, content + 150))
            width = 440
            if center:
                x, y = self.screen_center(width, height)
            else:
                x = win.winfo_x()
                y = win.winfo_y()
            win.geometry("{}x{}+{}+{}".format(width, height, x, y))
            self.sync_manage_scroll()
        except Exception:
            pass

    def refresh_list_manager(self):
        """重画清单管理里的行"""
        holder = getattr(self, "_manage_list", None)
        win = getattr(self, "manage_win", None)
        if holder is None or win is None:
            return
        for child in holder.winfo_children():
            child.destroy()
        groups = (
            ("正常清单", self.store.visible_lists(), "normal"),
            ("已隐藏", self.store.hidden_lists(), "hidden"),
            ("已删除（保留 30 天）", self.store.deleted_lists(), "deleted"),
        )
        for title, items, kind in groups:
            if not items:
                continue
            tk.Label(holder, text="{}（{}）".format(title, len(items)),
                     bg=P.bg, fg=P.fg_dim, font=self.f_small,
                     anchor="w").pack(fill="x", pady=(4, 2))
            for lst in items:
                self.build_list_manager_row(holder, lst, kind)
        self.sync_manage_scroll()
        self.fit_manager_height()

    def build_list_manager_row(self, parent, lst, kind):
        """清单管理里的一行

        :param parent: 容器
        :param lst: 清单字典
        :param kind: normal / hidden / deleted
        """
        row = tk.Frame(parent, bg=P.bg_alt)
        row.pack(fill="x", pady=(0, 6))
        dot = tk.Canvas(row, width=10, height=10, bg=P.bg_alt,
                        highlightthickness=0, bd=0)
        dot.pack(side="left", padx=(10, 6))
        color = lst.get("color") or P.accent
        photo = self.dot_photo(color, 10)
        if photo is not None:
            dot.create_image(5, 5, image=photo)
            dot._photo = photo
        else:
            dot.create_oval(1, 1, 9, 9, fill=color, outline="")
        name = tk.Label(row, text=lst.get("name") or "未命名", bg=P.bg_alt,
                        fg=P.fg, font=self.f_item, anchor="w")
        name.pack(side="left")
        count = self.count_items(lst)
        tk.Label(row, text="{} 项".format(count), bg=P.bg_alt, fg=P.fg_faint,
                 font=self.f_small).pack(side="left", padx=8)

        if kind == "deleted":
            left = self.deleted_days_left(lst)
            tk.Label(row, text="还剩 {} 天".format(left), bg=P.bg_alt,
                     fg=P.fg_dim, font=self.f_small).pack(side="left")
        tk.Label(row, text="", bg=P.bg_alt).pack(side="left", fill="x",
                                                 expand=True)

        def button(text, command, strong=False):
            normal_fg = P.accent if strong else P.fg_dim
            normal_bg = P.bg_alt
            hover_bg = mix_color(normal_bg, P.fg, 0.12)
            label = tk.Label(row, text=text, bg=normal_bg, fg=normal_fg,
                             font=self.f_small, padx=10, pady=3,
                             cursor="hand2")
            label.pack(side="right", padx=(0, 4))
            label.bind("<Button-1>", lambda ev: command())
            label.bind("<Enter>", lambda ev, w=label, c=hover_bg:
                       w.configure(bg=c, fg=P.fg))
            label.bind("<Leave>", lambda ev, w=label, c=normal_bg,
                       f=normal_fg: w.configure(bg=c, fg=f))
            return label

        if kind == "normal":
            button("删除", lambda: self.manager_delete(lst), strong=False)
            if len(self.store.visible_lists()) > 1:
                button("隐藏", lambda: self.manager_hide(lst))
        else:
            button("恢复", lambda: self.manager_restore(lst))
            if kind == "hidden":
                button("删除", lambda: self.manager_delete(lst))
            else:
                button("彻底删除", lambda: self.manager_purge(lst), strong=True)

    def count_items(self, lst):
        """清单里有多少条任务(含子任务)

        :param lst: 清单字典
        """
        total = 0

        def walk(items):
            nonlocal total
            for it in items:
                total += 1
                walk(it.get("children") or [])

        walk(lst.get("items") or [])
        return total

    def deleted_days_left(self, lst):
        """删除的清单还剩几天

        :param lst: 清单字典
        """
        stamp = lst.get("deleted_at") or ""
        if not stamp:
            return 30
        try:
            from datetime import datetime
            when = datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S")
            left = 30 - (datetime.now() - when).days
            return max(0, left)
        except Exception:
            return 30

    def manager_hide(self, lst):
        """隐藏清单

        :param lst: 清单字典
        """
        self.store.set_list_hidden(lst.get("id"), True)
        self.store.save()
        self.after_list_change()

    def manager_delete(self, lst):
        """删除清单(软删除, 保留 30 天)

        :param lst: 清单字典
        """
        from tkinter import messagebox
        name = lst.get("name") or "未命名"
        if not messagebox.askyesno(
                "删除清单",
                "删除「{}」？\n里面的任务会一起保留 30 天，期间可以恢复。".format(name),
                parent=self.manage_win):
            return
        self.store.delete_list_soft(lst.get("id"))
        self.store.save()
        self.after_list_change()

    def manager_purge(self, lst):
        """彻底删除(不能恢复)

        :param lst: 清单字典
        """
        from tkinter import messagebox
        name = lst.get("name") or "未命名"
        if not messagebox.askyesno(
                "彻底删除",
                "彻底删除「{}」？\n里面的任务会一起删掉，不能恢复。".format(name),
                parent=self.manage_win):
            return
        self.store.delete_list_permanent(lst.get("id"))
        self.store.save()
        self.after_list_change()

    def manager_restore(self, lst):
        """恢复隐藏 / 删除的清单

        :param lst: 清单字典
        """
        self.store.restore_list(lst.get("id"))
        self.store.save()
        self.after_list_change()

    def after_list_change(self):
        """清单状态变了: 主界面和管窗口一起刷新"""
        self.refresh()
        self.refresh_list_manager()

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
