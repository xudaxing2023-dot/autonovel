"""
Pattern Registry — 所有解析 LLM 输出的正则集中管理（双重防线·第一道防线）。

设计原则:
  1. 多格式变体优先——每个 Pattern 至少支持多种 LLM 可能输出的格式变体
  2. 兜底行为显式声明——fallback 必须是明确可预期的行为
  3. 日志自动记录——未命中时自动记录 WARNING
  4. 永不抛异常——所有公开方法都有兜底保护

使用方式:
    from core.pattern_registry import registry
    result = registry.match("canon.no_new_facts", llm_text)
    if result.value:  # bool: True = 无新增事实
        return 0

参考:
    ARCH_PLAN.md §3 — 第一道防线：Pattern Registry 设计
    REGEX_AUDIT.md — 全项目正则表达式审计报告
"""

from dataclasses import dataclass
from typing import Callable, Any
import re
import logging

logger = logging.getLogger(__name__)

# 尝试导入项目级 debug_log，用于统一日志格式到 logs/debug.log
try:
    from core.diagnostic import debug_log as _debug_log
except ImportError:
    _debug_log = None


# ============================================================================
# 核心数据结构
# ============================================================================

@dataclass
class ParsedResult:
    """统一的解析返回类型。永远不会在构造时抛异常。

    Attributes:
        value: 解析出的值，类型取决于具体 Pattern。
               - canon.entry_count → int (条目数)
               - canon.no_new_facts → bool (是否无新增)
               - voice.vocabulary_section → re.Match | None
               - score.markdown_fallback → re.Match | None
        matched_by: 命中的变体名称
        confidence: 匹配置信度 0.0~1.0（1.0 = 确定性匹配，0.0 = 兜底）
    """
    value: Any
    matched_by: str = ""
    confidence: float = 1.0


@dataclass
class RegisteredPattern:
    """一个注册到 Registry 的解析模式。

    Attributes:
        name: 唯一标识符，如 "canon.no_new_facts"
        description: 人类可读描述
        variants: 变体列表 [(variant_name, re.Pattern | Callable[[str], Any]), ...]
                  按优先级排列。Callable 返回非 None 表示命中。
        fallback: 所有变体未命中时调用，签名为 (str) -> ParsedResult
        source: 原始正则所在文件名:行号
        known_risks: 已知风险说明
    """
    name: str
    description: str
    variants: list  # list of (str, re.Pattern | Callable[[str], Any])
    fallback: Callable[[str], ParsedResult]
    source: str = ""
    known_risks: str = ""


# ============================================================================
# Pattern Registry — 单一事实来源
# ============================================================================

