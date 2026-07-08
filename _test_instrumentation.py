"""临时验证脚本 — 测试 debug_log 和 crash_handler 是否正常工作"""
from core.diagnostic import debug_log, crash_handler

# 测试 debug_log
debug_log("TEST_START", "插桩测试开始", {"phase": "test", "version": "1.0"})
debug_log("TEST_EVENT", "这是一个测试事件", {"chapter": 1, "score": 8.5})
debug_log("TEST_END", "插桩测试结束")

# 测试 crash_handler
try:
    raise ValueError("模拟一个致命错误")
except ValueError:
    crash_handler({"phase": "drafting", "chapters_drafted": 5, "iteration": 3})

print("✓ 所有测试完成")
print("  请检查 logs/debug.log 确认输出内容")
