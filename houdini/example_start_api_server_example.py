# Houdini API 服务端
# 作用：在 Houdini Python 环境中启动一个 Flask 服务，通过 HTTP 接口驱动指定节点烹饪
#      并将几何点（点云）转换为轻量化 JSON 返回，便于外部（如 UE/工具链）消费。
# 运行：
#   python start_api_server.py -c /path/to/config.json
# 配置 config.json 字段：
#   - "file": 需要加载的 .hip 文件绝对路径
#   - "node": 要烹饪的节点路径（例如：/obj/geo1/OUT_result）
#   - "port": 服务监听端口
#
# 注意：本脚本应在包含 Houdini Python 的环境中运行（hython 或已正确设置的 Python）
# -----------------------------------------------------------------------------
import sys

# 将 Houdini 的 Python 依赖路径注入到 sys.path 中，确保能够导入 hou 与相关包
sys.path.append("/opt/hfs19.5/python/lib/python3.9/site-packages-forced")
sys.path.append("/opt/hfs19.5/houdini/python3.9libs")
from flask import Flask, jsonify, request, abort
import sys

print(sys.path)
import os, time, json
import datetime
import traceback

app = Flask(__name__)

import hou

print(hou.houdiniPath())
import argparse
import random

# 解析命令行参数，读取外部配置文件路径
parser = argparse.ArgumentParser()
parser.add_argument('-c', "--config", type=str, default="")
args = parser.parse_args()
config = args.config

# 读取配置：包含 .hip 文件路径、节点路径与端口
cfg = json.load(open(config, 'r'))

# 加载指定的 HIP 工程文件。ignore_load_warnings=True 用于忽略加载过程中的非致命警告
hou.hipFile.load(cfg["file"], ignore_load_warnings=True)

# 记录并获取需要烹饪的节点
node_path = cfg["node"]
node = hou.node(node_path)
print(node_path)


@app.route('/region/plant', methods=['POST'])
def pcg_region_plant():
    """
    区域种植接口（POST /region/plant）

    请求体 JSON 示例：
    {
        "region": "{\"vetex\": [[50.0,-0.5,-50.0],[-50.0,-0.5,-50.0],[-50.0,-0.5,50.0],[50.0,-0.5,50.0]]}",
        "seed": 2
    }

    说明：
    - region: 作为字符串传入的顶点/区域 JSON（会直接写入到节点参数 json_data）
    - seed  : 随机种子（会直接写入到节点参数 seed）

    返回 JSON：
    {
      "scene": {
        "actors": [
          {"typeId": int, "pos": [x,z,y], "sca": [sx,sy,sz], "rot": [qx,qy,qz,qw]},
          ...
        ],
        "group": {},          # 预留：分组信息
        "relation": []        # 预留：关系信息
      }
    }
    """
    data = request.get_json()
    print("request data:", data)

    # vextex_data = '{"vetex": [[50.0, -0.5, -50.0], [-50.0, -0.5, -50.0], [-50.0, -0.5, 50.0], [50.0, -0.5, 50.0]]}'
    # seed_data = 2

    # 从请求中读取区域描述与随机种子
    vertex_data = data['region']
    seed_data = data['seed']

    # 将请求内容写入到 Houdini 节点参数：json_data 与 seed
    json_data_parm = hou.parm(node_path + '/json_data')
    json_data_parm.set(vertex_data)

    seed_parm = hou.parm(node_path + '/seed')
    seed_parm.set(seed_data)

    try:
        # 强制烹饪节点，确保参数变更后输出更新
        node.cook(force=True)
    except Exception as e:
        # 打印烹饪失败的详细信息，便于排查
        print("Error happened while cooking node ", e, e.description(), e.instanceMessage())
        print("Details:", node.errors())
        print(traceback.print_exc())

    # 在线服务：从节点几何中读取点云数据，并转换为轻量化的 actors 数组
    geo = node.geometry()
    points = geo.points()  # 点云对象读取
    data = []  # 点云数据写入

    relation = []  # 预留：关系信息（未使用）
    group_map = {} # 预留：分组信息（未使用）

    # 遍历点云
    for idx, p in enumerate(points):
        scale = p.attribValue("pscale")
        typeId = p.attribValue("typeId")

        # pos and sca, Houdini TO UE, 仅用于在线阶段
        # 将 Houdini 坐标转换为 UE 使用的顺序（x,z,y），并对数值做 3 位小数的四舍五入。
        # 为每个点构建字典：typeId（素材类型）、pos（位置 XZY）、sca（等比缩放）、rot（四元数，默认无旋转）。
        d = {
            "typeId": typeId,
            "pos": [round(p.position()[0], 3), round(p.position()[2], 3), round(p.position()[1], 3)],
            "sca": [scale, scale, scale],
            "rot": [0, 0, 0, 1],
        }

        data.append(d)

    # 将点云数据存储在res中
    res = {
        'actors': data,
        'group': group_map,
        'relation': relation
    }

    return jsonify({'scene': res})


if __name__ == '__main__':
    # 启动 Flask 服务。host=0.0.0.0 允许外部访问；debug=True 便于调试（生产环境建议关闭）。
    app.run(host='0.0.0.0', debug=True, port=cfg['port'])
