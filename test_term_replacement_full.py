from translation.term_manager import TermManager
import traceback

def main():
    print("开始测试术语替换功能...")
    
    term_manager = TermManager()
    
    # 测试用的替换字典
    replacements = {
        "__TERM_0__": "QRZ（谁在呼叫我）",
        "__TERM_1__": "呼叫",
        "__TERM_2__": "收到"
    }
    
    # 测试用例
    test_cases = [
        # 基本测试
        ("__TERM_0__? 谁在__TERM_1__?", "基本测试 - 标准占位符"),
        ("__ term_0__？谁是__TERM_1_？", "基本测试 - 带空格和下划线的占位符"),
        ("__term_0____term_1__", "基本测试 - 连续占位符"),
        
        # 复杂测试
        ("请问__term_0__？谁在__term_1__？使用__TERM_2__应答", "复杂测试 - 多个术语"),
        ("__ TERM_0__？在__TERM_0__等待回复。", "复杂测试 - 重复术语"),
        ("__TERM_0___test__TERM_1__", "复杂测试 - 带下划线分隔符"),
        
        # 边缘情况
        ("这是一段没有任何占位符的文本", "边缘测试 - 无占位符"),
        ("__TERM_999__", "边缘测试 - 未知占位符ID"),
        ("__TERM_0__？__TERM_1_？__TERM_2__？", "边缘测试 - 多个带下划线的占位符")
    ]
    
    for text, description in test_cases:
        print(f"\n{description}")
        print(f"原文: {text}")
        
        try:
            # 执行术语替换
            result = term_manager.restore_ham_radio_terms(text, replacements)
            print(f"结果: {result}")
            
            # 检查处理结果
            has_unprocessed = "__TERM_" in result or "__term_" in result
            has_extra_underscores = any(marker in result for marker in ["_？", "_?", "_，", "_,", "_。", "_.", "_！", "_!"])
            
            if has_unprocessed:
                print("警告: 存在未处理的占位符!")
            
            if has_extra_underscores:
                print("警告: 存在多余的下划线!")
                
            if not has_unprocessed and not has_extra_underscores:
                print("✓ 测试通过")
        
        except Exception as e:
            print(f"错误: {e}")
            traceback.print_exc()
    
    print("\n测试完成")

if __name__ == "__main__":
    main() 