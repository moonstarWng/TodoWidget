# -*- coding: utf-8 -*-
"""录制使用演示 GIF

全程用程序接口驱动界面(和真实操作走同一套处理链), 不移动真实鼠标键盘。
演示数据是脚本现编的假数据, 不读取 todo_data.json, 不会暴露任何真实内容。

运行: py -3 record_demo.py
输出: demo.gif
"""

import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import tkinter as tk

from PIL import ImageGrab

from todowidget.app import TodoApp
from todowidget.store import Store, new_item
from todowidget.utils import FakeEvent, TkApp, place_window

APP_DIR = os.path.dirname(os.path.abspath(__file__))
CONF_FILE = os.path.join(APP_DIR, "todo_config.json")
OUT_GIF = os.path.join(APP_DIR, "demo.gif")

WIN_W = 380
WIN_H = 450
WIN_X = 2300
WIN_Y = 140
BOX = (2268, 118, 3112, 702)
SCALE = 0.72
DELAY = 0.09


def item(text, children=None):
    node = new_item(text)
    if children:
        node["children"] = [new_item(c) for c in children]
    return node


def demo_lists():
    """纯虚构的演示数据"""
    main_items = [
        item("新产品上线", ["确认需求文档", "设计稿评审",
                          "灰度发布方案", "上线检查清单"]),
        item("这周的琐事", ["交水电费", "取快递", "预约体检"]),
        item("读一本闲书"),
        item("整理旅行照片"),
    ]
    study_items = [
        item("读书计划", ["《设计模式》第 3 章", "《人类简史》后半本"]),
        item("每周复盘"),
    ]
    food_items = [
        item("买菜", ["牛奶", "鸡蛋", "西红柿"]),
        item("换个咖啡豆"),
    ]
    return [
        {"id": "demo-main", "name": "我的待办", "items": main_items},
        {"id": "demo-study", "name": "学习", "items": study_items},
        {"id": "demo-food", "name": "生活", "items": food_items},
    ]


