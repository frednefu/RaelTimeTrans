"""播放同一段"嘀"声，但换几种不同的播法，用"响几声"区分是哪一种。

用来定位"程序放音没声音"到底卡在哪一层：
- 如果只有第 4 种（DirectSound）没声、前 3 种都有声，说明是 DirectSound 这条路
  在本机送不出声音——程序已经改用 MME，遇到这种情况请把结论告诉开发者。
- 如果全都没声，说明问题在系统/设备侧（音量、静音、显示器音箱接线、选错了设备）。

本机（Windows 11 + VB-Audio 虚拟声卡回环实测）的已知结论：
    MME 16kHz/44.1kHz 出声、WASAPI 48kHz 出声，而 DirectSound 能打开、能写入，
    但送出去的全是静音（回环峰值只有 1，正常约 8000）。程序因此统一用 MME。

用法（在项目目录下）：
    python check_audio_output.py              # 用 settings.json 里选的输出设备
    python check_audio_output.py 耳机          # 按名字关键词挑设备
    python check_audio_output.py DELL
    python check_audio_output.py --index 13   # 直接指定设备索引（两台同名显示器
                                              # 在 MME 下列表里名字一样，只能这样区分）
"""
import os
import sys
import time

import numpy as np
import pyaudio

REPO = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from audio.audio_manager import clean_device_name  # noqa: E402

# (响几声, 主机接口, 采样率None=用设备原生, 声道数, 说明)
ROUTES = [
    (1, "MME", 16000, 1, "程序现在用的方式：MME + 16kHz 单声道"),
    (2, "MME", None, 1, "MME + 设备原生采样率"),
    (3, "WASAPI", None, 2, "WASAPI + 设备原生采样率（程序不用的备选）"),
    (4, "DirectSound", 16000, 1, "DirectSound（程序以前用的方式，本机实测无声）"),
]

HOST_NAMES = {
    "MME": "MME",
    "DirectSound": "Windows DirectSound",
    "WASAPI": "Windows WASAPI",
    "WDM-KS": "Windows WDM-KS",
}


def norm(text):
    return " ".join((text or "").split()).strip().lower()


def find_device(p, host_index, name_key):
    """在指定主机接口里按名字找输出设备（MME 名字被截断，用前缀兜底）"""
    fuzzy = None
    for i in range(p.get_device_count()):
        d = p.get_device_info_by_index(i)
        if d["hostApi"] != host_index or d["maxOutputChannels"] <= 0:
            continue
        n = norm(clean_device_name(d["name"]))
        if n == name_key:
            return i, d
        if fuzzy is None and name_key and (name_key[:18] in n or n[:18] in name_key):
            fuzzy = (i, d)
    return fuzzy if fuzzy else (None, None)


def make_beeps(rate, channels, count):
    """count 声 880Hz 短音，用声音数量区分是哪一种播法"""
    tone = (0.22 * 32767 * np.sin(2 * np.pi * 880 * np.arange(int(rate * 0.3)) / rate)).astype(np.int16)
    gap = np.zeros(int(rate * 0.18), dtype=np.int16)
    parts = []
    for k in range(count):
        parts.append(tone)
        if k < count - 1:
            parts.append(gap)
    data = np.concatenate(parts)
    if channels == 2:
        data = np.repeat(data[:, None], 2, axis=1).ravel()
    return data.tobytes()


def parse_args(argv):
    """解析 [关键词] 与 --index N（直接指定设备索引）"""
    forced_index = None
    rest = []
    i = 0
    while i < len(argv):
        if argv[i] == "--index":
            if i + 1 >= len(argv):
                print("--index 后面要跟设备索引，例如：--index 13")
                return None, None
            try:
                forced_index = int(argv[i + 1])
            except ValueError:
                print(f"设备索引要是数字，收到的是「{argv[i + 1]}」")
                return None, None
            i += 2
            continue
        rest.append(argv[i])
        i += 1
    return (rest[0] if rest else None), forced_index


