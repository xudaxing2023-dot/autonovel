"""
core package — 共享工具与基础设施
"""

import sys


def _stderr_print(*args, **kwargs):
    """安全输出到 stderr，兼容 Windows 控制台编码限制。"""
    try:
        print(*args, file=sys.stderr, **kwargs)
    except (OSError, UnicodeEncodeError):
        # Windows 控制台编码限制，静默跳过
        pass


def _safe_print(*args, **kwargs):
    """安全输出到 stdout，兼容 Windows 控制台编码限制。
    
    与 _stderr_print 不同，此函数不会静默跳过 —
    遇到编码错误时使用 errors='replace' 降级重新编码，
    确保 LLM 生成的 Unicode 文本在 cp936 控制台下可显示。
    """
    try:
        print(*args, **kwargs)
    except (OSError, UnicodeEncodeError):
        # 降级：逐参数用 errors='replace' 重新编码后输出
        encoding = sys.stdout.encoding or 'utf-8'
        try:
            for arg in args:
                safe_str = str(arg).encode(encoding, errors='replace').decode(encoding, errors='replace')
                print(safe_str, **kwargs)
        except Exception:
            pass
