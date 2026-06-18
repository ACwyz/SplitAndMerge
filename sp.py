#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
综合分割器 - 支持视频（-v）和文件（-f）两种模式
用法：
  视频模式: python split_unified.py -v input.mp4 [-s 20] [-o output_dir]
  文件模式: python split_unified.py -f input.bin [-s 20] [-o output_dir]

自动检测 FFmpeg 是否安装，未安装时在 Windows 下自动执行 winget install ffmpeg（显示安装过程）。
安装完成后提示用户重启终端以使环境变量生效。
分片数量上限 9999。

输出目录后缀：
  视频模式：原文件名_vsplit
  文件模式：原文件名_fsplit
"""

import os
import sys
import json
import argparse
import subprocess
import shutil

# ---------- 检测并安装 FFmpeg ----------
def check_and_install_ffmpeg():
    """检测 FFmpeg 是否可用，若不可用且为 Windows 则尝试自动安装（显示安装过程）"""
    ffmpeg_path = shutil.which('ffmpeg')
    if ffmpeg_path is not None:
        print(f"✅ 检测到 FFmpeg: {ffmpeg_path}")
        return True

    print("⚠️ 未找到 FFmpeg。", file=sys.stderr)

    # 仅 Windows 下尝试自动安装
    if sys.platform == 'win32':
        print("正在使用 winget 自动安装 FFmpeg ...", file=sys.stderr)
        try:
            # 直接执行，将输出显示在终端（不捕获）
            subprocess.run(['winget', 'install', 'ffmpeg'], check=True)
            # 安装后重新检查环境变量（可能需要刷新）
            if shutil.which('ffmpeg') is not None:
                print("✅ FFmpeg 安装成功！")
                return True
            else:
                print("✅ FFmpeg 已安装，但当前终端尚未刷新环境变量。", file=sys.stderr)
                print("请 **重启此终端** 或 **重新打开命令提示符**，然后再次运行本脚本。", file=sys.stderr)
                return False  # 返回 False，让主程序退出
        except FileNotFoundError:
            print("❌ 未找到 winget 命令。请手动安装 FFmpeg：", file=sys.stderr)
            print("   方法一：使用 winget install ffmpeg (需 Windows 10/11)", file=sys.stderr)
            print("   方法二：从 https://ffmpeg.org/download.html 下载并手动配置 PATH", file=sys.stderr)
            return False
        except subprocess.CalledProcessError as e:
            print(f"❌ winget 安装失败，错误码: {e.returncode}", file=sys.stderr)
            print("请手动安装 FFmpeg。", file=sys.stderr)
            return False
    else:
        # 非 Windows 系统，给出手动安装指引
        print("请手动安装 FFmpeg:", file=sys.stderr)
        print("  - macOS: brew install ffmpeg", file=sys.stderr)
        print("  - Ubuntu/Debian: sudo apt install ffmpeg", file=sys.stderr)
        print("  - Fedora: sudo dnf install ffmpeg", file=sys.stderr)
        print("  - 其他系统请参考 https://ffmpeg.org/download.html", file=sys.stderr)
        return False

# ---------- 文件分割（纯 Python） ----------
def split_file(input_path, chunk_size_mb=20, output_dir=None):
    if not os.path.isfile(input_path):
        print(f"错误：文件不存在 - {input_path}", file=sys.stderr)
        return False

    dir_name = os.path.dirname(input_path)
    base_name = os.path.basename(input_path)

    if output_dir is None:
        # 文件模式使用 _fsplit 后缀
        output_dir = os.path.join(dir_name, f"{base_name}_fsplit")
    os.makedirs(output_dir, exist_ok=True)

    total_size = os.path.getsize(input_path)
    if total_size == 0:
        print("文件大小为0，无法分割。", file=sys.stderr)
        return False

    chunk_size_bytes = chunk_size_mb * 1024 * 1024
    part_number = 1
    bytes_processed = 0
    manifest = {
        "original_name": base_name,
        "total_size": total_size,
        "chunk_size_mb": chunk_size_mb,
        "parts": []
    }

    try:
        with open(input_path, 'rb') as infile:
            while bytes_processed < total_size:
                remaining = total_size - bytes_processed
                bytes_to_read = min(chunk_size_bytes, remaining)
                data = infile.read(bytes_to_read)
                if not data:
                    break

                part_name = f"{base_name}.part{part_number:04d}"   # 4位数字，支持9999
                part_path = os.path.join(output_dir, part_name)

                with open(part_path, 'wb') as outfile:
                    outfile.write(data)

                manifest["parts"].append({
                    "name": part_name,
                    "size": len(data)
                })

                print(f"生成分片: {part_name} (大小: {len(data)} 字节)")
                bytes_processed += len(data)
                part_number += 1

                if part_number > 9999:
                    print("警告：分片数量超过9999，考虑增大分片大小。", file=sys.stderr)
                    break

        manifest_path = os.path.join(output_dir, "manifest.json")
        with open(manifest_path, 'w', encoding='utf-8') as mf:
            json.dump(manifest, mf, indent=2, ensure_ascii=False)

        print(f"✅ 文件分割完成！共生成 {len(manifest['parts'])} 个分片。")
        print(f"📁 输出目录: {output_dir}")
        print(f"📋 清单文件: {manifest_path}")
        return True

    except Exception as e:
        print(f"处理文件时出错: {e}", file=sys.stderr)
        return False

# ---------- 视频分割（FFmpeg） ----------
def get_video_info(input_path):
    cmd = [
        'ffprobe', '-v', 'error', '-show_entries',
        'format=duration,size,bit_rate', '-of', 'json', input_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError("ffprobe 执行失败，请检查 FFmpeg 安装")
    data = json.loads(result.stdout)
    fmt = data['format']
    duration = float(fmt.get('duration', 0))
    size = int(fmt.get('size', 0))
    bit_rate = int(fmt.get('bit_rate', 0))
    return duration, size, bit_rate

def split_video(input_path, chunk_size_mb=20, output_dir=None):
    # 检测 FFmpeg 是否安装，未安装则自动尝试安装
    if not check_and_install_ffmpeg():
        return False

    if not os.path.isfile(input_path):
        print(f"错误：文件不存在 - {input_path}", file=sys.stderr)
        return False

    dir_name = os.path.dirname(input_path)
    base_name = os.path.basename(input_path)
    name_without_ext, ext = os.path.splitext(base_name)

    if output_dir is None:
        # 视频模式使用 _vsplit 后缀
        output_dir = os.path.join(dir_name, f"{name_without_ext}_vsplit")
    os.makedirs(output_dir, exist_ok=True)

    try:
        duration, total_size, bit_rate = get_video_info(input_path)
        print(f"视频时长: {duration:.2f}s, 总大小: {total_size/1024/1024:.2f} MB")
    except Exception as e:
        print(f"获取视频信息失败: {e}", file=sys.stderr)
        return False

    if total_size == 0:
        print("视频大小为0，无法处理。", file=sys.stderr)
        return False

    chunk_size_bytes = chunk_size_mb * 1024 * 1024

    # 使用 HLS 封装器，通过 -hls_segment_size 限制每个分片大小
    segment_filename = os.path.join(output_dir, f"{name_without_ext}_%04d.ts")
    m3u8_path = os.path.join(output_dir, f"{name_without_ext}.m3u8")

    cmd = [
        'ffmpeg', '-i', input_path,
        '-c', 'copy',
        '-map', '0',
        '-f', 'hls',
        '-hls_segment_size', str(chunk_size_bytes),
        '-hls_segment_filename', segment_filename,
        '-hls_list_size', '0',
        '-hls_playlist_type', 'vod',
        m3u8_path
    ]

    print(f"开始视频分割，每个分片最大 {chunk_size_mb} MB...")
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        print(f"FFmpeg 执行失败: {e.stderr}", file=sys.stderr)
        return False

    # 收集生成的 TS 文件
    ts_files = sorted([f for f in os.listdir(output_dir) if f.endswith('.ts')])
    if not ts_files:
        print("未生成任何分片，请检查输入。", file=sys.stderr)
        return False

    # 构建 manifest.json
    manifest = {
        "original_name": base_name,
        "total_size": total_size,
        "chunk_size_mb": chunk_size_mb,
        "parts": []
    }
    for fname in ts_files:
        fpath = os.path.join(output_dir, fname)
        fsize = os.path.getsize(fpath)
        manifest["parts"].append({
            "name": fname,
            "size": fsize
        })

    manifest_path = os.path.join(output_dir, "manifest.json")
    with open(manifest_path, 'w', encoding='utf-8') as mf:
        json.dump(manifest, mf, indent=2, ensure_ascii=False)

    print(f"✅ 视频分割完成！共生成 {len(ts_files)} 个分片。")
    print(f"📁 输出目录: {output_dir}")
    print(f"📄 HLS 索引: {m3u8_path}")
    print(f"📋 清单文件: {manifest_path}")
    return True

# ---------- 主程序 ----------
def main():
    parser = argparse.ArgumentParser(
        description="综合分割器 - 支持视频（-v）和文件（-f）两种模式",
        epilog="示例:\n"
               "  python split_unified.py -v movie.mp4 -s 30\n"
               "  python split_unified.py -f archive.zip -s 15"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('-v', '--video', metavar='INPUT', help='视频文件路径（使用 FFmpeg 分割）')
    group.add_argument('-f', '--file', metavar='INPUT', help='普通文件路径（纯 Python 分割）')
    parser.add_argument('-s', '--size', type=int, default=20,
                        help='每个分片最大大小（MB），默认 20')
    parser.add_argument('-o', '--output-dir', help='输出目录（默认在输入文件同级创建 文件名_vsplit 或 文件名_fsplit）')

    args = parser.parse_args()

    if args.size <= 0:
        print("错误：分片大小必须大于0。", file=sys.stderr)
        sys.exit(1)

    success = False
    if args.video:
        success = split_video(args.video, args.size, args.output_dir)
    elif args.file:
        success = split_file(args.file, args.size, args.output_dir)

    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()