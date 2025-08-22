# houdini/png2json.py
"""
PNG → JSON 转换脚本：

- 目标：读取PNG图片，并将像素数据转换为与houdini_export_json.py相同格式的JSON
- 约定：输入PNG文件，输出JSON格式与houdini_export_json.py完全一致
- 调用方式：命令行运行，或由其他服务调用

命令行参数：
- --input      输入PNG文件路径（必需）
- --output     输出JSON文件路径（可选，默认与输入文件同目录）
- --format     输出格式：simple（简单像素数据）或 metadata（带元数据，默认）

输出格式（与houdini_export_json.py一致）：
简单格式：
{
  "0": [1.0, 0.0, 0.0],    # prim_index=0 的红色像素
  "1": [0.0, 1.0, 0.0],    # prim_index=1 的绿色像素
  "2": [0.0, 0.0, 1.0],    # prim_index=2 的蓝色像素
  ...
}

带元数据格式：
{
  "metadata": {
    "total_prims": 1024,
    "total_points": 1024,
    "source_image": "input.png",
    "width": 32,
    "height": 32
  },
  "pixels": {
    "0": [1.0, 0.0, 0.0],
    "1": [0.0, 1.0, 0.0],
    ...
  }
}
"""

import os
import json
import argparse
import sys
from typing import Any, Optional, Tuple, List, Dict

try:
    from PIL import Image
except ImportError:
    print("错误：需要安装 Pillow 库。请运行: pip install pillow")
    sys.exit(1)

def load_image(image_path: str) -> Image.Image:
    """加载PNG图片文件"""
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"图片文件不存在: {image_path}")
    
    try:
        img = Image.open(image_path)
        if img.mode not in ['RGB', 'RGBA']:
            img = img.convert('RGB')
        return img
    except Exception as e:
        raise RuntimeError(f"无法加载图片 {image_path}: {e}")

def image_to_pixels(img: Image.Image) -> Tuple[List[List[float]], int, int]:
    """
    将PIL图片转换为像素数组
    
    Args:
        img: PIL图片对象
    
    Returns:
        (pixels, width, height): 像素数组、宽度、高度
    """
    width, height = img.size
    
    # 创建像素数组，从左下角开始，先X递增，再Y递增
    # 这与json2jpg.py中的坐标系统保持一致
    pixels = []
    
    for y in range(height - 1, -1, -1):  # 从下到上
        for x in range(width):            # 从左到右
            pixel = img.getpixel((x, y))
            
            # 处理RGBA和RGB格式
            if len(pixel) == 4:  # RGBA
                r, g, b, a = pixel
                # 如果有透明度，可以混合背景色（这里简单忽略alpha）
            else:  # RGB
                r, g, b = pixel
            
            # 将0-255转换为0.0-1.0范围
            r_norm = r / 255.0
            g_norm = g / 255.0
            b_norm = b / 255.0
            
            pixels.append([r_norm, g_norm, b_norm])
    
    return pixels, width, height

def create_simple_json(pixels: List[List[float]]) -> Dict[str, List[float]]:
    """创建简单格式的JSON（只有像素数据）"""
    result = {}
    for i, pixel in enumerate(pixels):
        result[str(i)] = pixel
    return result

def create_metadata_json(pixels: List[List[float]], width: int, height: int, source_image: str) -> Dict[str, Any]:
    """创建带元数据的JSON格式"""
    return {
        "metadata": {
            "total_prims": len(pixels),
            "total_points": len(pixels),
            "source_image": os.path.basename(source_image),
            "width": width,
            "height": height
        },
        "pixels": create_simple_json(pixels)
    }

def save_json(data: Any, output_path: str) -> None:
    """保存JSON文件"""
    try:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"成功保存JSON文件: {output_path}")
    except Exception as e:
        raise RuntimeError(f"保存JSON文件失败: {e}")

def main() -> int:
    """主函数"""
    parser = argparse.ArgumentParser(description="将PNG图片转换为JSON格式")
    parser.add_argument("--input", "-i", required=True, help="输入PNG文件路径")
    parser.add_argument("--output", "-o", default="", help="输出JSON文件路径（可选）")
    parser.add_argument("--format", "-f", choices=["simple", "metadata"], default="metadata", 
                       help="输出格式：simple（简单）或metadata（带元数据，默认）")
    
    args = parser.parse_args()
    
    try:
        # 检查输入文件
        if not os.path.exists(args.input):
            print(f"错误：输入文件不存在: {args.input}")
            return 1
        
        # 加载图片
        print(f"正在加载图片: {args.input}")
        img = load_image(args.input)
        
        # 转换为像素数组
        print("正在转换像素数据...")
        pixels, width, height = image_to_pixels(img)
        print(f"图片尺寸: {width}x{height}, 总像素数: {len(pixels)}")
        
        # 确定输出路径
        if args.output:
            output_path = args.output
        else:
            # 默认与输入文件同目录，扩展名改为.json
            base_name = os.path.splitext(args.input)[0]
            output_path = f"{base_name}.json"
        
        # 创建JSON数据
        if args.format == "simple":
            json_data = create_simple_json(pixels)
            print("使用简单格式（只包含像素数据）")
        else:
            json_data = create_metadata_json(pixels, width, height, args.input)
            print("使用元数据格式（包含图片信息和像素数据）")
        
        # 保存JSON文件
        save_json(json_data, output_path)
        
        # 输出统计信息
        print(f"转换完成！")
        print(f"输入文件: {args.input}")
        print(f"输出文件: {output_path}")
        print(f"像素数量: {len(pixels)}")
        print(f"JSON文件大小: {os.path.getsize(output_path)} 字节")
        
        return 0
        
    except Exception as e:
        print(f"错误: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
