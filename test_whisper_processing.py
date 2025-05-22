import numpy as np
import time
import os
from audio.audio_processor import AudioProcessor, WhisperThreadPool

# 创建测试音频数据
def create_test_audio():
    # 创建一个简单的正弦波作为测试音频
    sample_rate = 16000
    duration = 3  # 秒
    frequency = 440  # Hz
    t = np.linspace(0, duration, int(sample_rate * duration), False)
    audio = 0.5 * np.sin(2 * np.pi * frequency * t)
    return audio.astype(np.float32)

# 回调函数，用于处理结果
def process_result(result):
    print("\n回调函数被调用，处理结果...")
    if "error" in result:
        print(f"处理错误: {result['error']}")
        return
    
    text = result.get("text", "")
    language = result.get("language", "unknown")
    delay_ms = result.get("delay_ms", 0)
    
    print(f"识别结果: '{text}'")
    print(f"识别语言: {language}")
    print(f"处理延迟: {delay_ms}ms")
    
    # 将结果写入文件以便检查
    with open("whisper_test_result.txt", "w", encoding="utf-8") as f:
        f.write(f"识别结果: {text}\n")
        f.write(f"识别语言: {language}\n")
        f.write(f"处理延迟: {delay_ms}ms\n")
    
    print(f"结果已保存到 whisper_test_result.txt")

def main():
    print("开始Whisper处理测试...")
    
    # 创建处理器
    processor = AudioProcessor()
    print(f"已创建AudioProcessor实例，当前设备: {processor.device}")
    
    # 尝试加载模型
    try:
        model = processor.get_model()
        print(f"成功加载模型: {processor.current_model_name}")
    except Exception as e:
        print(f"加载模型失败: {e}")
        return
    
    # 创建测试音频
    audio_data = create_test_audio()
    print(f"已创建测试音频: 形状={audio_data.shape}, 类型={audio_data.dtype}")
    
    # 测试同步处理
    print("\n测试同步处理...")
    try:
        result = processor.process_audio(audio_data)
        print(f"同步处理结果: {result}")
    except Exception as e:
        print(f"同步处理出错: {e}")
    
    # 测试异步处理
    print("\n测试异步处理...")
    try:
        # 确保线程池已启动
        if not processor.thread_pool.is_running:
            processor.thread_pool.start()
            print("已启动线程池")
        
        # 不再设置全局回调，而是直接传递给异步方法
        # processor.thread_pool.set_result_callback(process_result)
        # print("已设置结果回调函数")
        
        # 提交任务 - 直接传递回调函数
        task_id = processor.process_audio_async(audio_data, process_result)
        print(f"已提交异步处理任务，ID: {task_id}")
        
        # 等待处理完成
        print("等待任务完成...")
        max_wait = 30  # 最多等待30秒
        for _ in range(max_wait * 10):
            if not processor.thread_pool.is_busy():
                print("任务已完成")
                break
            time.sleep(0.1)
        else:
            print(f"等待超时({max_wait}秒)，任务可能仍在进行中")
        
    except Exception as e:
        print(f"异步处理出错: {e}")
    finally:
        # 等待一段时间确保回调被执行
        print("等待回调执行...")
        time.sleep(3)
        
        # 清理资源
        print("清理资源...")
        processor.cleanup()
    
    print("\n测试完成")

if __name__ == "__main__":
    main() 