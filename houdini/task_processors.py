# houdini/task_processors.py
"""
任务处理器模块：支持不同类型任务的插件化执行。

设计理念：
- 每种任务类型对应一个处理器类
- 处理器负责自己的执行流程（hython、直接操作、文件转换等）
- 调度服务通过注册表查找并调用对应的处理器
- 便于扩展新功能，维护现有功能
"""

import os
import sys
import json
import time
import tempfile
import subprocess
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, List
from log_system import LogSystem

log_system = LogSystem()


class BaseTaskProcessor(ABC):
    """任务处理器基类。"""
    
    @abstractmethod
    def can_handle(self, task_type: str) -> bool:
        """判断是否能处理指定的任务类型。"""
        pass
    
    @abstractmethod
    def execute(self, payload: dict) -> dict:
        """执行任务，返回结果。"""
        pass
    
    def get_required_fields(self) -> List[str]:
        """返回该任务类型必需的字段列表。"""
        return ["hip", "uuid"]
    
    def validate_payload(self, payload: dict) -> tuple[bool, str]:
        """验证请求体是否包含必需字段。"""
        for field in self.get_required_fields():
            if not payload.get(field):
                return False, f"缺少必需字段: {field}"
        return True, ""

    # ========= 通用工具方法（供子类复用） =========
    def normalize_parms(self, parms: dict) -> dict:
        """确保参数字典中的所有键都转换为小写。"""
        if not parms:
            return {}
        return {str(k).lower(): v for k, v in parms.items()}

    def extract_uuid(self, payload: Dict[str, Any], parms_lower: Dict[str, Any]) -> str:
        """从请求体/参数中提取 UUID。"""
        uuid_val = str(payload.get("uuid") or "").strip()
        if uuid_val:
            return uuid_val
        room_file = str(parms_lower.get("room_file") or "").strip()
        if room_file:
            base = os.path.basename(room_file)
            uuid_guess, _ = os.path.splitext(base)
            return uuid_guess
        return ""

    # 统一改用 LogSystem 写入

    def resolve_hython_path(self, payload: Dict[str, Any]) -> str:
        """解析 hython 可执行文件路径（通用）。"""
        hython = payload.get("hython")
        if hython:
            return hython
        hfs = payload.get("hfs") or os.environ.get("HFS")
        if not hfs:
            raise ValueError("未提供 hython 路径，且未在请求或环境变量中提供 HFS。")
        return os.path.join(hfs, "bin", "hython.exe")

    def run_subprocess(self, cmd: List[str], timeout_sec: int, env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """运行子进程，返回标准的结果字典：returncode/stdout/stderr/elapsed_ms。"""
        start = time.time()
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=timeout_sec,
            env=env
        )
        return {
            "returncode": proc.returncode,
            "stdout": (proc.stdout or "").strip(),
            "stderr": (proc.stderr or "").strip(),
            "elapsed_ms": round((time.time() - start) * 1000)
        }


