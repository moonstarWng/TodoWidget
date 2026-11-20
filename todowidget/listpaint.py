# -*- coding: utf-8 -*-
"""列表自绘

Tk 的 Treeview 只会用 GDI 往"色键背景"上画字, 抗锯齿只能跟色键混色,
压在图片上就是一圈毛边(空心字)。这里换个做法:

- Treeview 继续负责交互(选中、拖拽、键盘、改名), 但颜色全设成色键 —— 看不见
- 列表的底色条和文字由我们自己用 PIL 画进底图(灰度抗锯齿), 文字底下永远
  有一块确切的背景, 所以是实心的

只在图片/渐变皮肤下启用; 纯色主题文字本来就清楚, 保持 Tk 原生渲染。
"""

from PIL import Image, ImageDraw, ImageFont

from .theme import P, hex_to_rgb

# Tk 的点数到像素: 96dpi 下 1pt = 1.333px
DPI_SCALE = 96.0 / 72.0
FONT_DIR = "C:/Windows/Fonts/"
FONT_REG = "msyh.ttc"
FONT_BOLD = "msyhbd.ttc"
FONT_SYMBOL = "seguisym.ttf"

# Treeview 的布局常量(跟 app.build_ui 里的 indent=18 对应)
INDENT = 18
TEXT_BASE = 17
IMAGE_GAP = 16

# 行状态对应的底色(画在文字下面)
BAND_SELECTED = "sel"
BAND_HOVER = "hover"
BAND_GROUP = "group"
BAND_DROP = "drop"