class PatternRegistry:
    """Pattern Registry — 所有 LLM 输出解析正则的单一注册中心。

    使用方式：
        from core.pattern_registry import registry
        result = registry.match("score.markdown_fallback", stdout)
        if result.value is not None:
            score = round(float(result.value.group(1)), 1)
    """

    def __init__(self):
        self._patterns: dict[str, RegisteredPattern] = {}

    def register(self, pattern: RegisteredPattern) -> None:
        """注册一个 Pattern。同名 Pattern 会覆盖旧注册。"""
        self._patterns[pattern.name] = pattern
        logger.info(
            "PatternRegistry: 已注册 '%s'（%d 变体）— %s",
            pattern.name, len(pattern.variants), pattern.description
        )

    def match(self, name: str, text: str) -> ParsedResult:
        """按优先级尝试所有变体，命中则返回；全部未命中则触发兜底。

        Args:
            name: Pattern 名称（如 "canon.no_new_facts"）
            text: 待解析的 LLM 输出文本

        Returns:
            ParsedResult — 永远不会为 None，永远不会抛异常。
            调用方检查 result.value 是否为 None/0/False 来判断是否命中。

        Raises:
            永不抛出异常——所有错误都在内部捕获并触发兜底。
        """
        if text is None:
            text = ""

        pattern = self._patterns.get(name)
        if pattern is None:
            msg = f"PatternRegistry: 未注册的 Pattern '{name}'"
            logger.warning(msg)
            self._log_fallback(name, ["<unregistered>"], "return_none", text)
            return ParsedResult(value=None, matched_by="unregistered", confidence=0.0)

        variant_names: list[str] = []
        for variant_name, variant in pattern.variants:
            variant_names.append(variant_name)
            try:
                # 分支 1: Callable 变体 — 直接调用，非 None 返回值 = 命中
                if callable(variant):
                    result = variant(text)
                    if result is not None:
                        if isinstance(result, ParsedResult):
                            result.matched_by = variant_name
                            return result
                        return ParsedResult(value=result, matched_by=variant_name)

                # 分支 2: 编译后的 re.Pattern — 调用 .search()
                elif isinstance(variant, re.Pattern):
                    m = variant.search(text)
                    if m:
                        return ParsedResult(value=m, matched_by=variant_name)

                # 分支 3: 原始字符串 — 编译后调用 .search()
                elif isinstance(variant, str):
                    m = re.search(variant, text)
                    if m:
                        return ParsedResult(value=m, matched_by=variant_name)

            except Exception as e:
                logger.debug(
                    "PatternRegistry: Pattern '%s' 变体 '%s' 执行异常: %s",
                    name, variant_name, e
                )
                continue

        # ── 全部变体未命中 → 记录 WARNING 并触发兜底 ──
        self._log_fallback(name, variant_names, "trigger_fallback", text)
        try:
            return pattern.fallback(text)
        except Exception as e:
            logger.error(
                "PatternRegistry: Pattern '%s' 兜底函数异常: %s", name, e
            )
            return ParsedResult(value=None, matched_by="fallback_error", confidence=0.0)

    def list_all(self) -> list[str]:
        """列出所有已注册的 Pattern 名称。"""
        return list(self._patterns.keys())

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _log_fallback(self, pattern_name: str, variants_attempted: list[str],
                      behavior: str, text: str) -> None:
        """记录兜底触发日志（logging.WARNING + debug_log 双重写入）。"""
        msg = (
            f"Pattern '{pattern_name}' 全部 {len(variants_attempted)} 个变体 "
            f"未命中，触发兜底: {behavior}。"
            f"文本前 200 字符: {text[:200]}"
        )
        logger.warning(msg)

        if _debug_log is not None:
            try:
                _debug_log("PATTERN_FALLBACK", msg, data={
                    "pattern": pattern_name,
                    "variants_attempted": variants_attempted,
                    "fallback_behavior": behavior,
                    "text_preview": text[:200],
                    "text_length": len(text),
                })
            except Exception:
                pass


# ============================================================================
# 全局单例
# ============================================================================

registry = PatternRegistry()


# ============================================================================
# Phase 1：注册 4 个高风险 Pattern
# ============================================================================

