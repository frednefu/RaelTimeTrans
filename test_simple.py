from translation.term_manager import TermManager

term_manager = TermManager()
print("TermManager 初始化成功")

replacements = {
    "__TERM_0__": "QRZ（谁在呼叫我）",
    "__TERM_1__": "呼叫"
}
print("测试替换字典:", replacements)

text = "__ term_0__？谁是__TERM_1_？"
print("原文:", text)

result = term_manager.restore_ham_radio_terms(text, replacements)
print("结果:", result) 