class RoomGenerationProcessor(BaseTaskProcessor):
    """房间生成任务处理器：hython执行 + JSON转PNG。"""
    
    def can_handle(self, task_type: str) -> bool:
        return task_type == "room_generation"
    
    def get_required_fields(self) -> List[str]:
        return ["hip", "cook_node", "uuid"]
    
    def _worker_script_path(self) -> str:
        """返回工作脚本路径。"""
        return os.path.join(os.path.dirname(__file__), "hython_cook_worker.py")
    
    def _json2jpg_script_path(self) -> str:
        """返回后置处理脚本路径。"""
        return os.path.join(os.path.dirname(__file__), "json2jpg.py")
    
    def execute(self, payload: dict) -> dict:
        """执行房间生成任务：hython + json2png。"""
        try:
            # 解析参数
            hip = payload.get("hip")
            cook_node = payload.get("cook_node")
            parm_node = payload.get("parm_node")
            parms = payload.get("parms", {})
            timeout_sec = int(payload.get("timeout_sec", 600))
            post_timeout_sec = int(payload.get("post_timeout_sec", 10))
            post_wait_sec = float(payload.get("post_wait_sec", min(5, post_timeout_sec)))
            
            # 验证必需字段
            if not hip or not cook_node:
                return {"ok": False, "error": "缺少必填字段：'hip' 或 'cook_node'"}
            
            # 解析 hython 路径
            try:
                hython_path = self.resolve_hython_path(payload)
            except Exception as e:
                return {"ok": False, "error": str(e)}
            if not os.path.isfile(hython_path):
                return {"ok": False, "error": f"hython 不存在: {hython_path}"}
            
            # 定位工作脚本
            worker = self._worker_script_path()
            if not os.path.isfile(worker):
                return {"ok": False, "error": f"找不到工作脚本: {worker}"}
            
            # 生成临时 job.json
            job = {
                "hip": hip, 
                "cook_node": cook_node, 
                "parm_node": parm_node, 
                "parms": self.normalize_parms(parms)
            }
            
            # 创建临时文件
            with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json", encoding="utf-8") as tf:
                json.dump(job, tf)
                job_path = tf.name
            with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json", encoding="utf-8") as rf:
                result_path = rf.name
            
            # 启动 hython 子进程
            child_env = os.environ.copy()
            child_env["PYTHONIOENCODING"] = "utf-8"
            hython_cmd = [hython_path, worker, "--job", job_path, "--out", result_path]
            try:
                hython_res = self.run_subprocess(hython_cmd, timeout_sec, env=child_env)
            finally:
                try:
                    os.remove(job_path)
                except Exception:
                    pass
            
            elapsed_ms = hython_res["elapsed_ms"]
            stdout = hython_res["stdout"]
            stderr = hython_res["stderr"]
            
            # 解析 worker 输出
            worker_json: Optional[Dict[str, Any]] = None
            if stdout:
                try:
                    worker_json = json.loads(stdout)
                except Exception:
                    worker_json = None
            if worker_json is None and os.path.isfile(result_path):
                try:
                    with open(result_path, "r", encoding="utf-8") as rf:
                        worker_json = json.load(rf)
                except Exception:
                    worker_json = None
                finally:
                    try:
                        os.remove(result_path)
                    except Exception:
                        pass
            
            # 执行后置处理（JSON→PNG）
            uuid_val = self.extract_uuid(payload, self.normalize_parms(parms))
            post_info = None
            
            if hython_res["returncode"] == 0 and worker_json and worker_json.get("ok") and uuid_val:
                reader = self._json2jpg_script_path()
                if os.path.isfile(reader):
                    child_env2 = os.environ.copy()
                    child_env2["PYTHONIOENCODING"] = "utf-8"
                    cmd_reader = [
                        sys.executable, reader,
                        "--hip", hip,
                        "--uuid", uuid_val,
                        "--wait-sec", str(max(0.0, post_wait_sec))
                    ]
                    try:
                        post_res = self.run_subprocess(cmd_reader, post_timeout_sec, env=child_env2)
                        stdout_post = post_res["stdout"]
                        post_json = None
                        if stdout_post:
                            try:
                                post_json = json.loads(stdout_post)
                            except Exception:
                                post_json = None
                        post_info = {
                            "returncode": post_res["returncode"],
                            "stdout": "",
                            "stderr": "",
                            "json": post_json,
                            "elapsed_ms_post": post_res["elapsed_ms"],
                            "ok": bool(post_json and post_json.get("ok") and post_res["returncode"] == 0)
                        }
                    except subprocess.TimeoutExpired:
                        post_info = {
                            "returncode": None,
                            "stdout": "",
                            "stderr": "json2jpg 超时",
                            "json": None,
                            "elapsed_ms_post": 0,
                            "ok": False
                        }
                    except Exception as _e:
                        post_info = {
                            "returncode": None,
                            "stdout": "",
                            "stderr": str(_e),
                            "json": None,
                            "elapsed_ms_post": 0,
                            "ok": False
                        }
            
            # 记录日志
            log_obj = {
                "uuid": uuid_val,
                "ok": bool(worker_json and worker_json.get("ok") and hython_res["returncode"] == 0),
                "elapsed_ms_dispatch": elapsed_ms,
                "returncode": hython_res["returncode"],
                "stdout": stdout,
                "stderr": stderr,
                "worker_json": worker_json,
                "post": post_info,
                "request": {
                    "task_type": payload.get("task_type"),
                    "hip": hip,
                    "cook_node": cook_node,
                    "parm_node": parm_node,
                    "parms": self.normalize_parms(parms)
                },
                "request_raw": payload
            }
            log_system.write_detail_log(hip_path=hip, uuid_val=uuid_val, data=log_obj)
            
            # 组装最终响应
            if hython_res["returncode"] == 0 and worker_json and worker_json.get("ok"):
                resp = worker_json.copy()
                resp["elapsed_ms_dispatch"] = elapsed_ms
                resp["post"] = post_info
                return resp
            else:
                return {
                    "ok": False,
                    "elapsed_ms_dispatch": elapsed_ms,
                    "returncode": hython_res["returncode"],
                    "stdout": stdout,
                    "stderr": stderr,
                    "worker_json": worker_json,
                    "post": post_info,
                }
                
        except Exception as e:
            return {"ok": False, "error": str(e)}


