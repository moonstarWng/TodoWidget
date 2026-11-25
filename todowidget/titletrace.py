# -*- coding: utf-8 -*-
"""临时诊断(用完就删): 盯左上角标题的颜色/文字变化, 只在变化时写日志

数据目录里有 trace.on 才启动。
"""

import os
import time

from .paths import DATA_DIR

MARK = os.path.join(DATA_DIR, "trace.on")
LOG = os.path.join(DATA_DIR, "title.log")

_last = {"key": None}


def _log(text):
    try:
        with open(LOG, "a", encoding="utf-8") as out:
            out.write("%s %s\n" % (time.strftime("%H:%M:%S"), text))
    except Exception:
        pass


def _rows(app):
    """顶栏/底栏里所有带文字的控件现在的样子"""
    rows = []
    for area, top in (("顶", getattr(app, "_head", None)),
                      ("底", getattr(app, "_foot", None))):
        if top is None:
            continue
        try:
            rows.append((area, "容器", str(top.cget("bg")).lower(),
                         str(top.winfo_manager()), top.winfo_width()))
        except Exception:
            continue

        def walk(widget, depth=0):
            if depth > 2:
                return
            for child in widget.winfo_children():
                try:
                    text = str(child.cget("text"))
                except Exception:
                    text = None
                if text is None:
                    walk(child, depth + 1)
                    continue
                try:
                    fg = str(child.cget("fg")).lower()
                except Exception:
                    fg = "?"
                try:
                    bg = str(child.cget("bg")).lower()
                except Exception:
                    bg = "?"
                rows.append((area, text[:8], "fg=%s bg=%s" % (fg, bg),
                             child.winfo_manager(), child.winfo_width()))
                walk(child, depth + 1)

        walk(top)
    return rows


def _stamp(app, tag):
    """记一次顶栏/底栏的样子(有变化才写)"""
    try:
        key = str(app.skin_key()).lower()
        rows = _rows(app)
        state = tuple(rows)
        if state == _last["key"]:
            return
        old_rows = {row[:2]: row for row in (_last.get("rows") or [])}
        _last["key"] = state
        _last["rows"] = rows
        for row in rows:
            if old_rows.get(row[:2]) == row:
                continue
            _log("%-12s %s %-8s %-40s %-6s w=%-4s 色键=%s 宽=%s 上色=%s 渐变=%s"
                 % (tag, row[0], row[1], row[2], row[3], row[4], key,
                    app.root.winfo_width(), app.bars_split, app.bars_grad))
    except Exception as exc:
        _log("采样失败: %s" % exc)


def start(app):
    """有 trace.on 就挂上采样和关键函数打点"""
    try:
        if not os.path.exists(MARK):
            return
        with open(LOG, "a", encoding="utf-8") as out:
            out.write("==== 启动 %s\n" % time.strftime("%H:%M:%S"))
    except Exception:
        return

    for name in ("fade_title", "stop_title_fade", "update_title"):
        fn = getattr(app.__class__, name, None)
        if fn is None or getattr(fn, "_traced", False):
            continue

        def make(fn=fn, name=name):
            def inner(self, *a, **kw):
                _stamp(self, "进入" + name)
                result = fn(self, *a, **kw)
                _stamp(self, "离开" + name)
                return result
            inner._traced = True
            return inner

        setattr(app.__class__, name, make())

    def tick():
        _stamp(app, "定时")
        try:
            app.root.after(60, tick)
        except Exception:
            pass

    app.root.after(200, tick)
