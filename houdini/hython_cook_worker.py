# houdini/hython_cook_worker.py
"""
hython 工作脚本：在 hython 环境中执行 HIP 加载、设参与 cook。
运行方式（由调度服务调用）：
  hython houdini/hython_cook_worker.py --job C:/.../job.json
job.json:
{
  "hip": "C:/path/to/file.hip",
  "cook_node": "/obj/geo1/OUT",                    # 必须：要执行 cook 的节点
  "parm_node": "/obj/geo1/INPUT",                  # 可选：要设置参数的节点（默认与 cook_node 相同）
  "parms": { "seed": 3, "json_data": "{...}" }
}
执行完成后向 stdout 打印 JSON：
  { "ok": true/false, "cook_node": "...", "parm_node": "...", "elapsed_ms": 123, "node_errors": [...], ... }
"""
import sys
import os
import json
import time
import argparse
import traceback

def _load_job(job_path: str) -> dict:
	"""
	从指定路径加载 job 配置文件。

	Args:
		job_path (str): job.json 文件的绝对路径

	Returns:
		dict: 包含 hip、node、parms 等配置信息的字典

	Raises:
		FileNotFoundError: 当 job.json 文件不存在时
		json.JSONDecodeError: 当 job.json 格式不正确时
	"""
	with open(job_path, "r", encoding="utf-8") as f:
		return json.load(f)

# 设置节点参数函数
def _set_node_parms(node, parms: dict):
	"""
	为 Houdini 节点设置参数值。

	支持两种参数类型：
	1. 标量参数 (parm): 使用 parm.set(value) 设置单个值
	2. 元组参数 (parmTuple): 使用 parmTuple.set([...]) 设置多个值

	Args:
		node: Houdini 节点对象
		parms (dict): 参数字典，键为参数名，值为要设置的值

	Returns:
		list: 找不到的参数名列表，用于调试和错误报告

	Note:
		- 对于 parmTuple，如果传入的是标量值，会自动扩展为与 tuple 长度相同的数组
		- 例如：parmTuple("scale") 长度为 3，传入 value=2.0，会设置为 [2.0, 2.0, 2.0]
	"""
	missing = []
	for name, value in (parms or {}).items():
		parm = node.parm(name)
		if parm is not None:
			parm.set(value)
			continue
		tp = node.parmTuple(name)
		if tp is not None:
			if isinstance(value, (list, tuple)):
				tp.set(value)
			else:
				tp.set([value] * len(tp))
			continue
		missing.append(name)
	return missing

def _write_result(out_path: str, payload: dict) -> None:
	"""将结果写入回退文件（若提供了 out_path）。"""
	if not out_path:
		return
	try:
		with open(out_path, "w", encoding="utf-8") as f:
			json.dump(payload, f, ensure_ascii=False)
			f.flush()
	except Exception:
		pass

def main():
	parser = argparse.ArgumentParser()
	parser.add_argument("--job", required=True, help="job json 路径")
	parser.add_argument("--out", required=False, default="", help="结果回退文件路径（可选）")
	args = parser.parse_args()

	try:
		import hou  # 在 hython 中应可导入
	except Exception as e:
		payload = {"ok": False, "error": f"导入 hou 失败: {e}"}
		print(json.dumps(payload, ensure_ascii=False))
		_write_result(args.out, payload)
		sys.exit(1)

	try:
		job = _load_job(args.job)
		hip = job["hip"]
		cook_node_path = job["cook_node"]
		parm_node_path = job.get("parm_node", cook_node_path) # 默认与 cook_node 相同
		parms = job.get("parms", {})

		start = time.time()

		hou.hipFile.load(hip, ignore_load_warnings=True) # 加载hip文件
		cook_node = hou.node(cook_node_path) # 获取 cook 节点
		parm_node = hou.node(parm_node_path) # 获取 parm 节点

		# 如果节点不存在，则抛出异常
		if cook_node is None:
			raise RuntimeError(f"找不到 cook 节点: {cook_node_path}")
		if parm_node is None:
			raise RuntimeError(f"找不到 parm 节点: {parm_node_path}")

		missing = _set_node_parms(parm_node, parms) # 设置 parm 节点参数
		cook_node.cook(force=True) # 执行 cook 节点
		elapsed_ms = round((time.time() - start) * 1000)

		result = {
			"ok": True,
			"cook_node": cook_node.path(),
			"parm_node": parm_node.path(),
			"elapsed_ms": elapsed_ms,
			"node_errors": cook_node.errors(),
			"missing_parms": missing,
			"parms": parms
		}
		print(json.dumps(result, ensure_ascii=False))
		_write_result(args.out, result)
		sys.exit(0)

	except Exception as e:
		err = {
			"ok": False,
			"error": str(e),
			"traceback": traceback.format_exc()
		}
		print(json.dumps(err, ensure_ascii=False))
		_write_result(args.out, err)
		sys.exit(1)

if __name__ == "__main__":
	main()