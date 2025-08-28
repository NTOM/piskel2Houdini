#!/usr/bin/env python
"""
在 Houdini 无界面环境下执行：
1) 读取 --job 指向的 JSON：{ hip, cook_node, parm_node?, uuid, parms? }
2) 打开HIP，设置参数（如果提供），
3) 在 cook_node 上按下名为 "execute" 的按钮参数（pressButton），用于触发缓存/导出。
4) 将执行结果以 JSON 打印到 stdout，并可选写入 --out 文件。
"""
import json
import sys
import os
import argparse
import time


def read_job(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def write_json(obj, out_path=None):
    text = json.dumps(obj, ensure_ascii=False)
    sys.stdout.write(text)
    sys.stdout.flush()
    if out_path:
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(text)


def set_parms(node, parms):
    if not parms:
        return {}
    # 统一小写键
    norm = {str(k).lower(): v for k, v in parms.items()}
    for k, v in norm.items():
        try:
            p = node.parm(k)
            if p is not None:
                p.set(v)
        except Exception:
            pass
    return norm


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--job', required=True)
    parser.add_argument('--out')
    args = parser.parse_args()

    import hou  # Houdini module

    start = time.time()
    try:
        job = read_job(args.job)
        hip = job['hip']
        cook_node_paths = job['cook_node']  # 现在可能是数组或字符串
        parm_node_path = job.get('parm_node') or (cook_node_paths[0] if isinstance(cook_node_paths, list) else cook_node_paths)
        uuid = job.get('uuid')
        parms = job.get('parms', {})

        hou.hipFile.load(hip)
        parm_node = hou.node(parm_node_path)
        if parm_node is None:
            raise RuntimeError('parm_node not found: ' + parm_node_path)

        # 先设置参数
        applied = set_parms(parm_node, parms)

        # 处理cook节点（支持单个或多个）
        cook_results = []
        if isinstance(cook_node_paths, list):
            # 多个cook节点，按顺序执行
            for i, cook_node_path in enumerate(cook_node_paths):
                try:
                    cook_result = execute_cook_node(cook_node_path, i, start)
                    cook_results.append(cook_result)
                    
                    # 如果某个节点失败，停止执行
                    if not cook_result['ok']:
                        break
                        
                except Exception as e:
                    cook_results.append({
                        'ok': False,
                        'cook_node': cook_node_path,
                        'index': i,
                        'error': str(e)
                    })
                    break
        else:
            # 单个cook节点（向后兼容）
            cook_result = execute_cook_node(cook_node_paths, 0, start)
            cook_results.append(cook_result)

        # 判断整体是否成功
        overall_ok = all(result['ok'] for result in cook_results)
        
        elapsed = int((time.time() - start) * 1000)
        result = {
            'ok': overall_ok,
            'uuid': uuid,
            'hip': hip,
            'cook_nodes': cook_node_paths if isinstance(cook_node_paths, list) else [cook_node_paths],
            'parm_node': parm_node_path,
            'elapsed_ms': elapsed,
            'parms': applied,
            'cook_results': cook_results,
            'total_cook_nodes': len(cook_results),
            'successful_cook_nodes': sum(1 for r in cook_results if r['ok'])
        }
        write_json(result, args.out)
    except Exception as e:
        err = {
            'ok': False,
            'error': str(e),
        }
        write_json(err, args.out)


def execute_cook_node(cook_node_path, index, start_time):
    """执行单个cook节点的逻辑"""
    cook_node = hou.node(cook_node_path)
    if cook_node is None:
        raise RuntimeError('cook_node not found: ' + cook_node_path)

    # 按下 execute 按钮
    btn = cook_node.parm('execute')
    if btn is None:
        raise RuntimeError('execute button parm not found on cook_node: ' + cook_node_path)
    
    # 记录按钮按下前的状态
    prev_cook_state = cook_node.parm('cook').eval() if cook_node.parm('cook') else None
    
    # 按下按钮
    btn.pressButton()
    
    # 等待一下让 cook 完成
    time.sleep(0.5)
    
    # 检查 cook 状态变化或是否有错误
    current_cook_state = cook_node.parm('cook').eval() if cook_node.parm('cook') else None
    has_error = cook_node.errors() or cook_node.warnings()
    
    # 判断是否成功：如果没有错误，且按钮按下没有抛出异常，就认为成功
    ok = True  # 默认认为成功，除非有明确的错误
    
    # 如果有错误，标记为失败
    if has_error:
        ok = False

    elapsed = int((time.time() - start_time) * 1000)
    return {
        'ok': ok,
        'cook_node': cook_node_path,
        'index': index,
        'elapsed_ms': elapsed,
        'cook_state_changed': prev_cook_state != current_cook_state if prev_cook_state is not None else None,
        'has_errors': bool(has_error),
    }


if __name__ == '__main__':
    main()


