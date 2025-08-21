# houdini/json2jpg.py
"""
JSON → JPG 转换脚本：

- 目标：读取生成的 {uuid}.json，并将像素数据转换为 JPG 图片。
- 约定：输入 JSON 位于 <hip_dir>/export/serve/<uuid>.json，输出 JPG 写入同目录 <uuid>.jpg。
- 调用方式：由调度服务在 hython 任务完成后异步触发，或手动运行。

命令行参数：
- --hip       HIP 文件路径（用于解析导出目录）
- --uuid      任务 UUID（定位 {uuid}.json）
- --wait-sec  可选，等待文件出现的秒数（默认 0，不等待）
- --out       可选，结果写入到该路径（JSON 格式），同时 stdout 也会打印同样的 JSON
 - --no-data  可选，不读取大文件内容，只返回是否存在与路径（减少IO与输出体积）

输出（stdout 及 --out）：
{
  "ok": true/false,
  "uuid": "...",
  "path_json": "<输入JSON路径>",
  "path_jpg": "<输出JPG路径>",
  "exists": true/false,             # 输入 JSON 是否存在
  "width": <int>,
  "height": <int>,
  "pixels_written": <int>,
  "error": <错误说明（可选）>
}
"""

import os
import json
import time
import argparse
import sys
from typing import Any, Optional, Tuple, List

try:
    from PIL import Image
except Exception:
    Image = None

# 根据 HIP 路径与 UUID 计算目标 JSON 文件路径
def build_target_path(hip_path: str, uuid_val: str) -> Optional[str]:
    """根据 HIP 路径与 UUID 计算目标 JSON 文件路径。

    规则：<hip_dir>/export/serve/<uuid>.json
    """
    hip_dir = os.path.dirname(hip_path or "")
    if not hip_dir or not os.path.isdir(hip_dir) or not uuid_val:
        return None
    return os.path.join(hip_dir, "export", "serve", f"{uuid_val}.json")

# 读取并解析 JSON 文件
def read_json_file(path: str) -> Any:
    """读取并解析 JSON 文件。"""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

#根据 total_prims 推断画布尺寸（正方形）
def infer_dimensions(total_prims: int) -> Tuple[int, int]:
    """根据 total_prims 推断画布尺寸（正方形）。

    要求 total_prims 为完全平方数；返回 (width, height)。
    """
    import math
    side = int(round(math.sqrt(max(0, int(total_prims)))))
    if side * side != int(total_prims):
        raise ValueError("total_prims 不是完全平方数，无法构建正方形画布")
    return side, side


def determine_dimensions(total_prims: int, pixels_len: int) -> Tuple[int, int]:
    """优先根据 total_prims 推断，否则尝试基于 pixels_len 推断。"""
    try:
        if int(total_prims) > 0:
            return infer_dimensions(int(total_prims))
    except Exception:
        pass
    # 回退：使用像素数量
    if pixels_len > 0:
        import math
        side = int(math.sqrt(pixels_len))
        if side * side == pixels_len:
            return side, side
    raise ValueError("无法推断尺寸：total_prims 与 pixels 数量均非完全平方数")


def normalize_pixels(pixels_raw: Any) -> List[List[float]]:
    """将 pixels 归一化为按索引顺序的 [r,g,b] 列表。

    支持两种输入：
    - 列表：[[r,g,b], ...]
    - 字典：{"0": [r,g,b], "1": [r,g,b], ...}
    """
    if isinstance(pixels_raw, list):
        return pixels_raw
    if isinstance(pixels_raw, dict):
        # 将键当作索引排序填充
        pairs = []
        for k, v in pixels_raw.items():
            try:
                idx = int(k)
            except Exception:
                continue
            pairs.append((idx, v))
        if not pairs:
            return []
        pairs.sort(key=lambda x: x[0])
        max_index = pairs[-1][0]
        out = [[0, 0, 0] for _ in range(max_index + 1)]
        for idx, rgb in pairs:
            out[idx] = rgb
        return out
    return []


