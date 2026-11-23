# -*- coding: utf-8 -*-
"""自检: 直接调用界面里公开的处理链, 不碰真实鼠标键盘"""

import os
import time

from . import screens, updater
from .app import TodoApp
from .paths import APP_DIR, CONF_FILE
from .store import Store, new_item
from .utils import FakeEvent, TkApp


# 自检要看的 Delphi 源码位置(可用环境变量 TUBEPRO_TRUNK 覆盖), 找不到就跳过源码检查
TUBEPRO_TRUNK = os.environ.get(
    "TUBEPRO_TRUNK",
    r"D:\Code\NC\CurrentWork\04_TubePro\TubePro_trunk2",
)


def read_source(path):
    """读 GBK / UTF-8 源码文本, 文件不存在返回空串

    :param path: 源码文件路径
    """
    if not os.path.exists(path):
        return ""
    for encoding in ("utf-8", "gbk"):
        try:
            with open(path, encoding=encoding) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
    return ""


def window_region(widget):
    """窗口现在设了裁剪区域没有(0 = 没有)

    :param widget: 任意 Tk 窗口
    """
    import ctypes
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    user32.GetParent.restype = ctypes.c_void_p
    hwnd = user32.GetParent(widget.winfo_id())
    handle = gdi32.CreateRectRgn(0, 0, 1, 1)
    kind = user32.GetWindowRgn(hwnd, handle)
    gdi32.DeleteObject(handle)
    return kind