def main():
    keyword, forced_index = parse_args(sys.argv[1:])
    if keyword is None and forced_index is None and len(sys.argv) > 1:
        # parse_args 已经报过错（返回 None, None），别再继续播一遍
        return

    p = pyaudio.PyAudio()
    hosts = {}
    for i in range(p.get_host_api_count()):
        hosts[p.get_host_api_info_by_index(i)["name"]] = i

    # 打印当前所有输出设备，方便确认挑到了哪个
    print("=" * 66)
    print("当前系统的输出设备：")
    for i in range(p.get_device_count()):
        d = p.get_device_info_by_index(i)
        if d["maxOutputChannels"] > 0:
            api = p.get_host_api_info_by_index(d["hostApi"])["name"]
            print(f"  [{api:<18}] {i:3d}  {clean_device_name(d['name'])}")
    print("=" * 66)

    # 标准名：优先用 --index 指定的那个设备，其次 DirectSound 列表里的名字
    # （DirectSound 虽不出声，但设备名是完整的，适合当"标准名"去其它接口找同名设备）
    if forced_index is not None:
        try:
            ref_info = p.get_device_info_by_index(forced_index)
        except Exception as e:
            print(f"索引 {forced_index} 不是有效设备：{e}")
            p.terminate()
            return
        if ref_info["maxOutputChannels"] <= 0:
            print(f"索引 {forced_index} 不是输出设备（没有输出声道）。")
            p.terminate()
            return
        forced_host = p.get_host_api_info_by_index(ref_info["hostApi"])["name"]
        std_name = clean_device_name(ref_info["name"])
        std_key = norm(std_name)
        print(f"目标设备（--index 指定）：[{forced_host}] 索引 {forced_index}  {std_name}")
        print(f"  （原生采样率 {int(ref_info['defaultSampleRate'])}，"
              f"只测这个接口下的播法）")
    else:
        # 选定目标设备：优先命令行关键词，其次 settings.json 里的输出设备
        if keyword:
            target_key = norm(keyword)
        else:
            try:
                import json
                saved = json.load(open(os.path.join(REPO, "settings.json"), encoding="utf-8")) \
                    .get("output_device", "")
                target_key = norm(clean_device_name(saved.replace("(Index:", "").rsplit(" ", 1)[0]))
            except Exception:
                target_key = ""
            if not target_key:
                target_key = "dell"

        ds = hosts.get("Windows DirectSound")
        ref_index, ref_info = find_device(p, ds, target_key)
        if ref_info is None:
            print(f"找不到名字含「{target_key}」的输出设备，退出。")
            p.terminate()
            return
        forced_host = None
        std_name = clean_device_name(ref_info["name"])
        std_key = norm(std_name)
        print(f"目标设备：{std_name}（DirectSound 索引 {ref_index}，"
              f"原生采样率 {int(ref_info['defaultSampleRate'])}）")

        # 同名设备（例如两台同型号显示器）：名字一样没法区分，提示用 --index 单独测
        same = [i for i in range(p.get_device_count())
                if p.get_device_info_by_index(i)["maxOutputChannels"] > 0
                and norm(clean_device_name(p.get_device_info_by_index(i)["name"])) == std_key]
        if len(same) > 1:
            print(f"提示：有 {len(same)} 个同名设备（索引 {', '.join(str(x) for x in same)}），"
                  f"名字上分不出是哪一台。")
            print("      要单独测其中某一台，用上面的索引跑：--index <索引>")

    print()
    routes = ROUTES
    if forced_index is not None:
        routes = [r for r in ROUTES if HOST_NAMES[r[1]] == forced_host]
        print(f"[{forced_host}] 接口下要测 {len(routes)} 种播法。")
    print(f"下面会依次播放 {len(routes)} 种方式，用『响几声』区分：")
    for count, host, rate, ch, desc in routes:
        print(f"  {count} 声 = {host} / {rate or '原生'}Hz / {ch} 声道  —— {desc}")
    print()
    print(">>> 请仔细听，记住你能听到『几声』。没听到的不用管。 <<<")
    print()
    time.sleep(1.0)

    results = []
    for count, host, rate, ch, desc in routes:
        host_index = hosts.get(HOST_NAMES[host])
        label = f"{count} 声 = {host} / {rate or '原生'}Hz / {ch}ch"
        if host_index is None:
            print(f"[跳过] {label}（系统没有这个主机接口）")
            results.append({"count": count, "route": label, "result": "主机接口不存在"})
            continue

        if forced_index is not None:
            # 指定索引时必须用这个索引本身：同名设备在列表里分不出来，按名字找会找到第一台
            idx, info = forced_index, p.get_device_info_by_index(forced_index)
        else:
            idx, info = find_device(p, host_index, std_key)
        if info is None:
            print(f"[跳过] {label}（这个接口下没有找到同名设备）")
            results.append({"count": count, "route": label, "result": "找不到设备"})
            continue

        use_rate = rate or int(info["defaultSampleRate"])
        try:
            stream = p.open(format=pyaudio.paInt16, channels=ch, rate=use_rate,
                            output=True, frames_per_buffer=1024, output_device_index=idx)
        except Exception as e:
            print(f"[失败] {label} -> 打不开：{e}")
            results.append({"count": count, "route": label, "result": f"打不开: {e}"})
            time.sleep(0.6)
            continue

        try:
            print(f"[播放] {label}  (索引 {idx}, {use_rate}Hz)")
            stream.write(make_beeps(use_rate, ch, count))
            time.sleep(0.35)          # 等缓冲区放完再关
            results.append({"count": count, "route": label, "result": "已播放"})
        except Exception as e:
            print(f"[失败] {label} -> 写入出错：{e}")
            results.append({"count": count, "route": label, "result": f"写入出错: {e}"})
        finally:
            try:
                stream.stop_stream()
                stream.close()
            except Exception:
                pass
        time.sleep(1.2)               # 留出间隔，方便分辨是哪一组

    p.terminate()
    print()
    print("=" * 66)
    print("播放完毕。请把你能听到的『声音数量』告诉我，例如：只听到 2 声。")
    print("如果一声都没听到，那问题就不在程序这条路上，而在系统/设备侧。")
    print("=" * 66)
    for r in results:
        print(f"  {r['count']} 声  {r['route']}  -> {r['result']}")


if __name__ == "__main__":
    main()