def main():
    TodoApp.start_tray = lambda self: None
    TodoApp.sink = lambda self: None

    tmp_data = os.path.join(tempfile.gettempdir(), "todo_demo_data.json")
    with open(tmp_data, "w", encoding="utf-8") as f:
        json.dump({"current": "demo-main", "lists": demo_lists()},
                  f, ensure_ascii=False, indent=1)

    conf_backup = None
    if os.path.exists(CONF_FILE):
        with open(CONF_FILE, encoding="utf-8") as f:
            conf_backup = f.read()

    root = TkApp()
    app = TodoApp(root, store=Store(tmp_data))
    root.attributes("-topmost", True)
    root.geometry("{}x{}+{}+{}".format(WIN_W, WIN_H, WIN_X, WIN_Y))

    # 铺一块干净的底, 免得把桌面壁纸录进去
    backdrop = tk.Toplevel(root)
    backdrop.overrideredirect(True)
    backdrop.configure(bg="#eef0f4")
    backdrop.geometry("{}x{}+{}+{}".format(BOX[2] - BOX[0], BOX[3] - BOX[1],
                                           BOX[0], BOX[1]))
    backdrop.lower()

    # 位置可能被 Tk 挪动, 直接用系统接口摆到位
    place_window(root, WIN_X, WIN_Y, WIN_W, WIN_H)
    for _ in range(14):
        root.update()
        time.sleep(0.03)

    print("[setup] 窗口:", root.winfo_rootx(), root.winfo_rooty(),
          root.winfo_width(), root.winfo_height())
    print("[setup] 树:", app.tree.winfo_width(), app.tree.winfo_height(),
          "行数:", len(app._refs))

    frames = []

    def shot(pause=DELAY):
        root.update()
        image = ImageGrab.grab(bbox=BOX, all_screens=True)
        frames.append(image.convert("RGB"))
        time.sleep(pause)

    def hold(seconds):
        count = max(1, int(seconds / DELAY))
        for _ in range(count):
            shot()

    def find(text):
        for iid, ref in app._refs.items():
            if ref["item"]["text"] == text:
                return iid
        return None

    def hover(text, x=140):
        iid = find(text)
        if iid is None:
            return
        box = app.tree.bbox(iid)
        if not box:
            return
        app.on_hover(FakeEvent(app.tree, x, box[1] + box[3] // 2))

    print("[step] 开始")
    hold(0.9)
    print("[step] 1 勾选")

    # 1. 勾选两条子任务, 组的进度跟着走
    hover("设计稿评审")
    shot()
    app.simulate_click(find("设计稿评审"), on_box=True)
    hold(0.5)
    app.simulate_click(find("确认需求文档"), on_box=True)
    hold(0.7)

    print("[step] 2 整组")
    # 2. 整组勾掉 -> 整个组会跑到"已完成"
    app.simulate_click(find("这周的琐事"), on_box=True)
    hold(0.9)

    print("[step] 3 便签")
    # 3. 双击打开便签, 写点 md, 切预览
    target_id = find("灰度发布方案")
    app.simulate_double_click(target_id)
    hold(0.6)
    if app.note_win is None:
        print("[warn] 便签没打开")
    else:
        content = ("# 灰度发布方案\n\n"
                   "- 先放 5% 用户\n"
                   "- 观察 24 小时错误率\n\n"
                   "1. 准备好回滚脚本\n"
                   "2. 通知值班同学\n\n"
                   "参考 https://example.com/release-guide")
        for i in range(0, len(content), 3):
            app.note_text.delete("1.0", "end")
            app.note_text.insert("1.0", content[:i + 3])
            shot(0.05)
        hold(0.4)
        app.note_toggle_mode()
        hold(1.2)
        app.simulate_click(find("读一本闲书"))
        hold(0.6)

    print("[step] 4 页签")
    # 4. 切到已完成, 再切回来
    app.set_tab("done")
    hold(0.9)
    app.set_tab("pending")
    hold(0.5)

    print("[step] 5 拖动")
    # 5. 拖动排序
    src = find("读一本闲书")
    target = find("新产品上线")
    if src and target:
        src_box = app.tree.bbox(src)
        dst_box = app.tree.bbox(target)
        start_y = src_box[1] + src_box[3] // 2
        end_y = dst_box[1] + dst_box[3] // 2
        app.on_press(FakeEvent(app.tree, 140, start_y))
        app.on_drag(FakeEvent(app.tree, 140, start_y + 10))
        steps = 12
        for i in range(1, steps + 1):
            y = start_y + int((end_y - start_y) * i / steps)
            app.on_drag(FakeEvent(app.tree, 140, y))
            shot(0.04)
        app.on_release(FakeEvent(app.tree, 140, end_y))
        hold(0.7)

    print("[step] 6 切换清单")
    # 6. 切换清单(菜单是原生弹窗, 录制时会卡住事件循环, 这里直接演示切换效果)
    app.switch_list("demo-study")
    hold(1.0)
    app.switch_list("demo-main")
    hold(0.6)

    print("[step] 7 折叠")
    # 7. 折叠成一条横杠, 再展开
    app.set_folded(True)
    hold(0.7)
    app.set_folded(False)
    hold(0.9)

    root.destroy()

    if conf_backup is not None:
        with open(CONF_FILE, "w", encoding="utf-8") as f:
            f.write(conf_backup)
    if os.path.exists(tmp_data):
        os.remove(tmp_data)

    size = (int(round((BOX[2] - BOX[0]) * SCALE)),
            int(round((BOX[3] - BOX[1]) * SCALE)))
    small = [frame.resize(size) for frame in frames]
    small[0].save(OUT_GIF, save_all=True, append_images=small[1:],
                  duration=int(DELAY * 1000), loop=0, optimize=True)
    print("帧数:", len(small), "尺寸:", size)
    print("输出:", OUT_GIF,
          round(os.path.getsize(OUT_GIF) / 1024 / 1024, 2), "MB")


if __name__ == "__main__":
    main()