def pixels_to_image(pixels: list, width: int, height: int) -> Image.Image:
    """根据像素数组构建 PIL 图片对象。

    约定：pixels 为 RGB 列表，分量范围 [0,1] 浮点数。
    像素索引从左下角开始，先 X 递增（左→右），再 Y 递增（下→上）。
    """
    if Image is None:
        raise RuntimeError("pillow 未安装，无法生成图片，请先 pip install pillow")

    # 创建空图（RGB，0..255）
    img = Image.new("RGB", (width, height))
    # 逐像素写入：将 [0,1] 转为 [0,255]
    # 注意输入坐标系为左下角原点，而 PIL 的 (0,0) 在左上角，因此需要翻转 Y
    def clamp01(x: float) -> float:
        return 0.0 if x < 0 else (1.0 if x > 1 else x)

    for idx, rgb in enumerate(pixels):
        if idx >= width * height:
            break
        x = idx % width
        y_from_bottom = idx // width
        y = (height - 1) - y_from_bottom  # 将下原点坐标映射到上原点坐标
        try:
            r, g, b = rgb
        except Exception:
            r, g, b = 0, 0, 0
        R = int(round(clamp01(float(r)) * 255))
        G = int(round(clamp01(float(g)) * 255))
        B = int(round(clamp01(float(b)) * 255))
        img.putpixel((x, y), (R, G, B))
    return img


def save_jpeg(img: Image.Image, path: str) -> None:
    """保存 JPG 图片（高质量、禁用子采样，尽量减少边缘模糊）。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.save(path, format="JPEG", quality=100, subsampling=0, optimize=False, progressive=False)


def save_png(img: Image.Image, path: str) -> None:
    """保存 PNG 图片（无损，像素完美保真）。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.save(path, format="PNG", compress_level=6)

# 如果提供了 out_path，则将结果写入该文件
def write_result_if_needed(out_path: Optional[str], payload: dict) -> None:
    """如果提供了 out_path，则将结果写入该文件。"""
    if not out_path:
        return
    try:
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.flush()
    except Exception:
        # 忽略写入失败
        pass


def main() -> int:
    """入口：解析参数，尝试读取 <hip_dir>/export/serve/<uuid>.json 并输出结果。"""
    parser = argparse.ArgumentParser(description="Read generated JSON by uuid (placeholder for JSON→JPG)")
    parser.add_argument("--hip", required=True, help="HIP 文件路径")
    parser.add_argument("--uuid", required=True, help="任务 UUID")
    parser.add_argument("--wait-sec", type=float, default=0.0, help="若文件不存在，等待的秒数（默认0）")
    parser.add_argument("--out", default="", help="结果回写到此路径（可选）")
    parser.add_argument("--no-data", action="store_true", help="不读取文件数据，只返回存在性等元信息")
    args = parser.parse_args()

    result = {
        "ok": False,
        "uuid": args.uuid,
        "path_json": None,
        "path_jpg": None,
        "exists": False,
        "width": None,
        "height": None,
        "pixels_written": 0,
    }

    try:
        target_path = build_target_path(args.hip, args.uuid)
        result["path_json"] = target_path
        if not target_path:
            result["error"] = "无法解析目标路径（检查 hip 与 uuid）"
            print(json.dumps(result, ensure_ascii=False))
            sys.stdout.flush()
            write_result_if_needed(args.out, result)
            return 1

        deadline = time.time() + max(0.0, args.wait_sec)
        while True:
            if os.path.isfile(target_path):
                result["exists"] = True
                try:
                    data = read_json_file(target_path)
                    # 解析像素（支持列表或映射）并推断尺寸
                    pixels = normalize_pixels(data.get("pixels"))
                    total_prims_val = int(data.get("total_prims", 0)) if str(data.get("total_prims", "")).strip() != "" else 0
                    width, height = determine_dimensions(total_prims_val, len(pixels))
                    result["width"], result["height"] = width, height
                    # 当 --no-data 时，只进行存在性与元信息确认，不生成图
                    if not args.no_data:
                        img = pixels_to_image(pixels, width, height)
                        base = os.path.splitext(target_path)[0]
                        jpg_path = base + ".jpg"
                        png_path = base + ".png"
                        # 同时输出 JPG（尽量减少伪影）与 PNG（像素完美）
                        # save_jpeg(img, jpg_path)
                        save_png(img, png_path)
                        result["path_jpg"] = jpg_path
                        result["path_png"] = png_path
                        result["pixels_written"] = min(len(pixels), width * height)
                    result["ok"] = True
                except Exception as e:
                    result["error"] = f"读取/解析/生成失败: {e}"
                break
            if time.time() >= deadline:
                break
            time.sleep(0.5)

        print(json.dumps(result, ensure_ascii=False))
        sys.stdout.flush()
        write_result_if_needed(args.out, result)
        return 0 if result.get("ok") else 2

    except Exception as e:
        result["error"] = str(e)
        print(json.dumps(result, ensure_ascii=False))
        sys.stdout.flush()
        write_result_if_needed(args.out, result)
        return 1


if __name__ == "__main__":
    sys.exit(main())