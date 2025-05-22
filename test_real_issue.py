from translation.term_manager import TermManager

def main():
    term_manager = TermManager()
    
    # 模拟问题中的情况
    text = "QRZ? Who is calling?"
    print(f"原文: {text}")
    
    # 模拟术语替换过程
    replacements = {
        "__TERM_0__": "QRZ（谁在呼叫我）",
        "__TERM_1__": "呼叫"
    }
    
    # 模拟翻译后的文本
    translated_text = "__ term_0__？谁是__TERM_1_？"
    print(f"翻译后文本: {translated_text}")
    
    # 应用术语还原
    result = term_manager.restore_ham_radio_terms(translated_text, replacements)
    print(f"术语还原后: {result}")
    
    # 验证是否所有占位符都被替换
    if "__TERM_" in result or "__term_" in result:
        print("警告: 仍有未替换的占位符!")
        # 再次尝试替换
        result = term_manager.restore_ham_radio_terms(result, replacements)
        print(f"再次替换后: {result}")
    else:
        print("所有占位符都已成功替换!")
    
    print("\n测试更复杂的情况:")
    complex_text = "__ term_0__？谁是__TERM_1___？在__TERM_0__等待回复。"
    print(f"复杂文本: {complex_text}")
    
    complex_result = term_manager.restore_ham_radio_terms(complex_text, replacements)
    print(f"替换后: {complex_result}")

if __name__ == "__main__":
    main() 