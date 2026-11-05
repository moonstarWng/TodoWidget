# -*- coding: utf-8 -*-
"""自检: 直接调用界面里公开的处理链, 不碰真实鼠标键盘"""

import os
import time

from .app import TodoApp
from .paths import APP_DIR, CONF_FILE
from .store import Store
from .utils import FakeEvent, TkApp

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
    app = TodoApp(root, store=Store(data_path))
    if app.collapsed:
        app.set_folded(False)
    app.set_tab("pending")
    results = []

    def check(name, ok):
        results.append((name, bool(ok)))

    def settle(times=5):
        for _ in range(times):
            root.update()
            time.sleep(0.02)

    def find(text):
        for iid, ref in app._refs.items():
            if ref["item"]["text"] == text:
                return iid
        return None

    settle(8)

    # 不写死任务名, 直接取两条未完成的子任务和第一个分组
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
    check("双击弹出便签", app.note_win is not None)

    if app.note_win is not None:
        app.note_text.insert("1.0", "自检写入的备注")
    time.sleep(0.45)  # 越过"刚打开不关"的保护
    app.simulate_click(second_leaf)
    settle()
    note_text = target_item.get("note")
    closed = app.note_win is None
    check("点别处关闭便签并保存内容", closed and note_text == "自检写入的备注")

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
