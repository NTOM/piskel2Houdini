# houdini/dispatcher_server.py
"""
调度服务：基于插件化任务处理器的 HTTP 服务。

支持多种任务类型：
- room_generation: 房间生成（hython + JSON转PNG）

运行（系统 Python，需安装 Flask）：pip install flask
  python houdini/dispatcher_server.py --host 0.0.0.0 --port 5050

请求 JSON（POST /cook）：
{
  "task_type": "room_generation",                    # 可选，默认 "room_generation"
  "hip": "C:/path/to/file.hip",
  "cook_node": "/obj/geo1/OUT",                     # 根据任务类型可能需要不同字段
  "parm_node": "/obj/geo1/INPUT",                   # 可选
  "uuid": "123e4567-e89b-12d3-a456-426614174000",  # 必须
  "parms": { "seed": 3, "json_data": "{ ... }" },
  "hython": "C:/Program Files/Side Effects Software/Houdini 19.5.716/bin/hython.exe",  # 可选
  "hfs": "C:/Program Files/Side Effects Software/Houdini 19.5.716",                   # 可选
  "timeout_sec": 600,                                                               # 可选
  "post_timeout_sec": 10,                                                           # 可选，后置处理超时
  "post_wait_sec": 5                                                                # 可选，后置处理等待时间
}
"""
import os
import sys
import json
import traceback
import argparse
from typing import Any, Dict, Optional
from flask import Flask, request, jsonify, send_file

# 导入任务处理器
from task_processors import get_task_processor, get_supported_task_types, DEFAULT_TASK_TYPE
from log_system import LogSystem

app = Flask(__name__)
log_system = LogSystem()

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

@app.route("/ping", methods=["GET"])
def ping():
	"""健康检查接口。"""
	return jsonify({"status": "ok"})

@app.route("/tasks", methods=["GET"])
def list_tasks():
	"""列出支持的任务类型。"""
	return jsonify({
		"supported_tasks": get_supported_task_types(),
		"default_task": DEFAULT_TASK_TYPE
	})

@app.route('/result/png', methods=['GET'])
def fetch_png():
	"""按 hip 与 uuid 返回生成的 PNG 文件。安全限制：仅允许访问 hip 同目录下 export/serve/<uuid>.png。"""
	hip = request.args.get('hip') or ''
	uuid_val = request.args.get('uuid') or ''
	if not hip or not uuid_val:
		return jsonify({'ok': False, 'error': 'missing hip or uuid'}), 400
	# 计算目标路径
	hip_dir = os.path.dirname(hip)
	if not os.path.isdir(hip_dir):
		return jsonify({'ok': False, 'error': 'invalid hip dir'}), 400
	png_path = os.path.join(hip_dir, 'export', 'serve', f'{uuid_val}.png')
	# 路径安全校验
	base_real = os.path.realpath(hip_dir)
	png_real = os.path.realpath(png_path)
	if not png_real.startswith(base_real):
		return jsonify({'ok': False, 'error': 'forbidden'}), 403
	if not os.path.isfile(png_real):
		return jsonify({'ok': False, 'error': 'file not found'}), 404
	return send_file(png_real, mimetype='image/png')

@app.route('/upload/png', methods=['POST'])
def upload_png():
    """接收前端上传的 PNG 文件，并保存到 hip 同目录下 export/serve/<uuid>.png。

    参数：
      - querystring: hip, uuid
      - form-data: file (PNG 文件)
    """
    try:
        hip = request.args.get('hip') or ''
        uuid_val = request.args.get('uuid') or ''
        if not hip or not uuid_val:
            return jsonify({'ok': False, 'error': 'missing hip or uuid'}), 400

        hip_dir = os.path.dirname(hip)
        if not os.path.isdir(hip_dir):
            return jsonify({'ok': False, 'error': 'invalid hip dir'}), 400

        # 获取文件
        if 'file' not in request.files:
            return jsonify({'ok': False, 'error': 'missing file field'}), 400
        f = request.files['file']
        if not f.filename:
            return jsonify({'ok': False, 'error': 'empty filename'}), 400

        # 目标路径与安全校验
        out_dir = os.path.join(hip_dir, 'export', 'serve')
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, f'{uuid_val}.png')
        base_real = os.path.realpath(hip_dir)
        out_real = os.path.realpath(out_path)
        if not out_real.startswith(base_real):
            return jsonify({'ok': False, 'error': 'forbidden'}), 403

        f.save(out_real)
        return jsonify({'ok': True, 'path': out_real, 'uuid': uuid_val})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route("/cook", methods=["POST"])
def cook():
	"""
	根据任务类型执行相应的处理流程。
	
	支持的任务类型：
	- room_generation: 房间生成（hython + JSON转PNG）
	"""
	try:
		# 读取并校验请求体
		payload = request.get_json(force=True) or {}
		
		# 确定任务类型
		task_type = payload.get("task_type", DEFAULT_TASK_TYPE)
		
		# 获取对应的任务处理器
		processor = get_task_processor(task_type)
		if not processor:
			return jsonify({
				"ok": False, 
				"error": f"不支持的任务类型: {task_type}",
				"supported_tasks": get_supported_task_types()
			}), 400
		
		# 验证必需字段
		is_valid, error_msg = processor.validate_payload(payload)
		if not is_valid:
			return jsonify({"ok": False, "error": error_msg}), 400
		
		# 执行任务
		result = processor.execute(payload)
		
		# 根据结果状态返回响应，并在成功时写入用户栈日志（如提供）
		try:
			if result.get("ok"):
				user_id = payload.get("user_id") or payload.get("users")
				request_time = payload.get("request_time") or payload.get("timestamp")
				process_name = payload.get("task_type", DEFAULT_TASK_TYPE)
				hip = payload.get("hip")
				uuid_val = str(payload.get("uuid") or "").strip()
				if user_id and request_time and hip and uuid_val:
					log_system.append_or_replace_user_stack(
						hip_path=hip,
						user_id=user_id,
						process_name=process_name,
						uuid_val=uuid_val,
						request_time_iso=request_time,
						status="completed"
					)
				return jsonify(result)
			else:
				return jsonify(result), 500
		except Exception:
			# 日志失败不影响业务返回
			return jsonify(result) if result.get("ok") else (jsonify(result), 500)
			
	except Exception as e:
		return jsonify({
			"ok": False, 
			"error": str(e), 
			"traceback": traceback.format_exc()
		}), 500

def _parse_args() -> argparse.Namespace:
	"""解析命令行参数（host/port/debug）。"""
	parser = argparse.ArgumentParser(description="Houdini Task Dispatcher (Plugin-based)")
	parser.add_argument("--host", default="0.0.0.0")
	parser.add_argument("--port", type=int, default=5050)
	parser.add_argument("--debug", action="store_true")
	return parser.parse_args()

def main():
	"""启动 Flask 调度服务。"""
	args = _parse_args()
	
	print(f"启动 Houdini 任务调度服务...")
	print(f"支持的任务类型: {', '.join(get_supported_task_types())}")
	print(f"默认任务类型: {DEFAULT_TASK_TYPE}")
	print(f"服务地址: http://{args.host}:{args.port}")
	
	app.run(host=args.host, port=args.port, debug=args.debug, use_reloader=False)

if __name__ == "__main__":
	main()