#!/usr/bin/env python
"""
PNG到JSON转换脚本：将PNG图像转换为JSON格式，供Houdini使用。

输入：<hip_dir>/export/serve/<uuid>.png
输出：<hip_dir>/export/serve/<uuid>.json

JSON格式：
{
  "ok": true,
  "uuid": "uuid-string",
  "path_png": "png文件路径",
  "path_json": "json文件路径",
  "width": 图像宽度,
  "height": 图像高度,
  "total_prims": 总像素数,
  "pixels": {
    "0": [r, g, b],  # 像素索引 -> RGB值 (0-1范围)
    "1": [r, g, b],
    ...
  }
}
"""
import json
import sys
import os
import argparse
from typing import Dict, List, Tuple, Any

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    print("警告: Pillow库未安装，无法处理PNG图像")


def build_target_path(hip_dir: str, uuid: str) -> Tuple[str, str]:
    """构建PNG和JSON文件路径。"""
    png_path = os.path.join(hip_dir, "export", "serve", f"{uuid}.png")
    json_path = os.path.join(hip_dir, "export", "serve", f"{uuid}.json")
    return png_path, json_path


def read_png_image(png_path: str) -> Tuple[Image.Image, int, int]:
    """读取PNG图像并返回图像对象和尺寸。"""
    if not PIL_AVAILABLE:
        raise RuntimeError("Pillow库未安装，无法读取PNG图像")
    
    if not os.path.isfile(png_path):
        raise FileNotFoundError(f"PNG文件不存在: {png_path}")
    
    img = Image.open(png_path)
    width, height = img.size
    return img, width, height


def image_to_pixels(img: Image.Image) -> Dict[str, List[float]]:
    """将图像转换为像素字典。像素索引从0开始，从左下角开始，X增加，Y增加。"""
    width, height = img.size
    pixels = {}
    
    # 转换为RGB模式（如果不是的话）
    if img.mode != 'RGB':
        img = img.convert('RGB')
    
    # 从图像数据创建像素字典
    # 注意：PIL的坐标系统是左上角为(0,0)，我们需要转换为左下角为(0,0)
    for y in range(height):
        for x in range(width):
            # PIL坐标 -> 我们的索引系统
            pil_x, pil_y = x, height - 1 - y  # 翻转Y轴
            index = pil_y * width + pil_x
            
            # 获取RGB值并转换为0-1范围
            r, g, b = img.getpixel((x, y))
            pixels[str(index)] = [r/255.0, g/255.0, b/255.0]
    
    return pixels


def save_json(data: Dict[str, Any], json_path: str) -> None:
    """保存JSON数据到文件。"""
    os.makedirs(os.path.dirname(json_path), exist_ok=True)
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()


def main():
    """主函数。"""
    parser = argparse.ArgumentParser(description="将PNG图像转换为JSON格式")
    parser.add_argument('--hip', required=True, help='HIP文件所在目录')
    parser.add_argument('--uuid', required=True, help='任务UUID')
    parser.add_argument('--wait-sec', type=float, default=0, help='等待PNG文件生成的秒数')
    parser.add_argument('--out', help='输出结果到指定文件')
    args = parser.parse_args()
    
    if not PIL_AVAILABLE:
        result = {
            "ok": False,
            "error": "Pillow库未安装，请运行: pip install Pillow"
        }
        print(json.dumps(result, ensure_ascii=False))
        if args.out:
            with open(args.out, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
        return
    
    try:
        # 构建文件路径
        png_path, json_path = build_target_path(args.hip, args.uuid)
        
        # 等待PNG文件生成（如果需要）
        if args.wait_sec > 0:
            import time
            start_time = time.time()
            while not os.path.isfile(png_path) and (time.time() - start_time) < args.wait_sec:
                time.sleep(0.1)
        
        # 读取PNG图像
        img, width, height = read_png_image(png_path)
        total_prims = width * height
        
        # 转换为像素数据
        pixels = image_to_pixels(img)
        
        # 保存JSON文件
        json_data = {
            "ok": True,
            "uuid": args.uuid,
            "path_png": png_path,
            "path_json": json_path,
            "width": width,
            "height": height,
            "total_prims": total_prims,
            "pixels": pixels
        }
        
        save_json(json_data, json_path)
        
        # 构建结果
        result = {
            "ok": True,
            "uuid": args.uuid,
            "path_png": png_path,
            "path_json": json_path,
            "width": width,
            "height": height,
            "total_prims": total_prims,
            "pixels_count": len(pixels)
        }
        
        # 输出结果
        print(json.dumps(result, ensure_ascii=False))
        
        # 可选：写入输出文件
        if args.out:
            with open(args.out, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
                
    except Exception as e:
        result = {
            "ok": False,
            "error": str(e),
            "uuid": args.uuid
        }
        print(json.dumps(result, ensure_ascii=False))
        if args.out:
            with open(args.out, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2)


if __name__ == '__main__':
    main()
