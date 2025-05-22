import time
import os
import sys
from audio.audio_manager import AudioManager
import keyboard  # 需要pip install keyboard

def main():
    print("=== 音频识别测试程序 ===")
    print("这个程序将测试完整的音频录制和识别流程")
    print("按Enter键继续...")
    input()
    
    # 获取可用设备
    audio_manager = AudioManager()
    input_devices = audio_manager.get_input_devices()
    output_devices = audio_manager.get_output_devices()
    
    # 列出所有设备
    print("\n可用的输入设备:")
    for i, device in enumerate(input_devices):
        print(f"{i}: {device}")
    
    print("\n可用的输出设备:")
    for i, device in enumerate(output_devices):
        print(f"{i}: {device}")
    
    # 用户选择设备
    try:
        input_idx = int(input("\n请选择输入设备编号: "))
        input_device = input_devices[input_idx]
        
        use_output = input("\n是否需要监听声音? (y/n): ").lower() == 'y'
        output_device = None
        if use_output:
            output_idx = int(input("请选择输出设备编号: "))
            output_device = output_devices[output_idx]
    except (ValueError, IndexError) as e:
        print(f"输入错误: {e}")
        return
    
    print(f"\n选择的输入设备: {input_device}")
    print(f"选择的输出设备: {output_device}")
    
    # 开始录音
    print("\n按下Enter键开始录音和识别...")
    input()
    
    print("开始录音和识别. 按ESC键停止...")
    audio_manager.start_recording(input_device, output_device)
    
    # 等待按键退出
    print("录音中... 请说话，按ESC键停止")
    
    # 定期检查识别结果
    try:
        last_check_time = time.time()
        while True:
            if keyboard.is_pressed('esc'):
                print("检测到ESC键，停止录音...")
                break
                
            # 每隔1秒检查一次识别结果
            current_time = time.time()
            if current_time - last_check_time >= 1:
                text = audio_manager.get_latest_text()
                if text:
                    print(f"\n识别到的文本: {text}")
                last_check_time = current_time
                
            time.sleep(0.1)  # 减少CPU使用率
    except KeyboardInterrupt:
        print("\n检测到Ctrl+C，停止录音...")
    finally:
        # 停止录音
        print("停止录音...")
        audio_manager.stop_recording()
        
        # 等待所有线程结束
        time.sleep(1)
        
        # 显示最终结果
        final_text = audio_manager.get_latest_text()
        if final_text:
            print(f"\n最终识别结果: {final_text}")
        else:
            print("\n没有识别到任何文本")
            
        detected_language = audio_manager.get_detected_language()
        print(f"检测到的语言: {detected_language}")
    
    print("\n测试完成")

if __name__ == "__main__":
    main() 