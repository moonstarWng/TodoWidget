# -*- coding: utf-8 -*-
"""清单数据: 多清单结构 + JSON 读写"""

import json
import os
import uuid
from datetime import datetime

from .paths import DATA_FILE

def new_item(text):
    return {"id": uuid.uuid4().hex[:8], "text": text, "done": False,
            "children": [], "open": True}

class Store:
    """多份清单; 每份清单是 {id, name, items}"""

    def __init__(self, path=DATA_FILE):
        self.path = path
        self.lists = []
        self.current = ""
        self.load()

    @property
    def items(self):
        lst = self.current_list()
        if lst is None:
            return []
        return lst["items"]

    def current_list(self):
        for lst in self.lists:
            if lst["id"] == self.current:
                return lst
        if self.lists:
            return self.lists[0]
        return None

    def current_name(self):
        lst = self.current_list()
        if lst is None:
            return "待办"
        return lst["name"]

    def select(self, list_id):
        for lst in self.lists:
            if lst["id"] == list_id:
                self.current = list_id
                return True
        return False

    def add_list(self, name):
        clean = (name or "").strip() or "新清单"
        lst = {"id": uuid.uuid4().hex[:8], "name": clean, "items": []}
        self.lists.append(lst)
        self.current = lst["id"]
        return lst

    def rename_list(self, list_id, name):
        clean = (name or "").strip()
        if not clean:
            return False
        for lst in self.lists:
            if lst["id"] == list_id:
                lst["name"] = clean
                return True
        return False

    def delete_list(self, list_id):
        if len(self.lists) <= 1:
            return False
        left = []
        for lst in self.lists:
            if lst["id"] != list_id:
                left.append(lst)
        if len(left) == len(self.lists):
            return False
        self.lists = left
        if self.current == list_id:
            self.current = self.lists[0]["id"]
        return True

    def load(self):
        if not os.path.exists(self.path):
            self.lists = [{"id": uuid.uuid4().hex[:8], "name": "待办",
                           "items": seed_data()}]
            self.current = self.lists[0]["id"]
            self.save()
            return

        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}

        lists = data.get("lists")
        if isinstance(lists, list) and lists:
            self.lists = lists
            for lst in self.lists:
                if not lst.get("id"):
                    lst["id"] = uuid.uuid4().hex[:8]
                if not lst.get("name"):
                    lst["name"] = "待办"
                if not isinstance(lst.get("items"), list):
                    lst["items"] = []
            self.current = data.get("current") or self.lists[0]["id"]
            if self.current_list() is None:
                self.current = self.lists[0]["id"]
            return

        old_items = data.get("items")
        if isinstance(old_items, list):
            # 老版本是单清单格式, 平滑升级成一份叫做"待办"的清单
            self.lists = [{"id": uuid.uuid4().hex[:8], "name": "待办",
                           "items": old_items}]
            self.current = self.lists[0]["id"]
            self.save()
            return

        self.lists = [{"id": uuid.uuid4().hex[:8], "name": "待办", "items": []}]
        self.current = self.lists[0]["id"]

    def save(self):
        if not self.lists:
            self.lists = [{"id": uuid.uuid4().hex[:8], "name": "待办",
                           "items": []}]
            self.current = self.lists[0]["id"]
        if self.current_list() is None:
            self.current = self.lists[0]["id"]

        data = {"updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "current": self.current,
                "lists": self.lists}
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)

def seed_data():
    """首次启动时的示例清单"""
    src = [
        ("开始使用", ["点左边的框勾选", "双击任务写便签", "拖动行可以排序"]),
        ("这些也可以试试", ["左上角清单名: 切换 / 新建清单",
                          "右上角 ▾: 折叠成一条横杠", "右下角 ⚙: 换配色"]),
    ]
    out = []
    for title, kids in src:
        it = new_item(title)
        it["children"] = [new_item(k) for k in kids]
        out.append(it)
    return out

def walk(items, parent=None):
    """深度遍历, 产出 (item, 所在列表)"""
    for it in items:
        yield it, items
        yield from walk(it.get("children") or [])

def leaf_stats(item):
    done = total = 0
    for it, _ in walk([item]):
        if it is item:
            continue
        if not it.get("children"):
            total += 1
            done += 1 if it.get("done") else 0
    return done, total


# --------------------------------------------------------------------------
# 主界面
# --------------------------------------------------------------------------
