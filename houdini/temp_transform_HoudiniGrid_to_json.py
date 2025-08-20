"""
Houdini 内部 Python 节点临时代码：将棋盘格平面 grid 结构输出为 JSON 格式

使用方法：
1. 在 Houdini 中创建一个 Python 节点
2. 将此代码复制到 Python 节点的代码编辑器中
3. 确保上游有包含 prim_index 和 Cd 属性的几何数据
4. 运行后会在指定路径生成 JSON 文件

输出格式：
{
  "0": [1.0, 0.0, 0.0],    # prim_index=0 的红色像素
  "1": [0.0, 1.0, 0.0],    # prim_index=1 的绿色像素
  "2": [0.0, 0.0, 1.0],    # prim_index=2 的蓝色像素
  ...
}
"""

import hou
import json
import os

def export_grid_to_json(output_path=None):
    """
    将当前节点的几何数据导出为 JSON 格式
    
    Args:
        output_path (str, optional): 输出文件路径。如果不指定，将在桌面创建文件。
    
    Returns:
        str: 输出文件的完整路径
    """
    # 获取当前节点的几何数据
    node = hou.pwd()
    geo = node.geometry()
    
    if not geo:
        print("错误：没有几何数据")
        return None
    
    # 检查必要的属性
    if not geo.findPrimAttrib("prim_index"):
        print("错误：找不到 prim_index 属性")
        return None
    
    if not geo.findPrimAttrib("Cd"):
        print("错误：找不到 Cd 颜色属性")
        return None
    
    # 构建像素数据字典
    pixel_data = {}
    
    # 遍历所有 prim（像素）
    for prim in geo.prims():
        # 获取 prim_index 作为 key
        prim_index = prim.attribValue("prim_index")
        
        # 获取 Cd 颜色属性作为 value
        color = prim.attribValue("Cd")
        
        # 将颜色值转换为列表格式（RGB）
        if hasattr(color, '__iter__'):
            color_list = [float(c) for c in color]
        else:
            color_list = [float(color)]
        
        # 存储到字典中
        pixel_data[str(prim_index)] = color_list
    
    # 如果没有指定输出路径，则在桌面创建文件
    if not output_path:
        desktop = os.path.expanduser("~/Desktop")
        output_path = os.path.join(desktop, "houdini_grid_export.json")
    
    # 确保输出目录存在
    output_dir = os.path.dirname(output_path)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    # 写入 JSON 文件
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(pixel_data, f, indent=2, ensure_ascii=False)
        
        print(f"成功导出 {len(pixel_data)} 个像素到: {output_path}")
        print(f"JSON 文件大小: {os.path.getsize(output_path)} 字节")
        
        return output_path
        
    except Exception as e:
        print(f"导出失败: {e}")
        return None

def export_with_metadata(output_path=None):
    """
    导出带元数据的 JSON 格式，包含网格信息和统计
    
    Args:
        output_path (str, optional): 输出文件路径
    
    Returns:
        str: 输出文件的完整路径
    """
    node = hou.pwd()
    geo = node.geometry()
    
    if not geo:
        print("错误：没有几何数据")
        return None
    
    # 构建完整的数据结构
    export_data = {
        "metadata": {
            "total_prims": len(geo.prims()),
            "total_points": len(geo.points()),
            "node_path": node.path()
        },
        "pixels": {}
    }
    
    # 检查并获取属性
    prim_index_attrib = geo.findPrimAttrib("prim_index")
    cd_attrib = geo.findPrimAttrib("Cd")
    
    if not prim_index_attrib or not cd_attrib:
        print("错误：缺少必要的属性 (prim_index 或 Cd)")
        return None
    
    # 收集像素数据
    for prim in geo.prims():
        prim_index = prim.attribValue("prim_index")
        color = prim.attribValue("Cd")
        
        # 转换颜色为列表
        if hasattr(color, '__iter__'):
            color_list = [float(c) for c in color]
        else:
            color_list = [float(color)]
        
        export_data["pixels"][str(prim_index)] = color_list
    
    # 设置输出路径
    if not output_path:
        desktop = os.path.expanduser("~/Desktop")
        output_path = os.path.join(desktop, "houdini_grid_with_metadata.json")
    
    # 写入文件
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, indent=2, ensure_ascii=False)
        
        print(f"成功导出带元数据的 JSON 到: {output_path}")
        print(f"包含 {len(export_data['pixels'])} 个像素")
        
        return output_path
        
    except Exception as e:
        print(f"导出失败: {e}")
        return None

# 主执行函数 - 在 Houdini Python 节点中调用
def main():
	"""
	主函数：在 Houdini Python 节点中调用此函数来执行导出
	"""
	print("开始导出 Houdini Grid 到 JSON...")
	
	# 获取当前节点
	node = hou.pwd()
	
	# 从节点的 export_path 参数获取导出路径
	export_path = node.parm("export_path").eval()
	
	# 检查是否设置了导出路径
	if export_path and export_path.strip():
		print(f"使用指定的导出路径: {export_path}")
		# 方式1：简单导出（只包含像素数据）
		# result = export_grid_to_json(export_path)
		
		# 方式2：带元数据的导出（推荐）
		result = export_with_metadata(export_path)
	else:
		print("未设置 export_path 参数，使用默认桌面路径")
		# 方式1：简单导出（只包含像素数据）
		# result = export_grid_to_json()
		
		# 方式2：带元数据的导出（推荐）
		result = export_with_metadata()
	
	if result:
		print(f"导出完成！文件位置: {result}")
		
		# 可选：在 Houdini 中显示文件路径
		# hou.ui.displayMessage(f"导出完成！\n文件位置: {result}")
	else:
		print("导出失败！")
		# hou.ui.displayMessage("导出失败！请检查控制台输出。")


main()