def _register_phase1_patterns() -> None:
    """在模块加载时注册所有 Phase 1 Pattern。

    每个 Pattern 的注册参数严格按照 ARCH_PLAN.md §4.1 Phase 1 定义。
    正则表达式与当前已修复版本的源码保持一致（参见各 source 字段）。
    """

    # ────────────────────────────────────────────────────────────────
    # Pattern 1: canon.entry_count
    # 用途：统计 LLM 返回的正典新增条目数
    # 原始位置：foundation/update_canon.py:77
    # 当前正则：r"^(?:—|-|\*) "（已兼容 EM DASH / hyphen / asterisk 三种 bullet）
    # ────────────────────────────────────────────────────────────────
    _ENTRY_COUNT_RE = re.compile(r"^(?:—|-|\*) ", re.MULTILINE)

    registry.register(RegisteredPattern(
        name="canon.entry_count",
        description="统计 LLM 返回的正典新增条目数（按 bullet 符号 ^— / ^- / ^* 计数）",
        variants=[
            ("combined_bullets", lambda text: len(
                _ENTRY_COUNT_RE.findall(text)
            )),
        ],
        fallback=lambda text: ParsedResult(
            value=0, matched_by="fallback_zero", confidence=0.0
        ),
        source="foundation/update_canon.py:77",
        known_risks=(
            "Prompt 要求 EM DASH (—)，LLM 实际可能输出 hyphen (-) 或 asterisk (*)；"
            "已用组合正则兼容三种格式。兜底返回 0（无新条目），偏保守。"
        ),
    ))

    # ────────────────────────────────────────────────────────────────
    # Pattern 2: canon.no_new_facts
    # 用途：检测 LLM 返回「无新增事实」的响应
    # 原始位置：foundation/update_canon.py:67
    # 当前正则：r'无(?:新增|新|可添加)事实|没有新(?:的)?事实|无需?更新'
    # ────────────────────────────────────────────────────────────────
    registry.register(RegisteredPattern(
        name="canon.no_new_facts",
        description="检测 LLM 返回「无新增事实」的响应（匹配多种中文否定表述）",
        variants=[
            ("chinese_no_new", re.compile(
                r'无(?:新增|新|可添加)事实|没有新(?:的)?事实|无需?更新'
            )),
        ],
        fallback=lambda text: ParsedResult(
            value=False, matched_by="fallback_assume_has_new", confidence=0.0
        ),
        source="foundation/update_canon.py:67",
        known_risks=(
            "LLM 可能输出英文 'No new facts' 或其他表述变体；"
            "兜底假定有新增（偏安全——宁可重复录入也不漏掉新事实）。"
        ),
    ))

    # ────────────────────────────────────────────────────────────────
    # Pattern 3: voice.vocabulary_section
    # 用途：从 voice.md 中定位词汇域节（Vocabulary Register）
    # 原始位置：voice_fingerprint.py:206-210
    # 当前正则：兼容中英文多种标题变体
    # ────────────────────────────────────────────────────────────────
    registry.register(RegisteredPattern(
        name="voice.vocabulary_section",
        description="从 voice.md 中定位词汇域节（Vocabulary Register / 词汇域 / 词汇注册表 / Word Register）",
        variants=[
            ("combined_titles", re.compile(
                r'###\s*(?:Vocabulary\s*Register|词汇域|词汇注册表|Word\s*Register)'
                r'.*?\n(.*?)(?=\n###|\n##|\Z)',
                re.DOTALL | re.IGNORECASE
            )),
        ],
        fallback=lambda text: ParsedResult(
            value=None, matched_by="fallback_empty", confidence=0.0
        ),
        source="voice_fingerprint.py:206",
        known_risks=(
            "LLM 输出的 voice.md 中可能不存在 Vocabulary Register 节；"
            "此时上层返回空列表，不影响文风指纹主流程。"
        ),
    ))

    # ────────────────────────────────────────────────────────────────
    # Pattern 4: score.markdown_fallback
    # 用途：Markdown 格式评分解析（JSON 解析失败时的回退安全网）
    # 原始位置：core/state_manager.py:388-400
    # 变体1: **综合评分**: X/10（中英文冒号兼容）
    # 变体2: ###...**评分**: X/10（小节内评分，兼容 Windows \r\n）
    # ────────────────────────────────────────────────────────────────
    registry.register(RegisteredPattern(
        name="score.markdown_fallback",
        description="Markdown 格式评分解析（JSON 解析失败时的回退安全网）",
        variants=[
            ("bold_overall_score", re.compile(
                r'\*\*综合评分\*\*\s*[：:]\s*(\d+(?:\.\d+)?)\s*/\s*10'
            )),
            ("bold_score_in_section", re.compile(
                r'(?:###|##)\s*.*?overall_score.*?[\r\n]+.*?'
                r'\*\*评分\*\*\s*[：:]\s*(\d+(?:\.\d+)?)\s*/\s*10',
                re.DOTALL | re.IGNORECASE
            )),
        ],
        fallback=lambda text: ParsedResult(
            value=None, matched_by="fallback_none", confidence=0.0
        ),
        source="core/state_manager.py:388-400",
        known_risks=(
            "死代码——当前 LLM 始终输出纯 JSON，Markdown 回退路径从未被实际触发；"
            "保留此 Pattern 作为未来格式变更时的安全网。"
        ),
    ))


