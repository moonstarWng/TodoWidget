# -*- coding: utf-8 -*-
"""一小套补间动画

Tk 自己只有 after(), 没有动画框架。这里不引第三方库, 就补两个东西:

1. 时间驱动的补间: 进度按"真实过了多少毫秒"算, 而不是"每 16ms 走一步"。
   事件循环一忙, 步进动画就会一顿一顿的, 按时间算就不会。
2. 几条常用的缓动曲线(缓出/缓入缓出), 起步和收尾都不生硬。

用法::

    tween = Tween(root, 0.25, on_frame=step, on_done=done)
    tween.start()      # 帧回调里拿到的是 0~1 的(已缓动)进度
    tween.stop()       # 中途不想要了
"""

import time


def _clamp(value):
    """把进度卡在 0~1 之间

    :param value: 原始进度
    """
    return max(0.0, min(1.0, value))


def linear(progress):
    """匀速, 一般只在拼曲线时用

    :param progress: 0~1 的进度
    """
    return _clamp(progress)


def ease_out_cubic(progress):
    """三次缓出: 起步快、收尾慢, 适合"变化一下就停"的场景

    :param progress: 0~1 的进度
    """
    value = _clamp(progress)
    return 1.0 - (1.0 - value) ** 3


def ease_in_cubic(progress):
    """三次缓入: 起步慢、收尾快

    :param progress: 0~1 的进度
    """
    value = _clamp(progress)
    return value ** 3


def ease_in_out_cubic(progress):
    """三次缓入缓出: 两头慢中间快, 淡入淡出最常用

    :param progress: 0~1 的进度
    """
    value = _clamp(progress)
    if value < 0.5:
        return 4.0 * value ** 3
    return 1.0 - ((-2.0 * value + 2.0) ** 3) / 2.0


def ease_out_quint(progress):
    """五次缓出: 比三次更"冲", 收尾更软

    :param progress: 0~1 的进度
    """
    value = _clamp(progress)
    return 1.0 - (1.0 - value) ** 5


def mix_hex(color_a, color_b, ratio):
    """两个颜色按比例混: ratio=0 得到 a, 1 得到 b

    :param color_a: 颜色 a, 形如 '#1b1d24'
    :param color_b: 颜色 b
    :param ratio: 混合比例
    """
    a = _hex_to_rgb(color_a)
    b = _hex_to_rgb(color_b)
    parts = []
    for index in range(3):
        parts.append(int(round(a[index] + (b[index] - a[index]) * _clamp(ratio))))
    return "#{:02x}{:02x}{:02x}".format(*parts)


def _hex_to_rgb(value):
    """'#1b1d24' -> (27, 29, 36), 解析失败就当蓝色

    :param value: 颜色字符串
    """
    text = str(value or "").lstrip("#")
    if len(text) != 6:
        return (91, 156, 255)
    try:
        return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))
    except ValueError:
        return (91, 156, 255)


class Tween:
    """按真实时间推一个 0~1 的进度, 每帧回调一次

    帧间隔默认 8ms(约 120fps), Tk 撑得住; 有一点延迟也能靠时间修正回来,
    不会像固定步数那样越跑越慢。
    """

    def __init__(self, root, duration, on_frame, on_done=None,
                 easing=ease_out_cubic, interval=8):
        """
        :param root: 用来排 after 的 Tk 窗口
        :param duration: 总时长(秒)
        :param on_frame: 每帧回调, 参数是缓动后的进度 0~1
        :param on_done: 跑完后的回调
        :param easing: 缓动曲线
        :param interval: 帧间隔(毫秒)
        """
        self.root = root
        self.duration = max(0.01, float(duration))
        self.on_frame = on_frame
        self.on_done = on_done
        self.easing = easing or linear
        self.interval = max(1, int(interval))
        self.job = None
        self._started = None

    def start(self):
        """开跑"""
        self.stop()
        self._started = time.perf_counter()
        self.on_frame(0.0)
        self.job = self.root.after(self.interval, self._tick)

    def stop(self):
        """停掉, 不会再回调"""
        if self.job is not None:
            try:
                self.root.after_cancel(self.job)
            except Exception:
                pass
            self.job = None

    def _tick(self):
        """算这一帧的进度并回调"""
        self.job = None
        if self._started is None:
            return
        elapsed = time.perf_counter() - self._started
        progress = _clamp(elapsed / self.duration)
        try:
            self.on_frame(self.easing(progress))
        except Exception:
            self._started = None
            return
        if progress >= 1.0:
            self._started = None
            if self.on_done is not None:
                self.on_done()
            return
        # 按剩余时间挑一个不超过 interval 的等待, 别为了凑帧把尾巴拖长
        rest = int(round((self.duration - elapsed) * 1000))
        self.job = self.root.after(max(1, min(self.interval, rest)), self._tick)