class RoomRegenProcessor(BaseTaskProcessor):
    """处理room_regen任务的处理器（房间重新生成）"""
    
    def can_handle(self, task_type: str) -> bool:
        return task_type == "room_regen"
    
    def get_required_fields(self) -> List[str]:
        return ["hip", "cook_node", "uuid"]
    
    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行room_regen任务：
        1. 运行png2json.py将前端上传的PNG转换为JSON（供Houdini使用）
        2. 运行hython_cook_press.py设置参数并按下execute按钮
        3. 返回执行结果（不需要JSON->PNG转换，因为前端已上传PNG）
        """
        try:
            start_time = time.time()
            
            # 提取和验证参数
            hip = payload["hip"]
            cook_node = payload["cook_node"]
            parm_node = payload.get("parm_node", cook_node)
            parms = self.normalize_parms(payload.get("parms", {}))
            uuid = self.extract_uuid(payload, parms)
            hython_path = payload.get("hython", self.resolve_hython_path(payload))
            timeout_sec = payload.get("timeout_sec", 300)
            
            # 日志记录（detail）
            log_data = {
                "uuid": uuid,
                "task_type": "room_regen",
                "timestamp": time.time(),
                "request_raw": payload
            }
            
            # 执行hython worker（press 版本）
            worker = os.path.join(os.path.dirname(__file__), 'hython_cook_press.py')
            
            # 先执行 PNG→JSON 转换（前端已上传PNG）
            png2json_script = os.path.join(os.path.dirname(__file__), 'png2json.py')
            if os.path.isfile(png2json_script):
                hip_dir = os.path.dirname(os.path.abspath(hip))
                png2json_cmd = ["python", png2json_script, "--hip", hip_dir, "--uuid", uuid]
                
                try:
                    png2json_res = self.run_subprocess(png2json_cmd, 60)
                    png2json_stdout = png2json_res["stdout"]
                    if png2json_stdout:
                        try:
                            png2json_info = json.loads(png2json_stdout)
                            if not png2json_info.get("ok"):
                                return {
                                    "ok": False,
                                    "error": f"PNG转JSON失败: {png2json_info.get('error', 'unknown error')}",
                                    "png2json": png2json_info
                                }
                        except Exception:
                            return {
                                "ok": False,
                                "error": "解析png2json输出失败",
                                "png2json_stdout": png2json_stdout
                            }
                    else:
                        return {
                            "ok": False,
                            "error": "png2json无输出"
                        }
                except Exception as e:
                    return {
                        "ok": False,
                        "error": f"执行png2json失败: {str(e)}"
                    }
            else:
                return {
                    "ok": False,
                    "error": f"找不到png2json脚本: {png2json_script}"
                }
            
            job_data = {
                "hip": hip,
                "cook_node": cook_node,
                "parm_node": parm_node,
                "uuid": uuid,
                "parms": parms
            }
            
            with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as tf:
                json.dump(job_data, tf, ensure_ascii=False, indent=2)
                job_path = tf.name
            
            with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as tf:
                result_path = tf.name
            
            child_env = os.environ.copy()
            child_env["PYTHONIOENCODING"] = "utf-8"
            hython_cmd = [hython_path, worker, "--job", job_path, "--out", result_path]
            try:
                hython_res = self.run_subprocess(hython_cmd, timeout_sec, env=child_env)
            finally:
                try:
                    os.remove(job_path)
                except Exception:
                    pass
            
            elapsed_ms = hython_res["elapsed_ms"]
            stdout = hython_res["stdout"]
            stderr = hython_res["stderr"]
            
            # 解析 worker 输出
            worker_json: Optional[Dict[str, Any]] = None
            if stdout:
                try:
                    worker_json = json.loads(stdout)
                except Exception:
                    worker_json = None
            if worker_json is None and os.path.isfile(result_path):
                try:
                    with open(result_path, "r", encoding="utf-8") as rf:
                        worker_json = json.load(rf)
                except Exception:
                    worker_json = None
                finally:
                    try:
                        os.remove(result_path)
                    except Exception:
                        pass
                        
            # room_regen 不需要 JSON->PNG 后处理（前端已上传PNG）
            post_info = {"ok": True, "note": "no post process for room_regen"}
            
            # 记录完整日志
            log_data.update({
                "elapsed_ms": elapsed_ms,
                "worker_stdout": stdout,
                "worker_stderr": stderr,
                "worker_json": worker_json,
                "post": post_info,
                "png2json_executed": True  # 标记已执行PNG->JSON转换
            })
            
            log_system.write_detail_log(hip_path=hip, uuid_val=uuid, data=log_data)
            
            # 构建响应
            if worker_json and worker_json.get("ok"):
                resp = worker_json.copy()
                resp["elapsed_ms_dispatch"] = elapsed_ms
                resp["post"] = post_info
                return resp
            else:
                return {
                    "ok": False,
                    "elapsed_ms_dispatch": elapsed_ms,
                    "returncode": hython_res["returncode"],
                    "stdout": stdout,
                    "stderr": stderr,
                    "worker_json": worker_json,
                    "post": post_info,
                }
                
        except Exception as e:
            return {"ok": False, "error": str(e)}


class ListThemesProcessor(BaseTaskProcessor):
    """读取 hip 同目录 export/serve/config/<hip_name>.json 并返回主题信息。

    返回字段：
    - ok: bool
    - themes: List[Dict] 原始主题对象列表（如存在）
    - lines: List[str] 便于前端直接展示的文本行
    - text: str 将 lines 用\n拼接后的整段文本
    """

    def can_handle(self, task_type: str) -> bool:
        return task_type == "list_themes"

    def get_required_fields(self) -> List[str]:
        # 仅需要 hip 与 uuid（保持与默认一致，uuid 便于通用请求模板）
        return ["hip", "uuid"]

    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            hip = str(payload.get("hip") or "").strip()
            if not hip:
                return {"ok": False, "error": "缺少必需字段: hip"}

            hip_dir = os.path.dirname(os.path.abspath(hip))
            hip_base = os.path.splitext(os.path.basename(hip))[0]
            cfg_path = os.path.join(hip_dir, "export", "serve", "config", f"{hip_base}.json")

            if not os.path.isfile(cfg_path):
                return {"ok": False, "error": f"未找到主题配置: {cfg_path}"}

            with open(cfg_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            # 兼容可能的结构：
            # 1) data["themes"] 为数组
            # 2) data 本身为数组
            # 3) data 为字典映射 { "name": { ... } }
            themes = None
            if isinstance(data, dict) and "themes" in data:
                themes = data.get("themes")
            elif isinstance(data, list):
                themes = data
            elif isinstance(data, dict):
                # 进一步尝试常见键位
                for key in ("items", "theme_list", "data"):
                    if key in data:
                        themes = data[key]
                        break
                # 若仍未命中，尝试将字典映射转换为数组
                if themes is None:
                    # 判断 value 是否像主题对象（dict 且包含常见字段）
                    looks_like_mapping = all(
                        isinstance(v, dict) for v in data.values()
                    ) and any(
                        any(k in ("description", "color", "hex", "chunk_tag", "cluster_id") for k in (v.keys() if isinstance(v, dict) else []))
                        for v in data.values()
                    )
                    if looks_like_mapping:
                        converted = []
                        for name_key, theme_val in data.items():
                            if isinstance(theme_val, dict):
                                item = {"name": name_key}
                                item.update(theme_val)
                                converted.append(item)
                        themes = converted

            if not isinstance(themes, list):
                themes = []

            lines: List[str] = []
            for item in themes:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or item.get("theme") or "").strip() or "(未命名)"
                color = str(item.get("color") or item.get("hex") or item.get("colour") or "").strip()
                desc = str(item.get("description") or item.get("desc") or item.get("note") or "").strip()
                if color and not color.startswith('#'):
                    # 规范化为 #RRGGBB（若已是 # 开头则保持）
                    color = '#' + color
                line = f"Theme: {name}    Color: {color or '-'}    Desc: {desc or '-'}"
                lines.append(line)

            text = "\n".join(lines) if lines else "(无可用主题)"
            return {
                "ok": True,
                "themes": themes,
                "lines": lines,
                "text": text,
                "config_path": cfg_path
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}


# 任务处理器注册表
TASK_PROCESSORS = {
    "room_generation": RoomGenerationProcessor(),
    "room_regen": RoomRegenProcessor(),
    "list_themes": ListThemesProcessor(),
}

# 默认任务类型
DEFAULT_TASK_TYPE = "room_generation"


def get_task_processor(task_type: str) -> Optional[BaseTaskProcessor]:
    """根据任务类型获取对应的处理器。"""
    return TASK_PROCESSORS.get(task_type)


def get_supported_task_types() -> List[str]:
    """获取支持的任务类型列表。"""
    return list(TASK_PROCESSORS.keys())
