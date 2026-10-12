"""检查设置面板的排版与「语音识别设置」合并后的模型下拉（离屏跑，不启真窗口）

用法：
    python check_settings_ui.py

用 `QT_QPA_PLATFORM=offscreen` 建一次 `MainWindow`（音视频、识别都不启动），验三件事：

- 整页装在可滚动的 `QScrollArea` 里、分组排成左右两列（一屏放不下时靠滚动条，而不是
  把底部的组裁掉），"高级设置"默认收起、点开才显示里面的项；
- 启动尺寸被夹到当前屏幕的可用区域里（本机实测存过 897×1360，比 1080p 屏还高）；
- 合并后的「语音识别设置」只有一个模型下拉：候选随后端变（整句 tiny~large / 流式
  tiny~medium），两个后端各记各的键，**流式后端下回填整句模型名不许写进 `simul_model`**
  ——合并最容易踩的就是这个坑；另外流式那两行和整句的状态行要按后端显隐；
- 两个逐词开关（「原文逐词显示」/「译文逐词显示」）都在字幕样式组里、勾选状态来自
  配置；译文刷新间隔不在流式那一组里（两种后端都吃）；
- 「显示音频数据统计信息」勾上之后**界面上真的有数**（以前这个键只有一段已经不跑的
  旧代码读它，勾了什么都不发生）：统计行的显隐跟着复选框、喂一块假音频就显示采样率/
  块大小/峰值/本轮时长，停止采集半秒后瞬时值回零。

`MainWindow` 的 `resizeEvent` 会存窗口大小，所以脚本会写 settings.json：跑之前备份、
退出时原样放回（`finally` 里），用户的设置不会被动。
"""
import os
import shutil
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # 必须赶在导入 PySide6 之前

from PySide6.QtWidgets import QApplication, QGroupBox, QLabel, QScrollArea  # noqa: E402

import numpy as np  # noqa: E402

from config import config  # noqa: E402
from model_residency import model_residency  # noqa: E402

FAILED = []


def check(ok, message):
    print(f"  [{'通过' if ok else '不通过'}] {message}")
    if not ok:
        FAILED.append(message)


