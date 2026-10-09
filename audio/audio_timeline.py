"""音频时间轴的数据结构（逐词字幕用）

单独放一个模块是为了让界面和单元测试能拿到这些结构，而不必把 whisper/torch/
PyAudio 全拖进来。

时间轴约定：**采集块号**。1 块 = chunk_size (1024) 个样本 ≈ 64ms @16kHz。

AudioManager.captured_chunks 是"录音开始以来读到了多少块"，只增不减，相当于这
轮录音的绝对时钟。一段音频（以及里面的每个词）都有自己在时间轴上的起止块号，
播放位置（用户此刻听到的音频）也换算到同一个刻度上——两者一比就知道某个词该不
该出现了，不需要任何手动延迟。
"""
from collections import namedtuple

# 一个词：文本 + 它在采集时间轴上的起止块号
TimedWord = namedtuple('TimedWord', ['text', 'start_chunk', 'end_chunk'])

# 一段音频识别出来的词表。
# utterance_id 把同一句话的预览结果与最终结果归到一组，最终结果替换预览结果；
# is_final 区分"说话过程中的预览识别"与"整句识别结果"。
WordSegment = namedtuple('WordSegment', ['utterance_id', 'words', 'start_chunk',
                                         'end_chunk', 'is_final', 'text'])

# 送进识别队列的一段音频：数据本身 + 它在采集时间轴上的位置
AudioSegmentTask = namedtuple('AudioSegmentTask', ['data', 'submit_time',
                                                   'start_chunk', 'end_chunk',
                                                   'utterance_id'])
