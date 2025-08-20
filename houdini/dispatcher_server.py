# houdini/dispatcher_server.py
"""
调度服务：接收 hip/cook_node/parm_node/params，请求即启动 hython 子进程执行 cook。
运行（系统 Python，需安装 Flask）：pip install flask
  python houdini/dispatcher_server.py --host 0.0.0.0 --port 5050
请求 JSON（POST /cook）：
{
  "hip": "C:/path/to/file.hip",
  "cook_node": "/obj/geo1/OUT",                    # 必须：要执行 cook 的节点
  "parm_node": "/obj/geo1/INPUT",                  # 可选：要设置参数的节点（默认与 cook_node 相同）
  "uuid": "123e4567-e89b-12d3-a456-426614174000",  # 可选
  "parms": { "seed": 3, "json_data": "{ ... }" },
  "hython": "C:/Program Files/Side Effects Software/Houdini 19.5.716/bin/hython.exe",  # 可选
  "hfs": "C:/Program Files/Side Effects Software/Houdini 19.5.716",                   # 可选(提供了hython则可不传)
  "timeout_sec": 600                                                                   # 可选
}
优先使用 hython 字段；若未提供，尝试从 HFS 推断 hython 路径；两者都没提供则报错。
"""
import os
import sys
import json
import time
import tempfile
import traceback
import subprocess
import argparse
from typing import Any, Dict, Optional
from flask import Flask, request, jsonify

app = Flask(__name__)

# 简单的 CORS 处理，允许从本地前端访问（如 http://localhost:9901）
@app.after_request
def add_cors_headers(response):
	response.headers['Access-Control-Allow-Origin'] = '*'
	response.headers['Access-Control-Allow-Methods'] = 'GET,POST,OPTIONS'
	response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
	return response

@app.route('/cook', methods=['OPTIONS'])
def cook_preflight():
	# 预检请求直接返回
	return ('', 204)

def _resolve_hython_path(payload: Dict[str, Any]) -> str:
	"""
	解析 hython 可执行文件路径。

	优先使用请求体中的 "hython" 字段；若不存在，则尝试使用请求体或环境变量中的 HFS 来推断
	${HFS}/bin/hython.exe 路径。若最终无法解析则抛出异常。
	"""
	hython = payload.get("hython")
	if hython:
		return hython
	hfs = payload.get("hfs") or os.environ.get("HFS")
	if not hfs:
		raise ValueError("未提供 hython 路径，且未在请求或环境变量中提供 HFS。请传入 'hython' 或设置 'HFS'。")
	hython_guess = os.path.join(hfs, "bin", "hython.exe")
	return hython_guess

def _worker_script_path() -> str:
	"""
	返回工作脚本 hython_cook_worker.py 的绝对路径。
	"""
	return os.path.join(os.path.dirname(__file__), "hython_cook_worker.py")

def _normalize_parms(parms: dict) -> dict:
	"""确保参数字典中的所有键都转换为小写
	
	Args:
		parms (dict): 原始参数字典
		
	Returns:
		dict: 键转换为小写的参数字典
	"""
	if not parms:
		return {}
	return {k.lower(): v for k, v in parms.items()}

def _extract_uuid(payload: Dict[str, Any], parms_lower: Dict[str, Any]) -> str:
	"""从请求中提取 UUID。

	优先使用顶层 payload['uuid']；否则尝试从 parms['room_file'] 提取（形如 "<uuid>.json"）。
	若均不可得，返回空字符串。
	"""
	uuid_val = str(payload.get("uuid") or "").strip()
	if uuid_val:
		return uuid_val
	room_file = str(parms_lower.get("room_file") or "").strip()
	if room_file:
		base = os.path.basename(room_file)
		uuid_guess, _ = os.path.splitext(base)
		return uuid_guess
	return ""