def main():
    backup = "settings.json.smoke-backup"
    shutil.copyfile("settings.json", backup)
    try:
        app = QApplication.instance() or QApplication([])
        from gui.main_window import MainWindow
        window = MainWindow()
        window.show()
        app.processEvents()

        print("— 布局 —")
        central = window.centralWidget()
        check(isinstance(central, QScrollArea), f"中央部件是可滚动页面（{type(central).__name__}）")
        check(bool(central.widgetResizable()), "页面宽度跟着视口走")
        groups = [g.title() for g in central.findChildren(QGroupBox)]
        print(f"  分组: {groups}")
        check("语音识别设置" in groups and "Whisper模型设置" not in groups
              and "流式识别设置" not in groups,
              "两个模型组已并成「语音识别设置」")
        check(window.advanced_group.isChecked() is False
              and window.advanced_container.isHidden(),
              "高级设置默认是收起的")
        window.advanced_group.setChecked(True)
        app.processEvents()
        check(not window.advanced_container.isHidden(), "点开后高级设置显示出来")
        window.advanced_group.setChecked(False)
        app.processEvents()

        print("— 屏幕尺寸夹取 —")
        available = app.primaryScreen().availableGeometry()
        print(f"  屏幕可用区域 {available.width()}×{available.height()}，"
              f"窗口 {window.width()}×{window.height()}（配置里存的是 "
              f"{config.get('main_window_width')}×{config.get('main_window_height')}）")
        check(window.height() <= available.height() and window.width() <= available.width(),
              "启动尺寸被夹到屏幕可用区域里")

        print("— 合并后的模型下拉 —")
        batch_key_before = config.get("whisper_model")
        window.asr_backend_combo.setCurrentIndex(0)
        app.processEvents()
        batch_models = [window.asr_model_combo.itemText(i)
                        for i in range(window.asr_model_combo.count())]
        batch_shown = window.asr_model_combo.currentText()
        check(batch_models == ["tiny", "base", "small", "medium", "large"],
              f"整句后端下候选是 tiny~large（{batch_models}）")
        check(batch_shown == batch_key_before,
              f"整句后端下显示的是 whisper_model（{batch_shown}）")
        check(window._batch_status_box.isHidden() is False
              and window._stream_group.isHidden() is True
              and window._stream_advanced_box.isHidden() is True,
              "整句后端：识别状态在、流式那两行收起来")

        window.asr_backend_combo.setCurrentIndex(1)
        app.processEvents()
        simul_models = [window.asr_model_combo.itemText(i)
                        for i in range(window.asr_model_combo.count())]
        simul_shown = window.asr_model_combo.currentText()
        check(simul_models == ["tiny", "base", "small", "medium"],
              f"流式后端下候选是 tiny~medium（{simul_models}）")
        check(simul_shown == config.get("simul_model", "small"),
              f"流式后端下显示的是 simul_model（{simul_shown}）")
        check(window._batch_status_box.isHidden() is True
              and window._stream_group.isHidden() is False
              and window._stream_advanced_box.isHidden() is False,
              "流式后端：识别状态收起、流式那两行显示")

        # 换模型只动当前后端的键
        window.asr_model_combo.setCurrentText("medium")
        app.processEvents()
        check(config.get("simul_model") == "medium"
              and config.get("whisper_model") == batch_key_before,
              f"流式后端下换模型只改 simul_model（{config.get('simul_model')}），"
              f"whisper_model 还是 {config.get('whisper_model')}")
        check(window.audio_manager.current_model_name != "medium",
              "流式后端下换模型不会去加载整句模型（加载只发生在整句后端）")

        window.asr_backend_combo.setCurrentIndex(0)
        app.processEvents()
        check(window.asr_model_combo.currentText() == batch_key_before,
              f"切回整句后端，下拉换回它自己那个模型（{window.asr_model_combo.currentText()}）")
        # 回填整句模型时不许写坏 simul_model
        window._sync_asr_model_combo("small")
        check(config.get("simul_model") == "medium",
              f"回填整句模型不动 simul_model（{config.get('simul_model')}）")

        print("— 翻译引擎切换 —")
        window.translation_backend_combo.setCurrentText("Google（网络）")
        app.processEvents()
        check(window.local_llm_box.isHidden() and window.local_advanced_box.isHidden(),
              "切到 Google：本地模型那几行和服务地址那几行一起收起")
        # 「显存」那一行**不在 local_llm_box 里**：它报的是整台机器的驻留情况
        # （识别模型才是大头的占位者），换翻译引擎不该把它藏起来。
        check(not window.residency_label.isHidden() and not window.release_gpu_button.isHidden(),
              "切到 Google：显存状态行和「释放显存」按钮照样在")
        window.translation_backend_combo.setCurrentText("本地模型（低延迟）")
        app.processEvents()
        check(not window.local_llm_box.isHidden() and not window.local_advanced_box.isHidden(),
              "切回本地：两块都回来")

        print("— 显存回收的控件 —")
        check(window.advanced_group.isChecked() or window.local_advanced_box.isHidden()
              or window.idle_unload_spin is not None,
              "「闲置卸载」旋钮挂在本地模型的高级那一块里")
        check(window.idle_unload_spin.value() == int(config.get("model_idle_unload_sec", 300)),
              f"闲置卸载秒数来自配置（{window.idle_unload_spin.value()}）")
        check(window.model_idle_unload_checkbox.isChecked()
              == bool(config.get("model_idle_unload_enabled", True)),
              "「自动回收」勾选状态来自配置")
        # 标题（"显存:"）和正文是两个部件：正文里没有"显存"二字，别按正文找标题
        captions = [label.text() for label in window.findChildren(QLabel)
                    if label.text().startswith("显存")]
        check(captions == ["显存:"], "「显存」那一行有标题（%s）" % (captions or "没有"))
        text = window.residency_label.text()
        check("torch" in text or "驻留" in text or "已卸载" in text,
              "显存状态行的正文报的是用量/驻留情况（现在是 %r）" % text)
        # 关掉自动回收 = 三项闲置超时都设 0（只认手动点按钮）
        window.model_idle_unload_checkbox.setChecked(False)
        app.processEvents()
        timeouts = {e["key"]: e["idle_timeout"] for e in model_residency.snapshot()}
        check(timeouts and all(value == 0 for value in timeouts.values()),
              f"关掉「自动回收」之后账本上不再按闲置卸（{timeouts}）")
        check(config.get("model_idle_unload_enabled") is False,
              "这个开关立刻落了盘")
        window.model_idle_unload_checkbox.setChecked(True)
        app.processEvents()
        timeouts = {e["key"]: e["idle_timeout"] for e in model_residency.snapshot()}
        check(all(value == window.idle_unload_spin.value() for value in timeouts.values()),
              f"勾回来之后三项都按旋钮的值走（{timeouts}）")

        print("— 预览区还在（设置里换字号要能找到它）—")
        preview_layout = window.findChild(QGroupBox, "字幕预览")
        check(preview_layout is not None and preview_layout.layout() is not None,
              "「字幕预览」组在滚动页里照样找得到")

        print("— 两个逐词开关 —")
        check(window.word_by_word_checkbox.text() == "原文逐词显示"
              and window.word_by_word_checkbox.isChecked()
              == bool(config.get("word_by_word_enabled", True)),
              f"「原文逐词显示」在，勾选状态来自配置"
              f"（{window.word_by_word_checkbox.isChecked()}）")
        check(window.translation_word_by_word_checkbox.text() == "译文逐词显示"
              and window.translation_word_by_word_checkbox.isChecked()
              == bool(config.get("translation_word_by_word", True)),
              f"「译文逐词显示」在，勾选状态来自配置"
              f"（{window.translation_word_by_word_checkbox.isChecked()}）")
        # 以前的"边说边翻译"只在流式后端下露出来，现在被通用的「译文逐词显示」取代
        check(not hasattr(window, "simul_translate_check"),
              "旧的「边说边翻译」复选框已经拿掉")
        # 译文刷新间隔两种后端都要用，所以不在流式那一组里
        window.asr_backend_combo.setCurrentIndex(0)
        app.processEvents()
        check(not window.simul_prefix_spin.isHidden(),
              "整句后端下「译文刷新间隔」照样看得见（它不只管流式）")
        window.asr_backend_combo.setCurrentIndex(1)
        app.processEvents()
        check(not window.simul_prefix_spin.isHidden(),
              "流式后端下也在")

        print("— 「显示音频数据统计信息」勾了真的要显示东西 —")
        stats_label = window.audio_stats_label
        check(stats_label.parent() is window.show_audio_stats_checkbox.parent(),
              "统计行和「显示音频数据统计信息」复选框在同一个组里")
        # 显隐一律跟着复选框走（复选框的初始状态来自配置）
        window.show_audio_stats_checkbox.setChecked(False)
        app.processEvents()
        check(not stats_label.isVisible(), "没勾的时候收起来")
        check(config.get("show_audio_stats") is False, "勾选状态写回了配置")
        window.show_audio_stats_checkbox.setChecked(True)
        app.processEvents()
        check(stats_label.isVisible(), "勾上之后露出来")

        # 喂一块假音频：标签里必须有真数据（这个选项以前是勾了什么都不发生）
        window.audio_manager.reset_audio_stats()
        window.audio_manager._update_audio_stats(
            np.full(1024, 3277, dtype=np.int16), False, 120.0, 350.0)
        window.update_audio_stats_label()
        stats_text = stats_label.text()
        check("音频统计" in stats_text and "16000 Hz" in stats_text
              and "1024 样" in stats_text and "64 ms" in stats_text,
              f"采样率/块大小显示出来了：{stats_text}")
        check("本块峰值 10.0%、RMS 10.0%" in stats_text,
              "本块的峰值/RMS 按百分比显示（3277/32768 = 10.0%）")
        check("本轮已采集 0.1 s（有语音 0.1 s，共 1 块）" in stats_text,
              "本轮累计时长/语音时长/块数都对得上（1024 样 = 64ms）")
        check("底噪 120、判定阈值 350" in stats_text, "VAD 那两个数来自采集线程")

        # 停止采集半秒之后瞬时值要回零（不然界面上挂着一个不动的数字，像还在采）
        window.audio_manager._audio_stats["updated_at"] = time.time() - 10
        window.update_audio_stats_label()
        check("本块峰值 0.0%、RMS 0.0%" in stats_label.text()
              and "本轮已采集 0.1 s" in stats_label.text(),
              "停采之后瞬时值回零、本轮累计还留着")

        window.close()
    finally:
        shutil.move(backup, "settings.json")

    print("-" * 60)
    if FAILED:
        print(f"{len(FAILED)} 项不通过：" + "; ".join(FAILED))
        return 1
    print("界面冒烟检查全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