class ListPaintMixin:
    """把列表画进皮肤底图"""

    def list_paint_active(self):
        """现在是不是要用自绘列表(只看配色; 皮肤窗口可能还没建出来)"""
        return self.skin_spec() is not None

    def list_paint_ready(self):
        """自绘模式, 而且皮肤窗口已经在了"""
        return self.list_paint_active() and self.skin_win is not None

    def list_paint_key_out(self):
        """把 Treeview 自己画的东西全变成色键(看不见), 只留交互"""
        if not self.list_paint_active():
            return
        key = self.skin_key()
        try:
            style = ttk_style(self.root)
            style.configure("Todo.Treeview", foreground=key, background=key,
                            fieldbackground=key)
            style.map("Todo.Treeview",
                      foreground=[("selected", key)],
                      background=[("selected", key)])
        except Exception:
            pass
        tags = ("item", "item_h", "item_done", "item_done_h",
                "group", "group_h", "group_done", "group_done_h",
                "empty", "sep", "day")
        for tag in tags:
            try:
                self.tree.tag_configure(tag, foreground=key, background=key)
            except Exception:
                pass
        for tag in tags:
            try:
                self.tree.tag_configure("drop_" + tag, foreground=key,
                                        background=key)
            except Exception:
                pass

    # ---------------- 字体 ----------------
    def list_paint_font(self, tk_font, bold=False):
        """按 Tk 字体挑一个等效的 PIL 字体(缓存)

        :param tk_font: Tk 的 font 对象
        :param bold: 要不要粗体
        """
        try:
            points = abs(int(tk_font.actual("size")))
        except Exception:
            points = 10
        key = (points, bool(bold))
        cached = self._list_fonts.get(key)
        if cached is not None:
            return cached
        base = int(round(points * DPI_SCALE))
        name = FONT_BOLD if bold else FONT_REG
        font = None
        for size in (base, base + 1, base - 1, base + 2):
            try:
                font = ImageFont.truetype(FONT_DIR + name, size, index=1)
                break
            except Exception:
                continue
        if font is None:
            try:
                font = ImageFont.load_default()
            except Exception:
                return None
        self._list_fonts[key] = font
        return font

    # ---------------- 绘制 ----------------
    def list_paint_style_of(self, iid):
        """这一行用什么字色/字体/底色

        :param iid: 行 id
        """
        try:
            tags = self.tree.item(iid, "tags") or ()
        except Exception:
            tags = ()
        tag = tags[0] if tags else "item"
        if tag in ("group",):
            return {"font": self.f_group_skin, "fg": P.group,
                    "band": BAND_GROUP}
        if tag in ("group_done",):
            return {"font": self.f_group_skin_done, "fg": P.done,
                    "band": BAND_GROUP}
        if tag == "item_done":
            return {"font": self.f_item_skin_done, "fg": P.done, "band": None}
        if tag in ("sep", "day"):
            return {"font": self.f_small_skin, "fg": P.fg_dim, "band": None}
        if tag == "empty":
            return {"font": self.f_item, "fg": P.fg_faint, "band": None}
        return {"font": self.f_item_skin, "fg": P.fg, "band": None}

    def list_paint_depth(self, iid):
        """这一行在第几层(根行是 0)

        :param iid: 行 id
        """
        depth = 0
        try:
            node = self.tree.parent(iid)
            while node:
                depth += 1
                node = self.tree.parent(node)
        except Exception:
            return 0
        return depth

    def list_paint_text_x(self, iid, bbox):
        """这一行正文从哪个 x 开始

        Treeview 里现在不放文字(免得叠一层毛边字), 所以按缩进规则算:
        `17 + 层数*18`, 有勾选框再往后让 16px。

        :param iid: 行 id
        :param bbox: 这一行的 bbox
        """
        depth = self.list_paint_depth(iid)
        has_image = False
        try:
            has_image = bool(self.tree.item(iid, "image"))
        except Exception:
            has_image = False
        x = bbox[0] + TEXT_BASE + depth * INDENT
        if has_image:
            x += IMAGE_GAP
        return x

    def list_paint_rows(self):
        """当前可见的行(按显示顺序)"""
        rows = []
        try:
            base_x = self.tree.winfo_rootx() - self.root.winfo_rootx()
            base_y = self.tree.winfo_rooty() - self.root.winfo_rooty()
        except Exception:
            return rows

        def walk(parent):
            for iid in self.tree.get_children(parent):
                rows.append(iid)
                walk(iid)

        try:
            walk("")
        except Exception:
            return rows
        return [(iid, base_x, base_y) for iid in rows]

    def list_paint_draw(self, image):
        """把列表内容画到图上(底色条 + 文字 + 分组三角 + 置顶标记)

        :param image: 已经有底图/膜的那张图(RGB)
        """
        if not self.list_paint_active():
            return image
        try:
            draw = ImageDraw.Draw(image, "RGBA")
            focus = self.tree.focus()
            selected = set(self.tree.selection())
            hover = self._hover
            drop = getattr(self, "_marked", None)
            for iid, off_x, off_y in self.list_paint_rows():
                bbox = self.tree.bbox(iid)
                if not bbox:
                    continue
                left = bbox[0] + off_x
                top = bbox[1] + off_y
                width = bbox[2]
                height = bbox[3]
                if top + height < 0 or top > image.height:
                    continue
                style = self.list_paint_style_of(iid)
                style["bold"] = self.list_paint_is_bold(style["font"])
                # 底色条
                band = style["band"]
                color = None
                alpha = 255
                if iid in selected:
                    color = hex_to_rgb(P.sel)
                elif iid == hover:
                    color = hex_to_rgb(P.hover)
                elif drop is not None and iid == drop:
                    # 拖动时落在哪一行: 淡淡铺一层强调色
                    color = hex_to_rgb(P.accent)
                    alpha = 90
                elif band == BAND_GROUP:
                    color = hex_to_rgb(P.group_bg)
                    alpha = 210
                if color is not None:
                    draw.rectangle([left, top, left + width - 1, top + height - 1],
                                   fill=(color[0], color[1], color[2], alpha))
                # 分组三角
                if band == BAND_GROUP:
                    self.list_paint_triangle(draw, iid, left, top, height,
                                             style["fg"])
                # 正文
                label = (self._row_text.get(iid) or "").strip()
                if label:
                    font = self.list_paint_font(style["font"], style["bold"])
                    if font is not None:
                        try:
                            ascent, descent = font.getmetrics()
                        except Exception:
                            ascent, descent = 14, 4
                        text_x = self.list_paint_text_x(iid, bbox) + off_x
                        text_y = top + max(0, (height - (ascent + descent)) // 2)
                        self.list_paint_text(draw, text_x, text_y + ascent, label,
                                             style["font"], style["bold"],
                                             style["fg"])
                # 置顶的小图钉
                self.list_paint_pin(draw, iid, left, top, width, height)
        except Exception:
            pass
        return image

    def list_paint_triangle(self, draw, iid, left, top, height, color):
        """分组行左边的展开三角

        :param draw: ImageDraw
        :param iid: 行 id
        :param left: 行左边界
        :param top: 行上边界
        :param height: 行高
        :param color: 颜色
        """
        try:
            is_open = bool(self.tree.item(iid, "open"))
        except Exception:
            return
        cx = left + TEXT_BASE + self.list_paint_depth(iid) * INDENT - 11
        cy = top + height // 2
        if is_open:
            points = [(cx - 4, cy - 2), (cx + 4, cy - 2), (cx, cy + 3)]
        else:
            points = [(cx - 2, cy - 4), (cx + 3, cy), (cx - 2, cy + 4)]
        draw.polygon(points, fill=color)

    def list_paint_note(self, draw, x, baseline):
        """便签标记(小方块 + 一道斜线), 备用

        :param draw: ImageDraw
        :param x: 左边起点
        :param baseline: 文字基线
        """
        try:
            color = hex_to_rgb(P.fg_dim)
            top = baseline - 8
            draw.rectangle([x, top, x + 6, top + 7], outline=color, width=1)
            draw.line([x + 2, top + 2, x + 4, top + 4], fill=color, width=1)
            draw.line([x + 4, top + 2, x + 2, top + 4], fill=color, width=1)
        except Exception:
            pass

    def list_paint_has_glyph(self, font, ch):
        """这个字体里有没有这个字符(拿私用区画出来的方框当参照)

        :param font: PIL 字体
        :param ch: 单个字符
        """
        key = (id(font), ch)
        cached = self._glyph_ok.get(key)
        if cached is not None:
            return cached
        try:
            ref = font.getmask("\ue000")
            got = font.getmask(ch)
            ok = (got.size, bytes(got)) != (ref.size, bytes(ref))
        except Exception:
            ok = False
        self._glyph_ok[key] = ok
        return ok

    def list_paint_is_bold(self, tk_font):
        """这个 Tk 字体是不是粗体

        :param tk_font: Tk 字体对象
        """
        try:
            return str(tk_font.actual("weight")) == "bold"
        except Exception:
            return False

    def list_paint_px(self, tk_font):
        """Tk 字体的点数换算成像素大小

        :param tk_font: Tk 字体对象
        """
        try:
            points = abs(int(tk_font.actual("size")))
        except Exception:
            points = 10
        return max(8, int(round(points * DPI_SCALE)))

    def list_paint_char_font(self, ch, tk_font, bold):
        """给一个字符挑字体: 雅黑没有就用 Segoe UI Symbol

        :param ch: 单个字符
        :param tk_font: Tk 字体对象
        :param bold: 是否粗体
        """
        primary = self.list_paint_font(tk_font, bold)
        if primary is None or self.list_paint_has_glyph(primary, ch):
            return primary
        size = self.list_paint_px(tk_font)
        key = ("sym", size)
        cached = self._list_fonts.get(key)
        if cached is not None:
            return cached
        try:
            font = ImageFont.truetype(FONT_DIR + FONT_SYMBOL, size)
        except Exception:
            font = primary
        self._list_fonts[key] = font
        return font

    def list_paint_text(self, draw, x, baseline, text, tk_font, bold, color):
        """画一行文字; 雅黑里缺的符号自动改用符号字体

        :param draw: ImageDraw
        :param x: 起点
        :param baseline: 基线 y
        :param text: 文字
        :param tk_font: Tk 字体对象
        :param bold: 是否粗体
        :param color: 颜色
        """
        primary = self.list_paint_font(tk_font, bold)
        if primary is None:
            return
        missing = False
        for ch in text:
            if not self.list_paint_has_glyph(primary, ch):
                missing = True
                break
        if not missing:
            draw.text((x, baseline), text, font=primary, fill=color,
                      anchor="ls")
            return
        cursor = x
        for ch in text:
            font = self.list_paint_char_font(ch, tk_font, bold) or primary
            try:
                draw.text((cursor, baseline), ch, font=font, fill=color,
                          anchor="ls")
                cursor += font.getlength(ch)
            except Exception:
                continue

    def list_paint_pin(self, draw, iid, left, top, width, height):
        """置顶标记(用系统彩色 emoji 画图钉)

        :param draw: ImageDraw
        :param iid: 行 id
        :param left: 行左边界
        :param top: 行上边界
        :param width: 行宽
        :param height: 行高
        """
        ref = self._refs.get(iid)
        if not ref or not (ref.get("item") or {}).get("pinned"):
            return
        font = self._list_fonts.get("emoji")
        if font is None:
            try:
                font = ImageFont.truetype(FONT_DIR + "seguiemj.ttf", 13)
            except Exception:
                font = None
            self._list_fonts["emoji"] = font
        if font is None:
            return
        try:
            draw.text((left + width - 22, top + height // 2 + 1), "\U0001F4CC",
                      font=font, anchor="lm", embedded_color=True)
        except Exception:
            pass

    # ---------------- 触发 ----------------
    def list_paint_later(self):
        """过一会儿重画一次列表(合并同一轮里的多次请求)"""
        if not self.list_paint_ready() or getattr(self, "_menu_open", False):
            return
        if getattr(self, "_list_paint_job", None) is not None:
            return
        self._list_paint_job = self.root.after_idle(self.list_paint_now)

    def list_paint_now(self):
        """立刻重画列表(只重合成, 不重新裁底图)"""
        self._list_paint_job = None
        if not self.list_paint_ready() or getattr(self, "_menu_open", False):
            return
        if self._skin_base is None:
            self.reload_skin_image(force=True)
            return
        self.skin_push_image(self.compose_skin(self._skin_base))


def ttk_style(root):
    """拿 ttk 的 Style 对象(单独拆出来, 免得每次 import)

    :param root: 任意 Tk 窗口
    """
    from tkinter import ttk
    return ttk.Style(root)