# ============================================================================
# Phase 2：注册 8 个中等风险 Pattern + 审阅解析 Pattern
# ============================================================================

def _register_phase2_patterns() -> None:
    """在模块加载时注册所有 Phase 2 Pattern。

    每个 Pattern 的注册参数严格按照 ARCH_PLAN.md §4.1 Phase 2 定义。
    正则表达式基于 REGEX_AUDIT.md 的修复建议设计。
    """

    # ────────────────────────────────────────────────────────────────
    # Pattern 5: slop.four_char
    # 用途：检测连续 3+ 四字成语/形容词作为 AI 痕迹
    # 原始位置：evaluation/evaluate.py:216
    # 问题：匹配任意 4 个连续汉字，假阳性极高
    # ────────────────────────────────────────────────────────────────
    _FOUR_CHAR_RE = re.compile(r'[\u4e00-\u9fff]{4}')

    # 常见四字成语/形容词白名单（用于提高精确率）
    _COMMON_FOUR_CHAR_IDIOMS = {
        "不知所措", "小心翼翼", "不可思议", "无论如何", "自然而然",
        "翻天覆地", "惊天动地", "前所未有", "不约而同", "异口同声",
        "千钧一发", "气喘吁吁", "目不转睛", "心旷神怡", "恍然大悟",
        "迫不及待", "筋疲力尽", "欣喜若狂", "垂头丧气", "兴高采烈",
        "犹豫不决", "不假思索", "张牙舞爪", "喃喃自语", "沉默不语",
        "意味深长", "不由自主", "毫不犹豫", "漫不经心", "若有所思",
        "不慌不忙", "一动不动", "不知不觉", "一望无际", "一尘不染",
        "一触即发", "一鸣惊人", "一丝不苟", "一举一动", "一言不发",
    }

    def _four_char_match(text: str):
        """变体1：当前正则（宽松匹配，返回所有 4 字窗口）。"""
        return _FOUR_CHAR_RE.findall(text) if text else []

    def _four_char_idiom_match(text: str):
        """变体2：白名单成语精确匹配（高精确率，可能漏检 AI 自创四字词）。"""
        if not text:
            return []
        found = []
        # 滑动窗口匹配（成语白名单中的词在文本中出现）
        for idiom in _COMMON_FOUR_CHAR_IDIOMS:
            count = text.count(idiom)
            if count > 0:
                found.extend([idiom] * count)
        return found

    registry.register(RegisteredPattern(
        name="slop.four_char",
        description="检测连续四字词/成语密度（AI 痕迹指标）",
        variants=[
            ("all_four_char_windows", _four_char_match),
            ("common_idiom_whitelist", _four_char_idiom_match),
        ],
        fallback=lambda text: ParsedResult(
            value=[], matched_by="fallback_empty", confidence=0.0
        ),
        source="evaluation/evaluate.py:216",
        known_risks=(
            "变体1匹配任意4个连续汉字（非成语），假阳性极高；"
            "变体2用白名单精确匹配但可能漏检AI自创四字组合。"
        ),
    ))

    # ────────────────────────────────────────────────────────────────
    # Pattern 6: slop.dialog_tag
    # 用途：检测对话标签「说」「道」等使用频率
    # 原始位置：evaluation/evaluate.py:220
    # 问题：仅匹配说|道，遗漏大量对话标签
    # ────────────────────────────────────────────────────────────────
    _DIALOG_TAG_EXTENDED_RE = re.compile(
        r'(?:说|道|问|答|喊|叫|嚷|骂|吼|嘀咕|呢喃|嘟囔|低语|'
        r'问道|说道|答道|喊道|笑道|怒道|叹道|冷道|'
        r'开口|出声|回应|回答|反问|追问)'
        r'(?:[：:。，,！？\s]|$|[""」』])'
    )
    _DIALOG_TAG_LEGACY_RE = re.compile(r'(?:说|道)[,，。！？\s]')

    def _dialog_tag_extended(text: str):
        """变体1：扩展标签列表（覆盖说/道/问/答/喊/叫/骂/吼/嘀咕/呢喃 等）。"""
        return _DIALOG_TAG_EXTENDED_RE.findall(text) if text else []

    def _dialog_tag_legacy(text: str):
        """变体2：保留原始正则（向后兼容，仅匹配 说|道）。"""
        return _DIALOG_TAG_LEGACY_RE.findall(text) if text else []

    registry.register(RegisteredPattern(
        name="slop.dialog_tag",
        description="检测中文对话标签使用频率（说/道/问/答/喊/叫 等）",
        variants=[
            ("extended_tags", _dialog_tag_extended),
            ("legacy_tags", _dialog_tag_legacy),
        ],
        fallback=lambda text: ParsedResult(
            value=[], matched_by="fallback_empty", confidence=0.0
        ),
        source="evaluation/evaluate.py:220",
        known_risks=(
            "变体1虽扩展标签列表，但仍有漏检（如角色名+说、复合标签）；"
            "中文对话常见无标签纯对白，此统计天然偏低。"
        ),
    ))

    # ────────────────────────────────────────────────────────────────
    # Pattern 7: slop.em_dash
    # 用途：检测破折号密度（统一 evaluate.py 与 voice_fingerprint.py）
    # 原始位置：evaluation/evaluate.py:218 + voice_fingerprint.py:291
    # 问题：evaluate.py 仅匹配 ——，voice_fingerprint.py 用 count('—')+count('--')
    # ────────────────────────────────────────────────────────────────
    def _count_em_dashes(text: str) -> int:
        """统计所有破折号变体：—— / — / -- / –"""
        if not text:
            return 0
        return (text.count('——') + text.count('—') +
                text.count('--') + text.count('–'))

    def _count_em_dashes_regex(text: str) -> int:
        """正则方式统计（作为 Callable 变体的替代实现）。"""
        if not text:
            return 0
        return len(re.findall(r'——|—|--|–', text))

    registry.register(RegisteredPattern(
        name="slop.em_dash",
        description="统计破折号使用次数（统一 —— / — / -- / – 四种变体）",
        variants=[
            ("count_all_dash_variants", _count_em_dashes),
            ("regex_all_dash_variants", _count_em_dashes_regex),
        ],
        fallback=lambda text: ParsedResult(
            value=0, matched_by="fallback_zero", confidence=0.0
        ),
        source="evaluation/evaluate.py:218 + voice_fingerprint.py:291",
        known_risks=(
            "evaluate.py 原仅匹配 ——（中文EM DASH），与 voice_fingerprint.py 不一致；"
            "现已统一为四种破折号变体计数。"
        ),
    ))

    # ────────────────────────────────────────────────────────────────
    # Pattern 8: voice.vocab_well
    # 用途：从 Vocabulary Register 节解析 "N. **name**: keywords" 格式
    # 原始位置：voice_fingerprint.py:217-219
    # 问题：上游 Vocabulary Register 节可能不存在，此正则为死代码
    # ────────────────────────────────────────────────────────────────
    _VOCAB_WELL_RE = re.compile(
        r'\d+\.\s*\*{0,2}(.+?)\*{0,2}\s*[：:]\s*(.+)',
        re.MULTILINE,
    )

    def _vocab_well_structured(text: str):
        """变体1：解析结构化 'N. **name**: keywords' 格式，返回 [(name, {keywords}), ...]"""
        if not text:
            return []
        wells = []
        for match in _VOCAB_WELL_RE.finditer(text):
            name = match.group(1).strip()
            keywords_str = match.group(2).strip()
            keywords = set()
            for token in re.split(r'[,，、/\s]+', keywords_str):
                token = token.strip().lower()
                if token and len(token) >= 2:
                    keywords.add(token)
            if keywords:
                wells.append((name, keywords))
        return wells[:3] if wells else []

    def _vocab_well_quoted(text: str):
        """变体2：从文本中提取被引号/括号标注的关键词，返回 [("extracted", {keywords})]"""
        if not text:
            return []
        quoted = set(re.findall(r'[「「](.+?)[」」]', text))
        if quoted and len(quoted) >= 5:
            return [("extracted", quoted)]
        return []

    registry.register(RegisteredPattern(
        name="voice.vocab_well",
        description="从 Vocabulary Register 节解析词汇域条目（N. **name**: keywords 格式）",
        variants=[
            ("structured_well_format", _vocab_well_structured),
            ("quoted_keyword_extraction", _vocab_well_quoted),
        ],
        fallback=lambda text: ParsedResult(
            value=[], matched_by="fallback_empty", confidence=0.0
        ),
        source="voice_fingerprint.py:217",
        known_risks=(
            "上游 voice.vocabulary_section 若未命中，此 Pattern 接收空文本，必然返回空列表；"
            "这是正确的级联兜底行为。"
        ),
    ))

    # ────────────────────────────────────────────────────────────────
    # Pattern 9: antipattern.catalog_think
    # 用途：检测「他想到了X。他想到了Y。」目录式思考模式
    # 原始位置：evaluation/antipatterns.py:188-190
    # 问题：只匹配第三人称单数 他|她，遗漏角色名、我、他们
    # ────────────────────────────────────────────────────────────────
    _CATALOG_THINK_EXTENDED_RE = re.compile(
        r'(?:他|她|他们|她们|我|你|它)\s*'
        r'(?:想|思考|思索|琢磨|盘算|回忆|觉得|感觉|意识到|明白)'
        r'.*?(?:了|着|到|过)'
    )
    _CATALOG_THINK_LEGACY_RE = re.compile(
        r'(?:他|她)\s*(?:想|思考|思索|琢磨|盘算|回忆).*?(?:了|着|到)'
    )

    def _catalog_think_extended(text: str):
        """变体1：扩展主语（他/她/他们/她们/我/你/它）+ 扩展动词。"""
        return _CATALOG_THINK_EXTENDED_RE.findall(text) if text else []

    def _catalog_think_legacy(text: str):
        """变体2：保留原始正则（仅 他|她 + 想/思考/思索/琢磨/盘算/回忆）。"""
        return _CATALOG_THINK_LEGACY_RE.findall(text) if text else []

    registry.register(RegisteredPattern(
        name="antipattern.catalog_think",
        description="检测目录式思考模式（「他想到了X。他想到了Y。」）",
        variants=[
            ("extended_subjects_verbs", _catalog_think_extended),
            ("legacy_he_she_only", _catalog_think_legacy),
        ],
        fallback=lambda text: ParsedResult(
            value=[], matched_by="fallback_empty", confidence=0.0
        ),
        source="evaluation/antipatterns.py:188",
        known_risks=(
            "仍可能漏检角色名作为主语的情况（如「林恩想到了…」）；"
            "但扩展后的主语覆盖了绝大多数中文叙事主语。"
        ),
    ))

    # ────────────────────────────────────────────────────────────────
    # Pattern 10: text.sentence_split
    # 用途：按句末标点分割中文句子
    # 原始位置：voice_fingerprint.py:264, evaluation/evaluate.py:285,
    #          evaluation/antipatterns.py:62
    # 问题：不包括省略号……、分号；，引号内句号会导致错误切分
    # ────────────────────────────────────────────────────────────────
    def _sentence_split_expanded(text: str) -> list[str]:
        """变体1：扩展边界标点（含……、…、；），返回句子列表。"""
        if not text:
            return []
        # 使用更完整的句末标点集合
        sentences = re.split(r'[。！？!?…]+|(?<=[；;])\s*', text)
        return [s.strip() for s in sentences if s.strip()]

    def _sentence_split_legacy(text: str) -> list[str]:
        """变体2：保留原始边界（仅 。！？!?）。"""
        if not text:
            return []
        sentences = re.split(r'[。！？!?]+', text)
        return [s.strip() for s in sentences if s.strip()]

    def _sentence_split_newline(text: str) -> list[str]:
        """变体3：按换行分割（极端兜底）。"""
        if not text:
            return []
        return [s.strip() for s in text.split('\n') if s.strip()]

    registry.register(RegisteredPattern(
        name="text.sentence_split",
        description="按句末标点分割中文句子（兼容省略号、分号边界）",
        variants=[
            ("expanded_boundaries", _sentence_split_expanded),
            ("legacy_boundaries", _sentence_split_legacy),
        ],
        fallback=lambda text: ParsedResult(
            value=_sentence_split_newline(text),
            matched_by="fallback_newline", confidence=0.2
        ),
        source="voice_fingerprint.py:264, evaluate.py:285, antipatterns.py:62",
        known_risks=(
            "引号内的句号仍可能导致错误切分（如「你好！她说。」切成3段）；"
            "分号切分对中文小说可能过于激进（分号在叙述中不一定是句边界）。"
        ),
    ))

    # ────────────────────────────────────────────────────────────────
    # Pattern 11: outline.vol_boundary
    # 用途：在卷级大纲中定位「逐卷规划」节的起始位置
    # 原始位置：foundation/gen_outline.py:179-180
    # 问题：中文数字仅列到十，不匹配「卷一：」「第一卷」等表述
    # ────────────────────────────────────────────────────────────────
    _VOL_BOUNDARY_EXTENDED_RE = re.compile(
        r'^#{2,3}\s*(?:逐卷规划|'
        r'[一二三四五六七八九十百]+、\s*卷\s*\d+|'
        r'卷\s*\d+\s*[：:]|'
        r'第[一二三四五六七八九十百\d]+卷[：:]?|'
        r'卷[一二三四五六七八九十百\d]+[：:]?)',
        re.MULTILINE
    )
    _VOL_BOUNDARY_LEGACY_RE = re.compile(
        r'^#{2,3}\s*(?:逐卷规划|[一二三四五六七八九十]、\s*卷\s*\d|卷\s*\d+\s*[：:])',
        re.MULTILINE
    )

    def _vol_boundary_extended(text: str):
        """变体1：扩展中文数字范围（含百位）+ 多种卷表述。"""
        return _VOL_BOUNDARY_EXTENDED_RE.search(text) if text else None

    def _vol_boundary_legacy(text: str):
        """变体2：保留原始正则（中文数字仅列到十）。"""
        return _VOL_BOUNDARY_LEGACY_RE.search(text) if text else None

    registry.register(RegisteredPattern(
        name="outline.vol_boundary",
        description="在卷级大纲中定位「逐卷规划」节起始位置（卷边界检测）",
        variants=[
            ("extended_num_range", _vol_boundary_extended),
            ("legacy_num_range", _vol_boundary_legacy),
        ],
        fallback=lambda text: ParsedResult(
            value=None, matched_by="fallback_no_boundary", confidence=0.0
        ),
        source="foundation/gen_outline.py:179",
        known_risks=(
            "LLM 可能用完全不同的格式组织卷级大纲（如纯数字编号无「卷」字）；"
            "此时回退到全文作为单卷处理。"
        ),
    ))

    # ────────────────────────────────────────────────────────────────
    # Pattern 12-16: review.parse — 审阅报告结构化摘要解析
    # 原始位置：revision/review.py:69-96
    # 当前已验证为安全（🟢），注册以统一管理和监控
    # ────────────────────────────────────────────────────────────────

    registry.register(RegisteredPattern(
        name="review.stars",
        description="从审阅报告解析星级评分（总评: ★★★★☆）",
        variants=[
            ("star_rating", re.compile(r'总评\s*[：:]\s*[★☆]{1,5}')),
            ("inline_star", re.compile(r'★{1,5}')),
        ],
        fallback=lambda text: ParsedResult(
            value=0, matched_by="fallback_zero_stars", confidence=0.0
        ),
        source="revision/review.py:69",
        known_risks="LLM 可能用数字替代 ★ 符号（如「总评: 4/5」），此时会漏检。",
    ))

    registry.register(RegisteredPattern(
        name="review.major_count",
        description="从审阅报告解析严重问题数",
        variants=[
            ("major_count", re.compile(r'严重问题数[：:]\s*(\d+)')),
        ],
        fallback=lambda text: ParsedResult(
            value=0, matched_by="fallback_zero", confidence=0.0
        ),
        source="revision/review.py:80",
        known_risks="已验证与 LLM 输出匹配（review_round1.md）。",
    ))

    registry.register(RegisteredPattern(
        name="review.total_count",
        description="从审阅报告解析总问题数",
        variants=[
            ("total_count", re.compile(r'总问题数[：:]\s*(\d+)')),
        ],
        fallback=lambda text: ParsedResult(
            value=0, matched_by="fallback_zero", confidence=0.0
        ),
        source="revision/review.py:83",
        known_risks="已验证与 LLM 输出匹配（review_round1.md）。",
    ))

    registry.register(RegisteredPattern(
        name="review.qualified_count",
        description="从审阅报告解析合格问题数",
        variants=[
            ("qualified_count", re.compile(r'合格问题数[：:]\s*(\d+)')),
        ],
        fallback=lambda text: ParsedResult(
            value=0, matched_by="fallback_zero", confidence=0.0
        ),
        source="revision/review.py:86",
        known_risks="已验证与 LLM 输出匹配（review_round1.md）。",
    ))

    registry.register(RegisteredPattern(
        name="review.weak_chapters",
        description="从审阅报告解析最弱章节列表",
        variants=[
            ("weak_chapters", re.compile(r'最弱章节[：:]\s*([\d,\s]+)')),
        ],
        fallback=lambda text: ParsedResult(
            value=[], matched_by="fallback_empty", confidence=0.0
        ),
        source="revision/review.py:91",
        known_risks="已验证与 LLM 输出匹配（review_round1.md）。",
    ))

    # ────────────────────────────────────────────────────────────────
    # Pattern 17: codeblock.strip
    # 用途：剥除 LLM 响应中的 ```json ... ``` 代码块标记
    # 原始位置：evaluation/evaluate.py:50-52
    # 问题：\r\n 平台兼容性
    # ────────────────────────────────────────────────────────────────
    def _strip_codeblock(text: str) -> str:
        """剥除 markdown 代码块标记，保留内部内容。"""
        if not text:
            return ""
        t = text.strip()
        if t.startswith("```"):
            t = re.sub(r'^```[\w-]*\s*\r?\n?', '', t)
            t = re.sub(r'\s*```\s*$', '', t)
            t = t.strip()
        return t

    registry.register(RegisteredPattern(
        name="codeblock.strip",
        description="剥除 LLM 响应中的 Markdown 代码块标记（```json ... ```）",
        variants=[
            ("strip_fenced_block", _strip_codeblock),
        ],
        fallback=lambda text: ParsedResult(
            value=text.strip() if text else "",
            matched_by="fallback_passthrough", confidence=0.5
        ),
        source="evaluation/evaluate.py:50",
        known_risks=(
            "当前 LLM 输出纯 JSON（不包裹代码块），此 Pattern 为安全网；"
            "已修复 \r\n 兼容性问题。"
        ),
    ))


# 模块加载时自动注册 Phase 1 + Phase 2 Pattern
_register_phase1_patterns()
_register_phase2_patterns()
