import os
import sys
import json
from translation.term_manager import TermManager

def main():
    try:
        print("测试开始...")
        
        # 确保资源目录存在
        resource_dir = 'translation/resources'
        term_file = os.path.join(resource_dir, 'ham_radio_terms.json')
        
        print(f"资源目录: {resource_dir}")
        print(f"术语文件: {term_file}")
        
        if os.path.exists(resource_dir):
            print("资源目录已存在")
        else:
            print("创建资源目录")
            os.makedirs(resource_dir, exist_ok=True)
        
        if os.path.exists(term_file):
            print("术语文件已存在")
            with open(term_file, 'r', encoding='utf-8') as f:
                try:
                    terms = json.load(f)
                    print(f"术语文件有效，包含 {len(terms)} 个术语")
                except json.JSONDecodeError as e:
                    print(f"术语文件解析失败: {e}")
        else:
            print("术语文件不存在，将通过类自动创建")
        
        # 创建术语管理器实例
        print("创建术语管理器...")
        tm = TermManager()
        
        # 显示加载的术语数量
        print(f'加载了 {len(tm.terms)} 个术语')
        for term in tm.sorted_terms:
            print(f"- {term}: {tm.terms[term].get('zh-cn', '无中文翻译')}")
        
        # 测试中文翻译
        test_text_cn = "CQ CQ this is a test with QRZ and 73"
        print("\n中文翻译测试:")
        print(f"原文: {test_text_cn}")
        translated_cn = tm.translate_terms(test_text_cn, 'zh-cn')
        print(f"翻译: {translated_cn}")
        
        # 测试英文翻译
        test_text_en = "CQ CQ this is a test with QRZ and 73"
        translated_en = tm.translate_terms(test_text_en, 'en')
        print("\n英文翻译测试:")
        print(f"原文: {test_text_en}")
        print(f"翻译: {translated_en}")
        
        # 测试日文翻译
        test_text_ja = "CQ CQ this is a test with QRZ and 73"
        translated_ja = tm.translate_terms(test_text_ja, 'ja')
        print("\n日文翻译测试:")
        print(f"原文: {test_text_ja}")
        print(f"翻译: {translated_ja}")
        
        # 测试字母解释法呼号翻译
        test_text_phonetic = "Bravo Golf seven yankee yankee kilo calling"
        print("\n字母解释法呼号翻译测试:")
        print(f"原文: {test_text_phonetic}")
        translated_phonetic = tm.translate_terms(test_text_phonetic, 'zh-cn')
        print(f"翻译: {translated_phonetic}")
        
        # 测试字母解释法呼号转换
        converted_callsign = tm.convert_phonetic_callsign(test_text_phonetic)
        print(f"转换后的呼号: {converted_callsign}")
        
        # 测试信号报告自动转换
        print("\n信号报告自动转换测试:")
        signal_tests = [
            "five nine",
            "five nine nine",
            "five four",
            "five nine and good signal",
            "report is five nine nine",
            "CQ CQ five nine QRZ",
            "five nine nine calling",
            "BG2AYK five nine",
            "five nine BG2AYK",
            "five nine nine",
            "59",
            "599",
            "CQ CQ this is BG7YYK calling. Roger, your signal is five by nine",
            "QRZ? This is Victor Echo 5 Alpha Alpha Echo. Signal report five nine nine",
            "say 73 and I just may be listening."

        ]
        for s in signal_tests:
            print(f"原文: {s}")
            print(f"翻译: {tm.translate_terms(s, 'zh-cn')}")
        
        print("\n术语管理器测试完成!")
        
    except Exception as e:
        print(f"测试过程中出错: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main() 