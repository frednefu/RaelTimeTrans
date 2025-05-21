import os
import sys
import re
from translation.subtitle_manager import SubtitleManager

def is_callsign(text):
    """检查文本是否包含呼号"""
    # 检查标准呼号格式（字母数字组合）
    if re.search(r'\b[A-Z0-9]{3,}[A-Z][0-9][A-Z]{1,3}\b', text):
        return True
    # 检查字母解释法呼号
    if re.search(r'\b(Alpha|Bravo|Charlie|Delta|Echo|Foxtrot|Golf|Hotel|India|Juliet|Kilo|Lima|Mike|November|Oscar|Papa|Quebec|Romeo|Sierra|Tango|Uniform|Victor|Whiskey|X-ray|Yankee|Zulu)\b', text, re.IGNORECASE):
        return True
    return False

def test_translation():
    """测试翻译功能"""
    # 创建字幕管理器实例
    subtitle_manager = SubtitleManager()
    
    # 测试用例分类
    test_cases = {
        "基本术语测试": [
            "CQ CQ this is BG7YYK calling",
            "Roger, copy that",
            "QRZ? Who is calling?",
            "73, best regards",
        ],
        "信号报告测试": [
            "Your signal is five by nine",
            "Signal report five nine nine",
            "five nine and good signal",
            "Signal report five nine nine nine",
            "Your signal is five by nine plus",
        ],
        "呼号测试": [
            "This is Bravo Golf seven yankee yankee kilo",
            "Victor, Echo 5, Alpha, Alpha Echo",
            "This is Alpha Bravo Charlie Delta Echo",
            "This is X-ray Yankee Zulu",
        ],
        "组合测试": [
            "CQ CQ this is BG7YYK calling. Roger, your signal is five by nine",
            "QRZ? This is Victor Echo 5 Alpha Alpha Echo. Signal report five nine nine",
            "say 73 and I just may be listening.",
            "Roger, your signal is five by nine. Over.",
            "CQ CQ this is BG7YYK calling CQ CQ",
        ],
        "错误处理测试": [
            "",  # 空字符串
            "   ",  # 只有空格
            None,  # None值
            "!@#$%^&*()",  # 特殊字符
            "1234567890",  # 纯数字
        ]
    }
    
    # 目标语言
    target_languages = ["中文"]
    
    # 运行测试
    for language in target_languages:
        print(f"\n{language}翻译测试:\n")
        
        for category, cases in test_cases.items():
            print(f"\n{category}:")
            print("-" * 50)
            
            for text in cases:
                print(f"原文: {text}")
                try:
                    # 使用SubtitleManager的translate方法进行翻译
                    translation = subtitle_manager.translate(text, language, debug=True)
                    print(f"译文: {translation}")
                    
                    # 验证翻译结果
                    if text and isinstance(text, str):
                        # 验证呼号是否被正确保留
                        if is_callsign(text):
                            assert is_callsign(translation), "呼号格式未被正确保留"
                        
                        # 验证信号报告是否被正确转换
                        if "five by nine" in text.lower():
                            assert "59" in translation, "信号报告未被正确转换"
                        
                        # 验证特殊术语是否被正确翻译
                        if "CQ" in text:
                            if language == "中文":
                                assert "CQ" in translation, "CQ术语未被正确保留"
                            else:
                                assert "CQ" in translation, "CQ术语未被正确保留"
                        
                        # 验证73是否被正确翻译
                        if "73" in text:
                            if language == "中文":
                                assert "73" in translation, "73术语未被正确保留"
                            else:
                                assert "73" in translation, "73术语未被正确保留"
                        
                        # 验证Roger是否被正确翻译
                        if "Roger" in text:
                            if language == "中文":
                                assert "收到" in translation or "明白" in translation, "Roger术语未被正确翻译"
                            else:
                                assert "Roger" in translation, "Roger术语未被正确保留"
                    
                except Exception as e:
                    print(f"测试失败: {str(e)}")
                    import traceback
                    traceback.print_exc()
                
                print("-" * 50)
    
    print("\n测试完成!")

if __name__ == "__main__":
    test_translation() 