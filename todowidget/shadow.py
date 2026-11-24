# -*- coding: utf-8 -*-
"""给无边框窗口加一层柔和阴影

无边框窗口没有系统阴影, 这里单独开一个不接收鼠标的分层窗口垫在下面,
画一块模糊过的圆角黑块, 看着就有"浮起来"的感觉。
"""

import ctypes
import time
from ctypes import wintypes

import tkinter as tk

try:
    from PIL import Image, ImageDraw, ImageFilter
except Exception:
    Image = None

WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000


class _BitmapHeader(ctypes.Structure):
    """UpdateLayeredWindow 用的 DIB 头"""

    _fields_ = [
        ("biSize", ctypes.c_uint32),
        ("biWidth", ctypes.c_int32),
        ("biHeight", ctypes.c_int32),
        ("biPlanes", ctypes.c_uint16),
        ("biBitCount", ctypes.c_uint16),
        ("biCompression", ctypes.c_uint32),
        ("biSizeImage", ctypes.c_uint32),
        ("biXPelsPerMeter", ctypes.c_int32),
        ("biYPelsPerMeter", ctypes.c_int32),
        ("biClrUsed", ctypes.c_uint32),
        ("biClrImportant", ctypes.c_uint32),
    ]


class _BitmapInfo(ctypes.Structure):
    """DIB 头 + 调色板占位"""

    _fields_ = [("bmiHeader", _BitmapHeader),
                ("bmiColors", ctypes.c_uint32 * 3)]


class _BlendFunction(ctypes.Structure):
    """UpdateLayeredWindow 的混合参数"""

    _fields_ = [("BlendOp", ctypes.c_ubyte),
                ("BlendFlags", ctypes.c_ubyte),
                ("SourceConstantAlpha", ctypes.c_ubyte),
                ("AlphaFormat", ctypes.c_ubyte)]


def _api():
    """声明 UpdateLayeredWindow 那套函数的类型(64 位句柄不能按 int 传)

    :return: (user32, gdi32)
    """
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    user32.GetParent.restype = ctypes.c_void_p
    user32.GetParent.argtypes = [ctypes.c_void_p]
    user32.GetWindowLongW.restype = ctypes.c_long
    user32.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]
    user32.SetWindowLongW.restype = ctypes.c_long
    user32.SetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                      ctypes.c_long]
    user32.GetDC.restype = ctypes.c_void_p
    user32.GetDC.argtypes = [ctypes.c_void_p]
    user32.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    user32.UpdateLayeredWindow.restype = ctypes.c_bool
    user32.UpdateLayeredWindow.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(wintypes.POINT),
        ctypes.POINTER(wintypes.SIZE), ctypes.c_void_p,
        ctypes.POINTER(wintypes.POINT), ctypes.c_uint32,
        ctypes.POINTER(_BlendFunction), ctypes.c_uint32]
    user32.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                    ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int,
                                    ctypes.c_uint32]
    gdi32.CreateCompatibleDC.restype = ctypes.c_void_p
    gdi32.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
    gdi32.CreateDIBSection.restype = ctypes.c_void_p
    gdi32.CreateDIBSection.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(_BitmapInfo), ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p, ctypes.c_uint32]
    gdi32.SelectObject.restype = ctypes.c_void_p
    gdi32.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
    gdi32.DeleteDC.argtypes = [ctypes.c_void_p]
    return user32, gdi32


def shadow_pad(blur):
    """阴影图四周要留多少白

    高斯模糊的尾巴有好几倍 sigma, 留白不够就会在图片边界上被一刀切,
    看着就是阴影外圈有一条硬边。

    :param blur: 扩散强度
    """
    return max(4, int(round(float(blur) * 3)))


def _rgba(color, alpha=255):
    """颜色字符串转 RGBA 元组

    :param color: #rrggbb
    :param alpha: 不透明度
    """
    from .theme import hex_to_rgb
    red, green, blue = hex_to_rgb(color)
    return (red, green, blue, int(alpha))