def run_selftest():
    """自检: 直接调用界面里公开的处理链, 不碰真实鼠标键盘

    用法: py -3 todo.py --selftest
    """
    data_path = os.path.join(APP_DIR, "todo_selftest_data.db")
    if os.path.exists(data_path):
        os.remove(data_path)

    conf_backup = None
    if os.path.exists(CONF_FILE):
        with open(CONF_FILE, encoding="utf-8") as f:
            conf_backup = f.read()

    TodoApp.start_tray = lambda self: None
    root = TkApp()
    app = TodoApp(root, store=Store(data_path, import_json=False))
    app.sort_mode = "manual"   # 自检不受本机排序设置影响
    app.set_tab("pending")
    results = []

    def check(name, ok):
        results.append((name, bool(ok)))

    def settle(times=5):
        for _ in range(times):
            root.update()
            time.sleep(0.02)

    def settle_anim():
        """等收起 / 展开动画跑完"""
        for _ in range(80):
            root.update()
            if app._fold_job is None:
                settle(2)
                return
            time.sleep(0.02)

    def find(text):
        for iid, ref in app._refs.items():
            if ref["item"]["text"] == text:
                return iid
        return None

    if app.collapsed:
        app.set_folded(False)
        settle_anim()
    settle(8)

    # 皮肤模式下页签文字要画进图里(Tk 文本压在图上会一圈毛边/空心)
    tab_kinds = [app.tab_indicator.type(item)
                 for item in app.tab_indicator.find_all()]
    check("页签文字在皮肤下走自绘",
          (not app.list_paint_active()) or ("text" not in tab_kinds))

    # 显示器枚举不能漏屏(64 位句柄被截断时双屏只剩主屏)
    import ctypes
    system_count = ctypes.windll.user32.GetSystemMetrics(80)
    check("显示器枚举数量和系统一致",
          len(screens.monitors()) == system_count)
    first_leaf = None
    second_leaf = None
    first_group = None
    any_leaf = None
    for iid, ref in app._refs.items():
        item = ref["item"]
        if item.get("children"):
            if first_group is None:
                first_group = iid
            continue
        if any_leaf is None:
            any_leaf = iid
        if item.get("done"):
            continue
        if first_leaf is None:
            first_leaf = iid
        elif second_leaf is None:
            second_leaf = iid

    if first_leaf is None:
        first_leaf = any_leaf
    if second_leaf is None:
        second_leaf = any_leaf

    target = first_leaf
    target_item = app._refs[target]["item"]
    app.simulate_double_click(target)
    settle()
    check("双击弹出便签", bool(app.notes))

    # 皮肤窗口转发双击: 图片皮肤下列表区是透明的, 点击先落在皮肤窗口上,
    # 那边只有两次独立的 <Button-1>, 得自己判双击再转给列表
    app.close_note()
    settle()
    app.tree.see(target)
    settle(2)
    bbox = app.tree.bbox(target)
    skin_ok = False
    if bbox:
        screen_x = app.tree.winfo_rootx() + app.row_content_x(target) + 40
        screen_y = app.tree.winfo_rooty() + bbox[1] + bbox[3] // 2

        def skin_click():
            event = FakeEvent(app.root, 0, 0)
            event.x_root = screen_x
            event.y_root = screen_y
            app.forward_skin_event(event, "<Button-1>")
            app.forward_skin_event(event, "<ButtonRelease-1>")

        skin_click()
        time.sleep(0.1)
        settle(2)
        skin_click()
        settle()
        skin_ok = bool(app.notes)
    check("皮肤窗口转发的双击也能弹出便签", skin_ok)

    state = app.notes.get(target_item["id"])
    if state is not None:
        state["text"].insert("1.0", "自检写入的备注")
    time.sleep(0.45)  # 越过"刚打开不关"的保护
    app.simulate_click(second_leaf)
    settle()
    note_text = target_item.get("note")
    closed = not app.notes
    check("点别处关闭便签并保存内容", closed and note_text == "自检写入的备注")

    # 钉在桌面上的便签: 点别处不会被收走
    app.simulate_double_click(target)
    settle()
    state = app.notes.get(target_item["id"])
    pinned_ok = False
    keep_ok = False
    if state is not None:
        app.toggle_note_pin(state)
        pinned_ok = bool(target_item.get("note_pinned"))
        settle()
        try:
            on_top = bool(int(state["win"].attributes("-topmost")))
        except Exception:
            on_top = False
        time.sleep(0.45)
        app.simulate_click(second_leaf)
        settle()
        keep_ok = bool(app.notes)
        app.close_note()
        settle()
    check("便签可以钉在最前面", pinned_ok and on_top)
    check("钉住的便签不会点别处就消失", keep_ok)

    state_before = target_item["done"]
    app.simulate_click(target, on_box=True)
    settle()
    state_after = target_item["done"]
    check("点勾选框可以切换完成", state_before != state_after)

    # 分组可能刚才整组完成了, 重新挑一个还在列表里的分组
    parent = None
    for iid, ref in app._refs.items():
        if ref["item"].get("children"):
            parent = iid
            break
    if parent is None:
        parent = first_group
    parent_x = app.row_content_x(parent)
    app.tree.focus(parent)
    app.tree.selection_set(parent)
    app.add_child()
    time.sleep(0.1)
    settle()
    editor = app._editor
    indented = False
    if editor is not None:
        indented = editor.winfo_x() > parent_x
    check("新增子任务按层级缩进", indented)
    app.finish_edit()
    settle()

    before_top = len(app.tree.get_children())
    total = len(app._refs)
    app.collapse_all(True)
    settle()
    collapsed = sum(1 for iid in app._refs if app.tree.bbox(iid))
    check("全部折叠生效", collapsed == before_top)
    app.collapse_all(False)
    settle()
    expanded = sum(1 for iid in app._refs if app.tree.bbox(iid))
    check("全部展开生效", expanded == total)

    # 收起成窄横条: 宽度按顶栏内容算, 统计文字不再显示
    before_w = root.winfo_width()
    app.set_folded(True)
    # 动画第一帧窗口还是展开尺寸, 这时必须还有区域在裁, 否则会闪一帧展开图
    first_frame_ok = (not app._skin_layered
                      or window_region(app.skin_win) != 0)
    settle_anim()
    check("收起第一帧不会闪展开图", first_frame_ok)
    folded_w = root.winfo_width()
    stat_hidden = not app.stat_box.winfo_manager()
    folded_surface = tuple(app._skin_surface or ())
    folded_layer_ok = (not app._skin_layered
                       or folded_surface == (folded_w, root.winfo_height()))
    check("收起后里层图层缩到横条大小", folded_layer_ok)
    surface_image = app._skin_surface_image
    border_ok = True
    if app.border_active() and surface_image is not None:
        sw, sh = surface_image.size
        middle = surface_image.getpixel((sw // 2, sh // 2))
        right = surface_image.getpixel((sw - 2, sh // 2))
        bottom = surface_image.getpixel((sw // 2, sh - 2))
        border_ok = right != middle and bottom != middle
    check("收起后右边/下边也画了边框", border_ok)
    check("收起后横条变窄", folded_w < before_w and folded_w <= 220)
    check("收起后不显示统计文字", stat_hidden)
    check("收起后标题固定为待办清单",
          app.lbl_title.cget("text") == "待办清单")
    app.set_folded(False)
    settle_anim()
    check("展开后宽高恢复",
          root.winfo_width() >= 270 and root.winfo_height() >= 220)
    expanded_surface = tuple(app._skin_surface or ())
    expanded_layer_ok = (not app._skin_layered
                         or expanded_surface == (root.winfo_width(),
                                                 root.winfo_height()))
    check("展开后里层图层跟着放大", expanded_layer_ok)
    if app.list_paint_active():
        check("展开后页签恢复不透明", app._tabs_fade >= 0.99)
    # 统计文字按可用宽度自动显示 / 隐藏(窗口有最小宽度, 直接按宽度算)
    app.fit_width(330)
    wide_shown = bool(app.stat_box.winfo_manager())
    app.fit_width(200)
    narrow_hidden = not app.stat_box.winfo_manager()
    app.fit_width(root.winfo_width())
    check("统计文字按宽度自动显示/隐藏", wide_shown and narrow_hidden)
    check("展开后标题变回清单名", app.lbl_title.cget("text") != "待办清单")

    # 换配色会重建整个界面: 不能把窗口挪回"上次保存的位置"
    keep_geom = app.conf.get("geom")
    keep_layouts = dict(app.conf.get("layouts") or {})
    app.conf["geom"] = "300x460+40+40"
    app.conf["layouts"] = {}
    before_pos = (root.winfo_x(), root.winfo_y(), root.winfo_width())
    app.reload_ui()
    settle(18)
    after_pos = (root.winfo_x(), root.winfo_y(), root.winfo_width())
    check("换配色重建界面后窗口位置不变", before_pos == after_pos)
    app.conf["geom"] = keep_geom
    app.conf["layouts"] = keep_layouts

    # 设置 / 清单管理 / 配色编辑器都摆在主窗口那块屏的中间
    mx, my, mw, mh = app.current_monitor()
    cx, cy = app.screen_center(560, 500)
    in_monitor = (mx <= cx + 280 <= mx + mw and my <= cy + 250 <= my + mh)
    check("弹出的窗口摆在当前屏中间", in_monitor)

    # 右下角调节柄: 解开时有, 锁住后消失
    app.set_resize_locked(False)
    settle()
    grip_free = bool(app.grip.winfo_manager())
    app.set_resize_locked(True)
    settle()
    grip_locked = bool(app.grip.winfo_manager())
    check("自由调节 / 锁定窗口大小切换", grip_free and not grip_locked)
    app.set_resize_locked(False)
    settle()

    # 模拟拖右下角: 宽高都要变大 (不碰真实鼠标)
    w0, h0 = root.winfo_width(), root.winfo_height()
    app.start_resize(FakeEvent(app.grip, 0, 0))
    app.on_resize(FakeEvent(app.grip, 50, 40))
    settle()
    grew = root.winfo_width() > w0 and root.winfo_height() > h0
    app.end_resize(FakeEvent(app.grip, 0, 0))
    check("拖右下角可以改宽高", grew)

    # 窗口缩到最小也要能看见底栏, 不能被列表挤出去
    root.geometry("270x260")
    settle()
    check("窗口缩小时底栏还在", bool(app._foot.winfo_ismapped()))
    root.geometry("330x460")
    settle()

    # 设置窗口: 能打开、能切分类、能关掉
    app.open_settings()
    settle()
    opened = app.settings_win is not None
    app.show_settings_tab("about")
    settle()
    about_shown = bool(app._settings_panels["about"].winfo_ismapped())
    app.show_settings_tab("look")
    settle()
    app.close_settings()
    settle()
    check("设置窗口能打开并切换分类", opened and about_shown)
    check("设置窗口能关闭", app.settings_win is None)
    check("版本号可以比较",
          updater.parse_version("2026.11.19.2")
          > updater.parse_version("2026.11.19.1"))

    app.set_tab("done")
    settle()
    wrong = []
    for ref in app._refs.values():
        is_root = app.tree.parent(ref["item"]["id"]) == ""
        if is_root and not ref["item"]["done"]:
            wrong.append(ref["item"]["text"])
    check("已完成页只放整条完成的根任务", not wrong)
    app.set_tab("pending")
    settle()

    # 完成后应该记下完成时间
    check("勾选会记录完成时间", bool(target_item.get("completed_at")))

    # 图钉: 钉住的排到同层最前面
    app.set_tab("pending")
    while len(app.store.items) < 2:
        app.store.items.append(new_item("自检占位"))
    app.store.save()
    settle()
    rows = app.tree.get_children()
    if len(rows) >= 2:
        last_row = rows[-1]
        app.toggle_pin(last_row)
        settle()
        check("钉住的条目排到最前", app.tree.get_children()[0] == last_row)
        check("钉住状态会存下来",
              bool(app._refs[last_row]["item"].get("pinned")))
        app.toggle_pin(last_row)
        settle()

    # 按时间排序: 出现日期隔板, 且禁止拖动
    app.sort_mode = "time"
    app.refresh()
    settle()
    sep_count = 0
    for child in app.tree.get_children():
        if str(child).startswith("__sep__"):
            sep_count += 1
    check("按时间排序出现日期隔板", sep_count > 0)
    app.on_press(FakeEvent(app.tree, 120, 10))
    check("按时间排序时不能拖动", app._drag_src is None)
    app.sort_mode = "manual"
    app.refresh()
    settle()

    # BUGFIX#102911 线激光寻中降级重试日志: 寻中开始和每次降级重试都要带轨迹序号
    seek_dir = os.path.join(TUBEPRO_TRUNK, "CAM", "TPSeekModule")
    seek_stat = read_source(os.path.join(seek_dir, "SeekHelp",
                                         "uSeekCenterStat.pas"))
    seek_strs = read_source(os.path.join(seek_dir, "SeekStrs.pas"))
    if seek_stat and seek_strs:
        check("寻中开始日志带轨迹序号和句柄",
              "SLLSeekTraceHandle, [GetTraceIdx, FTraceHandle]" in seek_stat
              and "寻中开始，轨迹序号" in seek_strs)
        check("降级重试统一打印轨迹序号",
              "LogTraceInfo;" in seek_stat
              and "线激光轨迹序号" in seek_strs)
        check("轨迹序号按句柄反查且失败有日志",
              "TryCurveByHandle" in seek_stat
              and "SLLSeekTraceResolveFailed" in seek_stat)

    root.destroy()
    try:
        app.store.close()
    except Exception:
        pass
    if conf_backup is not None:
        with open(CONF_FILE, "w", encoding="utf-8") as f:
            f.write(conf_backup)
    if os.path.exists(data_path):
        os.remove(data_path)

    failed = 0
    for name, ok in results:
        mark = "OK  " if ok else "FAIL"
        print("  [{}] {}".format(mark, name))
        if not ok:
            failed += 1
    print("\n自检: {}/{} 通过".format(len(results) - failed, len(results)))
    return 1 if failed else 0