def _log_path_for_hip(hip_path: str, uuid_val: str) -> Optional[str]:
	"""根据 hip 文件路径与 uuid 计算日志文件路径：<hip_dir>/export/serve/log/<uuid>.json。

	当 hip_dir 不存在或 uuid 为空时返回 None。
	"""
	try:
		hip_dir = os.path.dirname(hip_path or "")
		if not hip_dir or not os.path.isdir(hip_dir) or not uuid_val:
			return None
		log_dir = os.path.join(hip_dir, "export", "serve", "log")
		os.makedirs(log_dir, exist_ok=True)
		return os.path.join(log_dir, f"{uuid_val}.json")
	except Exception:
		return None

def _write_json_safely(path: Optional[str], data: Dict[str, Any]) -> None:
	"""将 data 写入到 path（UTF-8）。若 path 无效或写入失败则忽略错误。"""
	if not path:
		return
	try:
		with open(path, "w", encoding="utf-8") as f:
			json.dump(data, f, ensure_ascii=False, indent=2)
			f.flush()
	except Exception:
		pass

@app.route("/ping", methods=["GET"])
def ping():
	"""健康检查接口。"""
	return jsonify({"status": "ok"})

@app.route("/cook", methods=["POST"])
def cook():
	"""
	按请求参数启动 hython 子进程执行 cook。

	请求 JSON:
	{
	  "hip": "C:/path/to/file.hip",
	  "cook_node": "/obj/geo1/OUT",
	  "parm_node": "/obj/geo1/INPUT",
	  "parms": { "seed": 3, ... },
	  "hython": "C:/.../hython.exe",  # 可选
	  "hfs": "C:/Program Files/...",  # 可选（未提供 hython 时用来推断）
	  "timeout_sec": 600               # 可选
	}
	"""
	try:
		# 读取并校验请求体
		payload = request.get_json(force=True) or {} # 用于解析 HTTP 请求中 JSON 格式的请求体（request body）
		hip = payload.get("hip") # 获取请求体中的 hip 字段
		cook_node = payload.get("cook_node") # 获取请求体中的 cook_node 字段
		parm_node = payload.get("parm_node") # 获取请求体中的 parm_node 字段
		parms = payload.get("parms", {}) # 获取请求体中的 parms 字段，如果 parms 不存在，则返回空字典
		
		# 如果 hip 或 cook_node 不存在，则返回 400 错误
		if not hip or not cook_node:
			return jsonify({"ok": False, "error": "缺少必填字段：'hip' 或 'cook_node'"}), 400

		# 解析 hython 路径，并检查文件存在
		hython_path = _resolve_hython_path(payload)
		if not os.path.isfile(hython_path):
			return jsonify({"ok": False, "error": f"hython 不存在: {hython_path}"}), 400

		# 定位工作脚本
		worker = _worker_script_path()
		if not os.path.isfile(worker):
			return jsonify({"ok": False, "error": f"找不到工作脚本: {worker}"}), 500

		# 生成临时 job.json，作为子进程输入
		job = {"hip": hip, "cook_node": cook_node, "parm_node": parm_node, "parms": _normalize_parms(parms)}
		timeout_sec = int(payload.get("timeout_sec", 600)) # 读取请求体中的 timeout_sec 字段，如果 timeout_sec 不存在，则返回 600

		# 创建上下文管理器
		with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json", encoding="utf-8") as tf:
			json.dump(job, tf)
			job_path = tf.name

		# 为 worker 准备结果回退文件路径（当 stdout 为空或不可解析时使用）
		with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json", encoding="utf-8") as rf:
			result_path = rf.name

		# 组装并启动 hython 子进程，传入 --out 回退路径
		cmd = [hython_path, worker, "--job", job_path, "--out", result_path]
		# 子进程环境：强制 stdout/stderr 使用 UTF-8 输出
		child_env = os.environ.copy()
		child_env["PYTHONIOENCODING"] = "utf-8"
		start = time.time()
		try:
			proc = subprocess.run(
				cmd,
				capture_output=True,
				text=True,
				encoding='utf-8',
				errors='replace',
				timeout=timeout_sec,
				env=child_env
			)
		finally:
			# 尝试删除临时 job 文件
			try:
				os.remove(job_path)
			except Exception:
				pass

		# 汇总子进程执行结果
		elapsed_ms = round((time.time() - start) * 1000)
		stdout = (proc.stdout or "").strip()
		stderr = (proc.stderr or "").strip()

		# 解析 worker 的输出，如果 stdout 不为空，则尝试将 stdout 转换为 JSON 格式
		worker_json: Optional[Dict[str, Any]] = None
		if stdout:
			try:
				worker_json = json.loads(stdout)
			except Exception:
				worker_json = None

		# 若 stdout 无法解析，则尝试读取 result 回退文件
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


		# 记录日志：收集调度与子进程的关键信息，写入到 hip/export/serve/log/<uuid>.json
		uuid_val = _extract_uuid(payload, _normalize_parms(parms))
		log_obj = {
			"uuid": uuid_val,
			"ok": bool(worker_json and worker_json.get("ok") and proc.returncode == 0),
			"elapsed_ms_dispatch": elapsed_ms,
			"returncode": proc.returncode,
			"stdout": stdout,
			"stderr": stderr,
			"worker_json": worker_json,
			"request": {
				"hip": hip,
				"cook_node": cook_node,
				"parm_node": parm_node,
				"parms": _normalize_parms(parms)
			}
		}
		_write_json_safely(_log_path_for_hip(hip, uuid_val), log_obj)

		# 返回成功：透传 worker 的结果并补充调度耗时
		if proc.returncode == 0 and worker_json and worker_json.get("ok"):
			worker_json["elapsed_ms_dispatch"] = elapsed_ms
			return jsonify(worker_json)
		else:
			# 返回失败：附带 returncode、stdout、stderr 便于排查；如果有 worker_json 也一并返回
			resp = {
				"ok": False,
				"elapsed_ms_dispatch": elapsed_ms,
				"returncode": proc.returncode,
				"stdout": stdout,
				"stderr": stderr,
			}
			if worker_json is not None:
				resp["worker_json"] = worker_json
			return jsonify(resp), 500

	except subprocess.TimeoutExpired:
		# 记录超时日志
		try:
			parms_lower = _normalize_parms((payload or {}).get("parms", {}))
			uuid_val = _extract_uuid(payload or {}, parms_lower)
			log_obj = {
				"uuid": uuid_val,
				"ok": False,
				"error": "hython 执行超时",
				"worker_json": None,
				"request": {
					"hip": (payload or {}).get("hip"),
					"cook_node": (payload or {}).get("cook_node"),
					"parm_node": (payload or {}).get("parm_node"),
					"parms": parms_lower
				}
			}
			_write_json_safely(_log_path_for_hip((payload or {}).get("hip"), uuid_val), log_obj)
		except Exception:
			pass
		return jsonify({"ok": False, "error": "hython 执行超时"}), 504
	except Exception as e:
		# 记录异常日志
		try:
			parms_lower = _normalize_parms((payload or {}).get("parms", {}))
			uuid_val = _extract_uuid(payload or {}, parms_lower)
			log_obj = {
				"uuid": uuid_val,
				"ok": False,
				"error": str(e),
				"traceback": traceback.format_exc(),
				"worker_json": None,
				"request": {
					"hip": (payload or {}).get("hip"),
					"cook_node": (payload or {}).get("cook_node"),
					"parm_node": (payload or {}).get("parm_node"),
					"parms": parms_lower
				}
			}
			_write_json_safely(_log_path_for_hip((payload or {}).get("hip"), uuid_val), log_obj)
		except Exception:
			pass
		return jsonify({"ok": False, "error": str(e), "traceback": traceback.format_exc()}), 500

def _parse_args() -> argparse.Namespace:
	"""解析命令行参数（host/port/debug）。"""
	parser = argparse.ArgumentParser(description="Houdini Cook Dispatcher (Windows)")
	parser.add_argument("--host", default="0.0.0.0")
	parser.add_argument("--port", type=int, default=5050)
	parser.add_argument("--debug", action="store_true")
	return parser.parse_args()

def main():
	"""启动 Flask 调度服务。"""
	args = _parse_args()
	app.run(host=args.host, port=args.port, debug=args.debug, use_reloader=False)

if __name__ == "__main__":
	main()