def shadow_image(width, height, radius, blur, strength, card=None, ring=None,
                 offset=5):
    """生成一张带模糊圆角的阴影图(RGBA), 可以再叠一张抗锯齿的卡片

    :param width: 窗口宽
    :param height: 窗口高
    :param radius: 窗口圆角半径
    :param blur: 模糊半径(也就是四周留白的宽度)
    :param strength: 影子不透明度 0~1
    :param card: 卡片填充色(跟窗口底色一样), 不传就不画
    :param ring: 卡片描边色(跟窗口边框一样), 不传就不描
    :param offset: 影子往下偏多少像素, 看着更像浮起来
    """
    if Image is None:
        return None
    pad = shadow_pad(blur)
    sigma = max(1.0, float(blur) * 0.7)
    total_w = width + pad * 2
    total_h = height + pad * 2 + max(0, int(offset))
    mask = Image.new("L", (total_w, total_h), 0)
    drawer = ImageDraw.Draw(mask)
    drawer.rounded_rectangle(
        [pad, pad + max(0, int(offset)), pad + width - 1,
         pad + height - 1 + max(0, int(offset))],
        radius=max(1, int(radius)), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(sigma))
    alpha = mask.point(lambda value: int(value * max(0.0, min(1.0, strength))))
    layer = Image.new("RGBA", (total_w, total_h), (0, 0, 0, 255))
    layer.putalpha(alpha)
    if card is None:
        return layer
    # 卡片: 超采样几倍再缩回来, 圆角才没有锯齿。
    # 填色往外扩 1px(圆角也 +1): 窗口自己的圆角是 1 位区域切的, 边缘那一排
    # 像素会顶到弧线外面; 卡片大一圈才盖得住这些台阶
    over = 3
    big = Image.new("RGBA", (total_w * over, total_h * over),
                    (0, 0, 0, 0))
    painter = ImageDraw.Draw(big)
    pad2 = max(1, pad - 1)
    fill_box = [pad2 * over, pad2 * over, (pad + width) * over,
                (pad + height) * over]
    painter.rounded_rectangle(
        fill_box, radius=(max(1, int(radius)) + 1) * over,
        fill=_rgba(card))
    if ring:
        box = [pad * over, pad * over, (pad + width) * over - 1,
               (pad + height) * over - 1]
        painter.rounded_rectangle(box, radius=max(1, int(radius)) * over,
                                  outline=_rgba(ring), width=over)
    card_layer = big.resize((total_w, total_h), Image.LANCZOS)
    return Image.alpha_composite(layer, card_layer)


