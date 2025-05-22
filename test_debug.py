from translation.term_manager import TermManager
import traceback

def main():
    print("开始测试术语替换...")
    
    term_manager = TermManager()
    
    # 测试用的替换字典
    replacements = {
        "__TERM_0__": "QRZ（谁在呼叫我）",
        "__TERM_1__": "呼叫"
    }
    
    # 测试用例
    test_cases = [
        "__ term_0__？谁是__TERM_1_？",
        "__TERM_0____TERM_1__",
        "请问__term_0__？谁在__term_1__？"
    ]
    
    for i, text in enumerate(test_cases):
        print(f"\n测试 {i+1}:")
        print(f"原文: {text}")
        
        try:
            result = term_manager.restore_ham_radio_terms(text, replacements)
            print(f"结果: {result}")
            
            # 检查是否还有占位符或多余的下划线
            if "__TERM_" in result or "__term_" in result:
                print("警告: 仍有未替换的占位符!")
            
            if "_？" in result or "_?" in result:
                print("警告: 存在多余的下划线!")
        except Exception as e:
            print(f"处理错误: {e}")
            traceback.print_exc()

if __name__ == "__main__":
    main() 