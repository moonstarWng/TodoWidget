# -*- coding: utf-8 -*-
"""清单列表: 渲染、勾选、改名、拖动排序、右键菜单"""

import tkinter as tk
from datetime import datetime, timedelta
from tkinter import messagebox

from . import theme as T
from .store import leaf_stats, new_item, now_str, walk
from .theme import P
from .utils import FakeEvent

BOX_OFF = "\u2610"  # ☐ 没有图标时的兜底
BOX_ON = "\u2611"   # ☑

class ListViewMixin:
    def item_time(self, it):
        """这条在它所在页签里该按哪个时间排"""
        if self.tab == "done":
            return it.get("completed_at") or it.get("created_at") or ""
        return it.get("created_at") or ""

    def format_day(self, day):
        """隔板上显示的日期"""
        if not day:
            return "未知日期"
        today = datetime.now().strftime("%Y-%m-%d")
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        if day == today:
            return "今天 · " + day[5:]
        if day == yesterday:
            return "昨天 · " + day[5:]
        return day

    def ordered_roots(self):
        """当前页签要显示的根条目; 钉住的排最前, 按时间模式时再按时间排"""
        want_done = self.tab == "done"
        pinned = []
        normal = []
        for it in self.store.items:
            if bool(it.get("done")) != want_done:
                continue
            if it.get("pinned"):
                pinned.append(it)
            else:
                normal.append(it)
        if self.sort_mode == "time":
            newest_first = want_done
            normal.sort(key=self.item_time, reverse=newest_first)
        return pinned + normal

    def pinned_first(self, items):
        """同一层里把钉住的提到前面"""
        pinned = []
        normal = []
        for it in items:
            if it.get("pinned"):
                pinned.append(it)
            else:
                normal.append(it)
        return pinned + normal

    def refresh(self, sync_open=True):
        t = self.tree
        sel = t.focus()
        name = self.store.current_name()
        if len(name) > 10:
            name = name[:9] + "\u2026"
        self.lbl_title.config(text=name + "  \u25be")
        try:
            current = self.store.current_list()
            color = (current or {}).get("color") or P.accent
            self.list_dot.delete("all")
            self.list_dot.create_oval(2, 2, 9, 9, fill=color, outline="")
        except Exception:
            pass
        open_state = {}
        if sync_open:
            for iid in self._refs:
                if t.exists(iid):
                    open_state[iid] = bool(t.item(iid, "open"))

        t.delete(*t.get_children())
        self._refs.clear()
        self._hover = None
        self._marked = None

        def insert_item(parent, it, items):
            kids = it.get("children") or []
            done = bool(it.get("done"))
            if self.img_off is not None:
                text = " " + (it["text"] or "(未命名)")
                image = self.img_on if done else self.img_off
            else:
                text = "{} {}".format(BOX_ON if done else BOX_OFF,
                                      it["text"] or "(未命名)")
                image = None
            if kids:
                d, n = leaf_stats(it)
                text += "  ·  {}/{}".format(d, n)
                tag = "group_done" if done else "group"
            else:
                tag = "item_done" if done else "item"
            note = (it.get("note") or "").strip()
            if note:
                text += "  \u270e"
            iid = it["id"]
            if iid in open_state:
                it["open"] = open_state[iid]
            options = {"iid": iid, "text": text, "tags": (tag,),
                       "open": it.get("open", True),
                       "values": ("\U0001F4CC",) if it.get("pinned") else ("",)}
            if image is not None:
                options["image"] = image
            t.insert(parent, "end", **options)
            self._refs[iid] = {"item": it, "list": items}
            for kid in self.pinned_first(kids):
                insert_item(iid, kid, kids)

        roots = self.ordered_roots()
        if self.sort_mode == "time":
            shown_day = None
            for it in roots:
                day = self.item_time(it)[:10]
                if day != shown_day:
                    shown_day = day
                    t.insert("", "end", iid="__sep__" + (day or "none"),
                             tags=("sep",), text="  " + self.format_day(day))
                insert_item("", it, self.store.items)
        else:
            for it in roots:
                insert_item("", it, self.store.items)
        if not t.get_children():
            t.insert("", "end", iid="__empty__", tags=("empty",),
                     text="  （还没有已完成的任务）" if self.tab == "done"
                     else "  （没有未完成的任务）")
        if sel and t.exists(sel):
            t.focus(sel)
            t.selection_set(sel)

        total = done = 0
        for it, _ in walk(self.store.items):
            if not it.get("children"):
                total += 1
                done += 1 if it.get("done") else 0
        # 页签和顶栏按根条目统计, 跟列表里看到的保持一致
        root_done = sum(1 for it in self.store.items if it.get("done"))
        root_total = len(self.store.items)
        self.lbl_stat.config(
            text="{} 项未完成 · {} 项已完成".format(root_total - root_done, root_done))
        self.update_tabs(root_done, root_total)
        try:
            self.pbar.place_configure(relwidth=(done / total) if total else 0)
        except Exception:
            pass
        self.root.after_idle(self.sync_scroll)

    def sync_scroll(self):
        """内容放得下就把滚动条藏起来, 更干净"""
        try:
            y0, y1 = self.tree.yview()
            need = (y1 - y0) < 0.998
            mapped = bool(self.scroll.winfo_ismapped())
            if need and not mapped:
                self.scroll.pack(side="right", fill="y", before=self.tree)
            elif not need and mapped:
                self.scroll.pack_forget()
        except Exception:
            pass

    def on_tree_configure(self, e):
        # 只有高度变了才重算, 否则滚动条一显示一隐藏会来回抖
        if getattr(self, "_tree_h", None) != e.height:
            self._tree_h = e.height
            self.root.after_idle(self.sync_scroll)

    # ---------------- 操作 ----------------

    def set_open(self, val):
        iid = self.tree.focus()
        ref = self._refs.get(iid)
        if ref:
            ref["item"]["open"] = val

    def on_hover(self, e):
        if self._dragging:
            return
        iid = self.tree.identify_row(e.y)
        if iid == getattr(self, "_hover", None):
            return
        self.clear_hover()
        if iid and iid in self._refs:
            self._hover = iid
            self.tree.item(iid, tags=(self.base_tag(iid) + "_h",))

    def clear_hover(self):
        iid = getattr(self, "_hover", None)
        self._hover = None
        if iid and self.tree.exists(iid):
            self.tree.item(iid, tags=(self.base_tag(iid),))

    def base_tag(self, iid):
        ref = self._refs.get(iid)
        if not ref:
            return "item"
        it = ref["item"]
        if it.get("children"):
            return "group_done" if it.get("done") else "group"
        return "item_done" if it.get("done") else "item"

    # ---------------- 渲染 ----------------

    def normalize(self):
        """组的状态 = 所有子项都完成, 同时维护完成时间"""
        def walk_up(items):
            for it in items:
                kids = it.setdefault("children", [])
                walk_up(kids)
                if not kids:
                    continue
                was_done = bool(it.get("done"))
                now_done = all(k.get("done") for k in kids)
                it["done"] = now_done
                if now_done:
                    if not was_done or not it.get("completed_at"):
                        stamps = [k.get("completed_at") for k in kids
                                  if k.get("completed_at")]
                        it["completed_at"] = max(stamps) if stamps else now_str()
                else:
                    it["completed_at"] = None
        walk_up(self.store.items)

    def toggle(self, iid):
        ref = self._refs.get(iid)
        if not ref:
            return
        item = ref["item"]
        target = not item.get("done")
        stamp = now_str()

        def apply(it):
            it["done"] = target
            if target:
                if not it.get("completed_at"):
                    it["completed_at"] = stamp
            else:
                it["completed_at"] = None
            for k in it.get("children") or []:
                apply(k)

        apply(item)
        self.normalize()
        self.store.save()
        self.refresh()

    def add_top(self):
        if self.collapsed:
            self.set_folded(False)
        self._add_to(self.store.items, "")

    def add_child(self):
        ref = self._refs.get(self.tree.focus())
        if not ref:
            return self.add_top()
        kids = ref["item"].setdefault("children", [])
        ref["item"]["open"] = True
        self._add_to(kids, ref["item"]["id"])

    def add_sibling(self):
        ref = self._refs.get(self.tree.focus())
        if not ref:
            return self.add_top()
        self._add_to(ref["list"], self._parent_of(ref["item"]))

    def _parent_of(self, item):
        for it, _ in walk(self.store.items):
            if item in (it.get("children") or []):
                return it["id"]
        return ""

    def _add_to(self, target_list, parent_iid):
        if self.tab != "pending":
            self.set_tab("pending")
        it = new_item("")
        target_list.append(it)
        self.normalize()
        self.refresh()
        if parent_iid and self.tree.exists(parent_iid):
            self.tree.item(parent_iid, open=True)
        self.tree.selection_set(it["id"])
        self.tree.focus(it["id"])
        self.tree.see(it["id"])
        self.root.after(30, lambda: self.start_edit(it["id"]))

    def delete_selected(self):
        iid = self.tree.focus()
        ref = self._refs.get(iid)
        if not ref:
            return
        item = ref["item"]
        kids = item.get("children") or []
        if kids:
            try:
                self.root.attributes("-topmost", True)
            except Exception:
                pass
            ok = messagebox.askyesno(
                "删除", "删除「{}」及 {} 个子项？".format(item["text"], len(kids)),
                parent=self.root)
            try:
                self.root.attributes("-topmost", bool(self.topmost))
            except Exception:
                pass
            if not ok:
                return
        ref["list"].remove(item)
        self.normalize()
        self.store.save()
        self.refresh()

    def move(self, delta):
        if self.sort_mode == "time":
            return  # 按时间排序时不能手动调顺序
        ref = self._refs.get(self.tree.focus())
        if not ref:
            return
        lst, item = ref["list"], ref["item"]
        i = lst.index(item)
        j = i + delta
        if 0 <= j < len(lst):
            lst[i], lst[j] = lst[j], lst[i]
            self.store.save()
            self.refresh()
            self.tree.focus(item["id"])
            self.tree.selection_set(item["id"])

    def collapse_all(self, val):
        for it, _ in walk(self.store.items):
            if it.get("children"):
                it["open"] = not val
        self.refresh(sync_open=False)

    def toggle_collapse_all(self):
        self.collapse_all(any(it.get("open") for it, _ in walk(self.store.items)
                              if it.get("children")))

    # ---------------- 拖动排序 ----------------

    def on_press(self, e):
        iid = self.tree.identify_row(e.y)
        if self.sort_mode == "time":
            self._drag_src = None  # 按时间排序时禁止拖动
        else:
            self._drag_src = iid
        self._drag_xy = (e.x, e.y)
        self._dragging = False
        self._drop = None
        self._press_box = iid if (iid and self.clicked_box(e.x, e.y)) else None
        self._press_pin = iid if (iid and self.clicked_pin(e.x)) else None

    def clicked_pin(self, x):
        """是不是点在了右边的图钉格子里"""
        try:
            column = self.tree.identify_column(x)
        except Exception:
            return False
        return column == "#1"

    def toggle_pin(self, iid):
        """钉住/取消钉住: 钉住的条目排在同一层最前面"""
        ref = self._refs.get(iid)
        if not ref:
            return
        item = ref["item"]
        item["pinned"] = not item.get("pinned")
        self.store.save()
        self.refresh()
        if self.tree.exists(iid):
            self.tree.focus(iid)
            self.tree.selection_set(iid)
            self.tree.see(iid)

    def on_drag(self, e):
        if not self._drag_src:
            return
        if not self._dragging:
            dx = abs(e.x - self._drag_xy[0])
            dy = abs(e.y - self._drag_xy[1])
            if dy < 6 or dy < dx:  # 竖向拖开一点才算拖动, 否则当普通点击
                return
            self._dragging = True
            self.clear_hover()
            self.show_ghost(self._drag_src)
        self.move_ghost(e.x_root, e.y_root)
        self.autoscroll(e.y)
        self.update_hint(e.y)

    def show_ghost(self, iid):
        """跟着鼠标走的小卡片, 一眼看出在拖什么"""
        ref = self._refs.get(iid)
        if not ref:
            return
        item = ref["item"]
        text = item["text"] or "(未命名)"
        if len(text) > 20:
            text = text[:19] + "\u2026"
        if item.get("children"):
            text = "\u2261 " + text
        try:
            g = tk.Toplevel(self.root)
            g.overrideredirect(True)
            g.attributes("-topmost", True)
            try:
                g.attributes("-alpha", 0.85)
            except Exception:
                pass
            box = tk.Frame(g, bg=P.ghost_bg)
            box.pack()
            ghost_fg = best_text_color(P.ghost_bg)
            tk.Label(box, text=text, bg=P.ghost_bg, fg=ghost_fg,
                     font=self.f_group, padx=12, pady=6).pack()
            self._ghost = g
        except Exception:
            self._ghost = None

    def move_ghost(self, x, y):
        if getattr(self, "_ghost", None) is not None:
            try:
                self._ghost.geometry("+{}+{}".format(x + 16, y + 14))
            except Exception:
                pass

    def hide_ghost(self):
        g = getattr(self, "_ghost", None)
        self._ghost = None
        if g is not None:
            try:
                g.destroy()
            except Exception:
                pass

    def on_release(self, e):
        dragging, src = self._dragging, self._drag_src
        box = getattr(self, "_press_box", None)
        pin = getattr(self, "_press_pin", None)
        self._drag_src = None
        self._dragging = False
        self._press_box = None
        self._press_pin = None
        self.hide_ghost()
        self.hide_hint()
        if dragging:
            if src:
                self.drop(src, self._drop)
            return "break"
        if pin and self.tree.exists(pin):
            # 放到事件之后再做, 免得在树的点击事件里重建整个列表
            self.root.after(0, self.toggle_pin, pin)
            return "break"
        if box and self.tree.exists(box):
            # 放到事件之后再做, 免得在树的点击事件里重建整个列表
            self.root.after(0, self.toggle, box)
            return "break"

    def autoscroll(self, y):
        h = self.tree.winfo_height()
        if y < 22:
            self.tree.yview_scroll(-1, "units")
        elif y > h - 22:
            self.tree.yview_scroll(1, "units")

    def drop_target(self, y):
        """算出松手位置: (父iid, 插入下标, 目标行, 方式 before/after/inside/end)"""
        iid = self.tree.identify_row(y)
        if not iid or iid not in self._refs:
            return "", len(self.store.items), "", "end"
        bbox = self.tree.bbox(iid)
        ref = self._refs[iid]
        item = ref["item"]
        kids = item.get("children") or []
        if not bbox:
            return "", len(self.store.items), "", "end"
        rel = (y - bbox[1]) / max(1, bbox[3])
        if kids and 0.28 <= rel <= 0.72:  # 落在组的中间 -> 收进去当子项
            return iid, len(kids), iid, "inside"
        parent = self.tree.parent(iid)
        idx = ref["list"].index(item)
        if rel < 0.5:
            return parent, idx, iid, "before"
        return parent, idx + 1, iid, "after"

    def update_hint(self, y):
        parent, index, tgt, mode = self.drop_target(y)
        src = self._drag_src
        ok = True
        if tgt and (tgt == src or self.is_ancestor(src, tgt)):
            ok = False
        if not ok:
            self.hide_hint()
            self._drop = None
            return
        self._drop = (parent, index, tgt, mode)
        self.clear_marks()
        if mode == "inside":
            bbox = self.tree.bbox(tgt)
            if bbox:
                self.mark_row(tgt)
                self.hint.place(x=bbox[0] + 2, y=bbox[1] + bbox[3] - 3,
                                width=max(40, self.tree.winfo_width() - 8),
                                height=2)
                self.hint.lift()
            return
        if mode == "end":
            bbox = self.tree.bbox(self.tree.get_children()[-1])
            if bbox:
                yy = bbox[1] + bbox[3]
                self.hint.place(x=4, y=yy, width=max(40, self.tree.winfo_width() - 10),
                                height=2)
                self.hint.lift()
            return
        bbox = self.tree.bbox(tgt)
        if bbox:
            yy = bbox[1] if mode == "before" else bbox[1] + bbox[3] - 1
            self.hint.place(x=bbox[0] + 2, y=yy,
                            width=max(40, self.tree.winfo_width() - 8), height=2)
            self.hint.lift()

    def mark_row(self, iid):
        self._marked = iid
        self.tree.item(iid, tags=("drop_" + self.base_tag(iid),))

    def clear_marks(self):
        iid = getattr(self, "_marked", None)
        self._marked = None
        if iid and self.tree.exists(iid):
            self.tree.item(iid, tags=(self.base_tag(iid),))

    def hide_hint(self):
        try:
            self.hint.place_forget()
        except Exception:
            pass
        self.clear_marks()

    def is_ancestor(self, a, b):
        p = self.tree.parent(b)
        while p:
            if p == a:
                return True
            p = self.tree.parent(p)
        return False

    def drop(self, src, target):
        if not target:
            return
        parent, index, tgt, mode = target
        if tgt and (tgt == src or self.is_ancestor(src, tgt)):
            return
        ref = self._refs.get(src)
        if not ref:
            return
        item, src_list = ref["item"], ref["list"]
        src_index = src_list.index(item)
        if mode == "inside":
            dst_list = self._refs[tgt]["item"].setdefault("children", [])
            dst_index = len(dst_list)
            self._refs[tgt]["item"]["open"] = True
        elif mode == "end":
            dst_list, dst_index = self.store.items, len(self.store.items)
        else:
            dst_list = self._refs[tgt]["list"]
            dst_index = dst_list.index(self._refs[tgt]["item"])
            if mode == "after":
                dst_index += 1
        if src_list is dst_list and dst_index > src_index:
            dst_index -= 1
        src_list.remove(item)
        dst_list.insert(dst_index, item)
        self.normalize()
        self.store.save()
        self.refresh()
        if self.tree.exists(src):
            self.tree.focus(src)
            self.tree.selection_set(src)
            self.tree.see(src)

    # ---------------- 双击便签 ----------------

    def on_double_click(self, e):
        iid = self.tree.identify_row(e.y)
        if not iid:
            return
        if self.clicked_box(e.x, e.y):
            return  # 框上双击不弹便签
        try:
            element = self.tree.identify_element(e.x, e.y)
        except Exception:
            element = ""
        if element == "Treeitem.indicator":
            return  # 双击小三角是展开/折叠
        self.open_note(iid)

    def clicked_box(self, x, y):
        try:
            return self.tree.identify_element(x, y) == "image"
        except Exception:
            return False

    def box_x(self, iid):
        """这一行勾选框的中心 x, 找不到就返回 None"""
        bbox = self.tree.bbox(iid)
        if not bbox:
            return None
        left = bbox[0]
        mid_y = bbox[1] + bbox[3] // 2
        limit = left + min(bbox[2], 240)
        x = left
        while x < limit:
            try:
                element = self.tree.identify_element(x, mid_y)
            except Exception:
                element = ""
            if element == "image":
                return x + 6
            x += 2
        return None

    # ---------------- 测试接口(不碰真实鼠标键盘) ----------------

    def simulate_click(self, iid, on_box=False):
        """等价于用鼠标点这一行, 处理链和真实点击完全一样"""
        bbox = self.tree.bbox(iid)
        if not bbox:
            return False
        mid_y = bbox[1] + bbox[3] // 2
        if on_box:
            x = self.box_x(iid)
        else:
            x = self.row_content_x(iid) + 40
        if x is None:
            return False

        tree_event = FakeEvent(self.tree, x, mid_y)
        root_event = FakeEvent(self.root, x, mid_y)
        self.on_press(tree_event)
        self.on_release(tree_event)
        self.on_any_click(root_event)
        return True

    def simulate_double_click(self, iid):
        """等价于用鼠标双击这一行的文字"""
        bbox = self.tree.bbox(iid)
        if not bbox:
            return False
        mid_y = bbox[1] + bbox[3] // 2
        x = self.row_content_x(iid) + 40

        tree_event = FakeEvent(self.tree, x, mid_y)
        root_event = FakeEvent(self.root, x, mid_y)
        self.on_press(tree_event)
        self.on_release(tree_event)
        self.on_press(tree_event)
        self.on_double_click(tree_event)
        self.on_any_click(root_event)
        self.on_release(tree_event)
        return True

    def row_content_x(self, iid):
        """某一行的正文从哪个 x 开始 (跳过展开箭头和勾选框)"""
        try:
            bbox = self.tree.bbox(iid)
        except Exception:
            return 0
        if not bbox:
            return 0
        left = bbox[0]
        mid_y = bbox[1] + bbox[3] // 2
        limit = left + min(bbox[2], 240)
        first_text = None
        x = left
        while x < limit:
            try:
                element = self.tree.identify_element(x, mid_y)
            except Exception:
                element = ""
            if element == "image":
                return x
            if element == "text" and first_text is None:
                first_text = x
            x += 2
        if first_text is not None:
            return first_text
        return left

    def start_edit(self, iid):
        if self._editor is not None:
            return
        ref = self._refs.get(iid)
        if not ref:
            return
        item = ref["item"]
        bbox = self.tree.bbox(iid)
        if not bbox:
            return

        x, y, w, h = bbox
        start_x = self.row_content_x(iid)
        avail = self.tree.winfo_width() - start_x - 10
        entry = tk.Entry(self.tree, font=self.f_item, bg=P.bg_alt, fg=P.fg,
                         insertbackground=P.accent, relief="flat", bd=0,
                         highlightthickness=1, highlightbackground=P.accent,
                         highlightcolor=P.accent)
        entry.place(x=start_x, y=y, width=max(120, avail), height=h)
        entry.insert(0, item["text"])
        entry.select_range(0, "end")
        entry.focus_set()
        self._editor = entry
        state = {"done": False}

        def finish(commit):
            if state["done"]:
                return
            state["done"] = True
            self._finish_edit = None
            text = entry.get().strip()
            try:
                entry.destroy()
            except Exception:
                pass
            self._editor = None
            if commit and text:
                item["text"] = text
            if text:
                self.store.save()
            else:  # 空文本 = 取消/丢弃新建的空任务
                if item in ref["list"]:
                    ref["list"].remove(item)
                self.store.save()
            self.normalize()
            self.refresh()

        self._finish_edit = finish
        entry.bind("<Return>", lambda ev: finish(True))
        entry.bind("<KP_Enter>", lambda ev: finish(True))
        entry.bind("<Escape>", lambda ev: finish(False))
        entry.bind("<FocusOut>", lambda ev: finish(True))

    def finish_edit(self):
        """退出改名状态(保存当前输入)"""
        f = getattr(self, "_finish_edit", None)
        if f is not None:
            f(True)

    def popup(self, e):
        iid = self.tree.identify_row(e.y)
        if iid:
            self.tree.selection_set(iid)
            self.tree.focus(iid)
        has = bool(iid) and iid in self._refs
        can_move = has and self.sort_mode != "time"
        pinned = False
        if has:
            pinned = bool(self._refs[iid]["item"].get("pinned"))
        m = tk.Menu(self.root, tearoff=0)
        m.add_command(label="新建任务", command=self.add_top)
        m.add_command(label="新建子任务", command=self.add_child, state="normal" if has else "disabled")
        m.add_command(label="重命名", command=lambda: self.start_edit(self.tree.focus()),
                      state="normal" if has else "disabled")
        m.add_separator()
        m.add_command(label="取消钉住" if pinned else "钉到最前",
                      command=lambda: self.toggle_pin(self.tree.focus()),
                      state="normal" if has else "disabled")
        m.add_command(label="上移", command=lambda: self.move(-1),
                      state="normal" if can_move else "disabled")
        m.add_command(label="下移", command=lambda: self.move(1),
                      state="normal" if can_move else "disabled")
        m.add_separator()
        m.add_command(label="删除", command=self.delete_selected,
                      state="normal" if has else "disabled")
        m.add_separator()
        m.add_command(label="全部展开", command=lambda: self.collapse_all(False))
        m.add_command(label="全部折叠", command=lambda: self.collapse_all(True))
        m.tk_popup(e.x_root, e.y_root)

    # ---------------- 窗口形态 ----------------
