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

    def log_path_for_hip(self, hip_path: str, uuid_val: str) -> Optional[str]:
        """计算日志文件路径：<hip_dir>/export/serve/log/<uuid>.json。"""
        try:
            hip_dir = os.path.dirname(hip_path or "")
            if not hip_dir or not os.path.isdir(hip_dir) or not uuid_val:
                return None
            log_dir = os.path.join(hip_dir, "export", "serve", "log")
            os.makedirs(log_dir, exist_ok=True)
            return os.path.join(log_dir, f"{uuid_val}.json")
        except Exception:
            return None

    def write_json_safely(self, path: Optional[str], data: Dict[str, Any]) -> None:
        """安全写入 JSON 文件（忽略写入异常）。"""
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.flush()
        except Exception:
            pass

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
            self.write_json_safely(self.log_path_for_hip(hip, uuid_val), log_obj)
            
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


# 任务处理器注册表
TASK_PROCESSORS = {
    "room_generation": RoomGenerationProcessor(),
}

# 默认任务类型
DEFAULT_TASK_TYPE = "room_generation"


def get_task_processor(task_type: str) -> Optional[BaseTaskProcessor]:
    """根据任务类型获取对应的处理器。"""
    return TASK_PROCESSORS.get(task_type)


def get_supported_task_types() -> List[str]:
    """获取支持的任务类型列表。"""
    return list(TASK_PROCESSORS.keys())
