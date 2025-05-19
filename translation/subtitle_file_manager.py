import os
import datetime
import re

class SubtitleFileManager:
    def __init__(self):
        # 创建一个英文名的字幕目录
        self.subtitle_dir = "Subtitles"
        self.current_file = None
        self.create_subtitle_directory()
        self.recording = False
        self.original_texts = []
        self.translated_texts = []
        self.start_time = None
        self.time_offset = 0  # 时间偏移，单位为毫秒
        
        # 用于防止重复添加相同内容的字幕
        self.last_original_text = None
        self.last_translated_text = None
    
    def create_subtitle_directory(self):
        """创建字幕保存目录"""
        if not os.path.exists(self.subtitle_dir):
            os.makedirs(self.subtitle_dir)
            print(f"Created subtitle directory: {self.subtitle_dir}")
    
    def start_recording(self):
        """开始记录字幕"""
        if self.recording:
            return
        
        self.recording = True
        self.original_texts = []
        self.translated_texts = []
        self.start_time = datetime.datetime.now()
        self.time_offset = 0
        
        # 重置上次记录的文本
        self.last_original_text = None
        self.last_translated_text = None
        
        # 创建一个新的字幕文件
        timestamp = self.start_time.strftime("%Y%m%d_%H%M%S")
        self.current_file = os.path.join(self.subtitle_dir, f"subtitle_{timestamp}.srt")
        print(f"Started recording subtitles to {self.current_file}")
    
    def stop_recording(self):
        """停止记录字幕并保存文件"""
        if not self.recording:
            return
        
        # 保存字幕文件
        if self.original_texts or self.translated_texts:
            self.save_subtitle_file()
        
        self.recording = False
        self.current_file = None
        self.last_original_text = None
        self.last_translated_text = None
        print("Stopped recording subtitles")
    
    def add_subtitle(self, original_text, translated_text=None):
        """添加字幕条目，仅当文本内容变化时才添加新记录"""
        if not self.recording:
            return
            
        # 检查原文是否与上次相同
        if original_text == self.last_original_text:
            # 如果原文相同，但有译文且与上次不同，则更新上次记录的译文
            if translated_text and translated_text != self.last_translated_text and self.translated_texts:
                self.last_translated_text = translated_text
                self.translated_texts[-1] = (translated_text, self.translated_texts[-1][1])
            return
        
        # 记录字幕文本
        timestamp = datetime.datetime.now()
        
        # 添加到列表
        self.original_texts.append((original_text, timestamp))
        # 确保译文列表长度与原文列表相同，未翻译时保存空值
        if translated_text:
            self.translated_texts.append((translated_text, timestamp))
        else:
            # 添加空值占位，确保两个列表长度一致
            self.translated_texts.append(("", timestamp))
        
        # 更新上次记录的文本
        self.last_original_text = original_text
        self.last_translated_text = translated_text
    
    def save_subtitle_file(self):
        """保存字幕文件为SRT格式"""
        if not self.current_file:
            return
        
        with open(self.current_file, 'w', encoding='utf-8') as f:
            # 合并原文和译文
            entries = []
            
            # 处理所有文本记录
            for i, (text, timestamp) in enumerate(self.original_texts):
                if text and text.strip():  # 确保文本不为空
                    time_diff = (timestamp - self.start_time).total_seconds() * 1000
                    start_time_ms = self.time_offset + time_diff
                    end_time_ms = start_time_ms + 3000  # 每个字幕显示3秒
                    
                    # 查找对应的译文
                    trans_text = ""
                    if i < len(self.translated_texts):
                        trans_text = self.translated_texts[i][0]
                    
                    entries.append({
                        'index': len(entries) + 1,
                        'start_time': start_time_ms,
                        'end_time': end_time_ms,
                        'original': text,
                        'translation': trans_text
                    })
            
            # 按时间排序
            entries.sort(key=lambda x: x['start_time'])
            
            # 写入SRT格式
            for i, entry in enumerate(entries):
                # 索引
                f.write(f"{i+1}\n")
                
                # 时间码
                start = self.format_time(entry['start_time'])
                end = self.format_time(entry['end_time'])
                f.write(f"{start} --> {end}\n")
                
                # 字幕文本
                f.write(f"{entry['original']}\n")
                if entry['translation'] and entry['translation'].strip():
                    f.write(f"{entry['translation']}\n")
                
                # 空行分隔
                f.write("\n")
        
        print(f"Saved subtitle file: {self.current_file}")
        
        # 生成一个新的文件，以防止覆盖
        if self.recording:
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            self.current_file = os.path.join(self.subtitle_dir, f"subtitle_{timestamp}.srt")
    
    def format_time(self, milliseconds):
        """将毫秒转换为SRT时间格式 HH:MM:SS,mmm"""
        total_seconds = int(milliseconds / 1000)
        ms = int(milliseconds % 1000)
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        
        return f"{hours:02d}:{minutes:02d}:{seconds:02d},{ms:03d}"
    
    def is_recording(self):
        """检查是否正在记录字幕"""
        return self.recording 