class WindowShadow:
    """跟着某个窗口走的阴影窗口

    :param owner: 被加阴影的窗口
    :param radius: 圆角半径(跟窗口一致)
    :param blur: 阴影往四周扩散多少像素
    :param strength: 不透明度 0~1
    """

    def __init__(self, owner, radius=12, blur=8, strength=0.5,
                 card=None, ring=None, offset=5, anchor=None):
        self.owner = owner
        # anchor: 返回"阴影要压在哪个窗口下面"的函数; 主窗口还有一层皮肤窗口,
        # 阴影必须排到皮肤下面, 夹在中间就会把整块阴影蒙在窗口背景上
        self.anchor = anchor
        self.radius = int(radius)
        self.blur = int(blur)
        self.strength = float(strength)
        self.card = card
        self.ring = ring
        self.offset = int(offset)
        self.win = None
        self._image_size = None
        self._image = None
        self._shown = False
        self._last_rect = None
        # True 时 sync 一律不再显示(收起/展开动画用), 直到 resume()
        self.suspended = False

    def create(self):
        """先把阴影窗口建出来(还没显示)"""
        if self.win is not None:
            return
        try:
            win = tk.Toplevel(self.owner)
            win.withdraw()
            win.overrideredirect(True)
            win.configure(bg="#000000")
            self.win = win
            self._apply_style()
        except Exception as exc:
            print("shadow create failed:", exc)
            self.win = None

    def _apply_style(self):
        """让阴影窗口不抢焦点、不接收鼠标"""
        win = self.win
        if win is None:
            return
        try:
            user32, _gdi32 = _api()
            hwnd = user32.GetParent(win.winfo_id())
            if not hwnd:
                return
            style = user32.GetWindowLongW(hwnd, -20)
            want = (style | WS_EX_LAYERED | WS_EX_TRANSPARENT
                    | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
            if style != want:
                user32.SetWindowLongW(hwnd, -20, want)
        except Exception as exc:
            print("shadow style failed:", exc)

    def sync(self, width=None, height=None, x=None, y=None, quick=False):
        """按窗口当前位置/大小摆好阴影

        :param width: 指定的宽, 不传就用窗口的
        :param height: 指定的高
        :param x: 指定的屏幕横坐标
        :param y: 指定的屏幕纵坐标
        :param quick: 动画每帧用: 不画抗锯齿卡片(画一次要 20 多毫秒, 会拖慢动画)
        """
        owner = self.owner
        win = self.win
        if win is None or Image is None or self.suspended:
            return
        try:
            if owner.state() != "normal":
                self.hide()
                return
            width = int(width or owner.winfo_width())
            height = int(height or owner.winfo_height())
            if width < 4 or height < 4:
                return
            if x is None:
                x = owner.winfo_rootx()
            if y is None:
                y = owner.winfo_rooty()
        except Exception as exc:
            print("shadow sync failed:", exc)
            return
        image = self._cached_image(width, height,
                                   None if quick else self.card)
        if image is None:
            return
        # 位置/大小/内容都没变就别再推一遍图层。Windows 的 z 序变化也会发
        # WM_WINDOWPOSCHANGED, Tk 一律当成 <Configure>, 不挡住的话
        # "同步 → 排 z 序 → 又来 <Configure> → 再同步" 会自己追自己
        rect = (int(width), int(height), int(x), int(y), bool(quick),
                id(image))
        try:
            shown = self._shown and win.state() == "normal"
        except Exception:
            shown = False
        if rect == self._last_rect and shown:
            self._stack_below()
            return
        pad = shadow_pad(self.blur)
        try:
            # 先摆到目标位置再显示: 刚建出来的顶层窗口默认 200x200 在 (0,0),
            # 直接 deiconify 会在屏幕左上角闪一块黑的; 先缩成 1x1 再推图层
            if win.state() != "normal":
                win.geometry("1x1+{}+{}".format(int(x) - pad, int(y) - pad))
                win.deiconify()
                win.update_idletasks()
            self._apply_style()
            if not self._push(image, x - pad, y - pad):
                # 推失败时别把已经显示出来的阴影收掉(会一闪一闪),
                # 只有从来没成功显示过才藏起来, 免得露出黑底
                if not self._shown:
                    win.withdraw()
                return
            topmost = bool(owner.attributes("-topmost"))
            if bool(win.attributes("-topmost")) != topmost:
                win.attributes("-topmost", topmost)
            self._shown = True
            self._last_rect = rect
            self._stack_below()
        except Exception as exc:
            print("shadow show failed:", exc)

    def _cached_image(self, width, height, card="keep"):
        """按窗口大小缓存阴影图(拖动时别每帧重算模糊)

        :param width: 窗口宽
        :param height: 窗口高
        :param card: 卡片颜色, 传 None 就是这张不画卡片
        """
        if card == "keep":
            card = self.card
        key = (int(width), int(height), self.radius, self.blur,
               round(self.strength, 3), card, self.ring, self.offset)
        if key == self._image_size and self._image is not None:
            return self._image
        image = shadow_image(width, height, self.radius, self.blur,
                             self.strength, card, self.ring, self.offset)
        if image is None:
            return None
        self._image_size = key
        self._image = image
        return image

    def _push(self, image, x, y):
        """把阴影图按逐像素透明推给阴影窗口

        :param image: RGBA 阴影图
        :param x: 屏幕横坐标
        :param y: 屏幕纵坐标
        """
        try:
            user32, gdi32 = _api()
            win = self.win
            hwnd = user32.GetParent(win.winfo_id())
            if not hwnd:
                return False
            width, height = image.size
            data = _premultiplied(image)
            screen = user32.GetDC(None)
            memory = gdi32.CreateCompatibleDC(screen)
            header = _BitmapHeader()
            header.biSize = ctypes.sizeof(_BitmapHeader)
            header.biWidth = width
            header.biHeight = -height
            header.biPlanes = 1
            header.biBitCount = 32
            info = _BitmapInfo()
            info.bmiHeader = header
            bits = ctypes.c_void_p()
            bitmap = gdi32.CreateDIBSection(memory, ctypes.byref(info), 0,
                                            ctypes.byref(bits), None, 0)
            if not bitmap:
                gdi32.DeleteDC(memory)
                user32.ReleaseDC(None, screen)
                return False
            ctypes.memmove(bits, data, len(data))
            old = gdi32.SelectObject(memory, bitmap)
            source = wintypes.POINT(0, 0)
            target = wintypes.POINT(int(x), int(y))
            size = wintypes.SIZE(width, height)
            blend = _BlendFunction(0, 0, 255, 1)
            ok = user32.UpdateLayeredWindow(
                hwnd, screen, ctypes.byref(target), ctypes.byref(size),
                memory, ctypes.byref(source), 0, ctypes.byref(blend), 2)
            gdi32.SelectObject(memory, old)
            gdi32.DeleteObject(bitmap)
            gdi32.DeleteDC(memory)
            user32.ReleaseDC(None, screen)
            return bool(ok)
        except Exception as exc:
            print("shadow push failed:", exc)
            return False

    def restack(self):
        """把阴影重新压到该在的位置(皮肤窗口重新排过之后要补一次)"""
        self._stack_below()

    def _stack_below(self):
        """把阴影压到窗口下面(紧贴着它)"""
        try:
            user32, _gdi32 = _api()
            win = self.win
            owner = self.owner
            shadow = user32.GetParent(win.winfo_id())
            target = 0
            if self.anchor is not None:
                try:
                    target = self.anchor() or 0
                except Exception:
                    target = 0
            if not target:
                target = user32.GetParent(owner.winfo_id())
            if not shadow or not target:
                return
            # 已经紧挨着它下面就不用再排: 反复 SetWindowPos 会让它重画/闪
            if user32.GetWindow(target, 2) == shadow:
                return
            no_activate = 0x0010
            user32.SetWindowPos(shadow, target, 0, 0, 0, 0,
                                0x0001 | 0x0002 | no_activate)
        except Exception as exc:
            print("shadow stack failed:", exc)

    def follow(self, owner=None):
        """让阴影跟着窗口的位置/大小/显示状态自动同步

        :param owner: 要跟的窗口, 不传就用建的时候那个
        """
        owner = owner or self.owner
        pending = {"job": None}

        def is_owner(event):
            """这个事件是不是窗口自己的

            子控件的 <Configure>/<Map>/<Unmap> 也会冒到顶层窗口的绑定上,
            不挡掉的话里面翻页、重排都会把阴影重推一遍(看着两个窗口一起闪),
            面板一收(<Unmap>)还会把阴影整个收掉。
            """
            if event is None:
                return True
            return getattr(event, "widget", None) is owner

        def sync_later(event=None):
            if not is_owner(event):
                return
            if self.win is None or pending["job"] is not None:
                return
            pending["job"] = owner.after(16, run_sync)

        def run_sync():
            pending["job"] = None
            self.sync()

        def on_unmap(event=None):
            if not is_owner(event):
                return
            self.hide()

        owner.bind("<Configure>", sync_later, add="+")
        owner.bind("<Map>", sync_later, add="+")
        owner.bind("<Unmap>", on_unmap, add="+")
        owner.after(30, sync_later)

    def suspend(self):
        """先退场, 并且之后的自动同步都别再显示它(收起/展开动画用)"""
        self.suspended = True
        self.hide()

    def resume(self):
        """动画结束: 恢复显示, 按窗口现在的位置/大小重新摆一次"""
        self.suspended = False
        self._last_rect = None
        self.sync()

    def hide(self):
        """藏起来(跟着窗口收起/隐藏)"""
        win = self.win
        if win is None:
            return
        self._shown = False
        self._last_rect = None
        try:
            win.withdraw()
        except Exception as exc:
            print("shadow hide failed:", exc)

    def destroy(self):
        """销毁阴影窗口"""
        win = self.win
        self.win = None
        if win is None:
            return
        try:
            win.destroy()
        except Exception as exc:
            print("shadow destroy failed:", exc)


def _premultiplied(image):
    """RGBA 图转成 alpha 已预乘的 BGRA 字节

    :param image: PIL RGBA 图
    """
    from PIL import ImageChops
    red, green, blue, alpha = image.split()
    red = ImageChops.multiply(red, alpha)
    green = ImageChops.multiply(green, alpha)
    blue = ImageChops.multiply(blue, alpha)
    return Image.merge("RGBA", (blue, green, red, alpha)).tobytes()


def attach_shadow(owner, radius=12, blur=8, strength=0.5, card=None,
                  ring=None, anchor=None):
    """给一个窗口挂上阴影, 位置/大小变了自动跟着走

    :param owner: 目标窗口
    :param radius: 圆角半径
    :param blur: 阴影扩散范围
    :param strength: 不透明度
    :param card: 卡片填充色(补圆角的抗锯齿边)
    :param ring: 卡片描边色
    :param anchor: 返回"阴影要压在哪个窗口下面"的函数
    :return: WindowShadow 实例(失败返回 None)
    """
    shadow = WindowShadow(owner, radius=radius, blur=blur,
                          strength=strength, card=card, ring=ring,
                          anchor=anchor)
    shadow.create()
    if shadow.win is None:
        return None
    shadow.follow(owner)
    return shadow
