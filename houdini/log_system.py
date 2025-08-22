"""
统一日志系统（OOP）：

- 详细日志（detail）：<hip_dir>/export/serve/log/detail/<uuid>.json
- 用户宏观日志（users）：<hip_dir>/export/serve/log/users/<user_id>.json

功能：
- 原子写入 JSON
- 自动创建目录
- 用户栈 append/replace 与历史迁移
"""

from __future__ import annotations

import os
import json
import tempfile
from typing import Any, Dict, Optional, List


class LogSystem:
    """统一日志系统：提供 detail 与 users 两类日志的写入接口。"""

    def __init__(self) -> None:
        pass

    # ============ 路径解析 ============
    def _hip_dir(self, hip_path: str) -> Optional[str]:
        try:
            d = os.path.dirname(os.path.abspath(hip_path or ""))
            return d if d and os.path.isdir(d) else None
        except Exception:
            return None

    def _base_log_dir(self, hip_path: str) -> Optional[str]:
        d = self._hip_dir(hip_path)
        if not d:
            return None
        return os.path.join(d, "export", "serve", "log")

    def detail_dir(self, hip_path: str) -> Optional[str]:
        base = self._base_log_dir(hip_path)
        if not base:
            return None
        return os.path.join(base, "detail")

    def users_dir(self, hip_path: str) -> Optional[str]:
        base = self._base_log_dir(hip_path)
        if not base:
            return None
        return os.path.join(base, "users")

    def _safe_filename(self, name: str) -> str:
        """将任意字符串转为安全文件名（Windows/Unix通用）。"""
        if not isinstance(name, str):
            name = str(name)
        # 替换非法字符： <>:"/\|?* 以及控制字符与空白中的空格
        unsafe = set('<>:"/\\|?*')
        out = []
        for ch in name:
            if ch in unsafe or ord(ch) < 32:
                out.append('_')
            else:
                out.append(ch)
        # 再额外将冒号与加号等可能遗漏的字符替换
        safe = ''.join(out).replace(':', '_').replace('+', '_')
        # 限制长度，避免过长文件名
        return safe[:200]

    def _ensure_dir(self, path: Optional[str]) -> bool:
        if not path:
            return False
        try:
            os.makedirs(path, exist_ok=True)
            return True
        except Exception:
            return False

    # ============ 原子 JSON 写入 ============
    def _atomic_write_json(self, path: str, data: Dict[str, Any]) -> None:
        try:
            parent = os.path.dirname(path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json", encoding="utf-8", dir=parent or None) as tf:
                json.dump(data, tf, ensure_ascii=False, indent=2)
                tf.flush()
                tmp_path = tf.name
            os.replace(tmp_path, path)
        except Exception:
            # 最小侵入策略：忽略写入异常
            pass

    # ============ 详细日志 ============
    def write_detail_log(self, hip_path: str, uuid_val: str, data: Dict[str, Any]) -> Optional[str]:
        """写入详细日志，返回写入路径（或 None）。"""
        if not hip_path or not uuid_val:
            return None
        ddir = self.detail_dir(hip_path)
        if not self._ensure_dir(ddir):
            return None
        out = os.path.join(ddir, f"{uuid_val}.json")
        self._atomic_write_json(out, data)
        return out

    # ============ 用户宏观日志：栈结构 ============
    def _user_log_path(self, hip_path: str, user_id: str) -> Optional[str]:
        udir = self.users_dir(hip_path)
        if not self._ensure_dir(udir):
            return None
        safe_id = self._safe_filename(user_id)
        return os.path.join(udir, f"{safe_id}.json")

    def _load_user_state(self, path: str, user_id: str, init_time_iso: str) -> Dict[str, Any]:
        state: Dict[str, Any] = {
            "user_id": user_id,
            "stack": [],
            "history": [],
            "updated_at": init_time_iso
        }
        try:
            if os.path.isfile(path):
                with open(path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    if isinstance(loaded, dict):
                        state.update(loaded)
        except Exception:
            # 读取失败时返回空结构
            pass
        return state

    def append_or_replace_user_stack(
        self,
        hip_path: str,
        user_id: str,
        process_name: str,
        uuid_val: str,
        request_time_iso: str,
        status: str = "completed"
    ) -> Optional[str]:
        """
        按规则更新用户栈：
        - 若 process_name 不存在，append
        - 若存在：截断其后的元素进 history，并将当前位置替换为新条目；
          被替换项也进入 history，标记 replaced。
        返回用户日志路径。
        """
        if not hip_path or not user_id or not process_name or not uuid_val or not request_time_iso:
            return None
        upath = self._user_log_path(hip_path, user_id)
        if not upath:
            return None

        state = self._load_user_state(upath, user_id, request_time_iso)
        stack: List[Dict[str, Any]] = list(state.get("stack") or [])
        history: List[Dict[str, Any]] = list(state.get("history") or [])

        new_entry = {
            "process_name": process_name,
            "uuid": uuid_val,
            "request_time": request_time_iso,
            "status": status
        }

        idx = None
        for i, e in enumerate(stack):
            if isinstance(e, dict) and e.get("process_name") == process_name:
                idx = i
                break

        if idx is None:
            stack.append(new_entry)
        else:
            # 把 idx 之后的元素移入 history
            tail = stack[idx+1:]
            if tail:
                for t in tail:
                    if isinstance(t, dict):
                        t2 = dict(t)
                        t2["status"] = "replaced"
                        t2["replaced_at"] = request_time_iso
                        history.append(t2)
            stack = stack[:idx+1]
            # 将当前位置（旧条目）也移入 history，然后写入新条目
            old = stack[idx] if idx < len(stack) else None
            if isinstance(old, dict):
                old2 = dict(old)
                old2["status"] = "replaced"
                old2["replaced_at"] = request_time_iso
                history.append(old2)
            stack[idx] = new_entry

        state["stack"] = stack
        state["history"] = history
        state["updated_at"] = request_time_iso

        self._atomic_write_json(upath, state)
        return upath


