import asyncio
import os
import tempfile

import pytest

from services import file_service
from services.novel_service import (
    parse_with_fixed_size,
    parse_with_rule,
    ParseError,
    _build_summary,
    _safe_filename,
    _read_metadata_from_header,
    _build_chapters_from_matches,
)


SAMPLE_TEXT = """书名: 测试小说
作者: 测试作者

第一章 开始
这是第一段内容。

第二章 旅途
这是第二段内容。
这是第二段的延续。

第三章 结局
大结局内容。
"""


def test_safe_filename_strips_path():
    assert _safe_filename("../../../etc/passwd") == "passwd"
    assert _safe_filename("C:/folder/测试.txt") == "测试.txt"
    assert _safe_filename("a/b\\c|d?.txt") == "c_d_.txt"
    assert _safe_filename("") == "novel.txt"


def test_safe_filename_keeps_extension():
    assert _safe_filename("note.TXT").endswith(".TXT")


def test_read_metadata_chinese():
    data = SAMPLE_TEXT.encode("utf-8")
    title, author = _read_metadata_from_header(data)
    assert title == "测试小说"
    assert author == "测试作者"


def test_read_metadata_english():
    text = b"title: My Novel\nauthor: John Doe\n\nbody..."
    title, author = _read_metadata_from_header(text)
    assert title == "My Novel"
    assert author == "John Doe"


def test_read_metadata_missing():
    title, author = _read_metadata_from_header("无元数据".encode("utf-8"))
    assert title == ""
    assert author == ""


def test_parse_with_rule_chinese():
    chapters = parse_with_rule(SAMPLE_TEXT, r"第.{1,5}章")
    assert len(chapters) == 3
    assert chapters[0].title.startswith("第一章")
    assert chapters[0].start_position > 0
    assert chapters[0].start_position < chapters[1].start_position
    assert chapters[-1].end_position == len(SAMPLE_TEXT)
    assert chapters[0].chapter_number == 1
    assert chapters[2].chapter_number == 3


def test_parse_with_rule_invalid_regex():
    with pytest.raises(ParseError):
        parse_with_rule(SAMPLE_TEXT, r"[invalid(")


def test_parse_with_rule_no_match():
    chapters = parse_with_rule(SAMPLE_TEXT, r"未匹配的规则")
    assert chapters == []


def test_parse_with_rule_positions_continuous():
    chapters = parse_with_rule(SAMPLE_TEXT, r"第.{1,5}章")
    for i in range(1, len(chapters)):
        assert chapters[i].start_position >= chapters[i - 1].end_position
    assert chapters[-1].end_position == len(SAMPLE_TEXT)


def test_parse_with_fixed_size_basic():
    paragraphs = [f"这是段落{i}。内容。" * 10 for i in range(20)]
    content = "\n".join(paragraphs)
    chapters = parse_with_fixed_size(content, chunk_size=200)
    assert len(chapters) >= 5
    for chap in chapters:
        assert chap.content is not None
        assert chap.content.strip() != ""
        assert chap.title


def test_parse_with_fixed_size_invalid_size():
    with pytest.raises(ParseError):
        parse_with_fixed_size("any", 0)
    with pytest.raises(ParseError):
        parse_with_fixed_size("any", -10)


def test_parse_with_fixed_size_short_content():
    chapters = parse_with_fixed_size("只有一行。", 1000)
    assert len(chapters) == 1
    assert "只有一行" in chapters[0].content


def test_build_chapters_from_matches_monotonic():
    import re
    pattern = re.compile(r"第\d+章", re.MULTILINE)
    matches = list(pattern.finditer("第1章\nx\n第2章\ny\n第3章\nz"))
    chapters = _build_chapters_from_matches("第1章\nx\n第2章\ny\n第3章\nz", matches)
    assert [c.chapter_number for c in chapters] == [1, 2, 3]
    for i in range(1, len(chapters)):
        assert chapters[i].start_position > chapters[i - 1].start_position


def test_build_chapters_title_includes_inline_subtitle():
    """标题应延伸到行末，保留"第28章：标题"这类同行副标题。"""
    import re
    text = (
        "楔子 序幕初开\n"
        "旧事已矣，遗音尚存。\n"
        "\n"
        "第二十八章 你们一起上吧\n"
        "唐银与马红俊一击必中。\n"
        "\n"
        "第二十九章 另起波澜\n"
        "下一段内容。\n"
    )
    pattern = re.compile(r"^\s*((?:楔子|序幕|第[一二三四五六七八九十百千零\d]+章))", re.MULTILINE)
    matches = list(pattern.finditer(text))
    chapters = _build_chapters_from_matches(text, matches)
    assert [c.chapter_number for c in chapters] == [1, 2, 3]
    assert chapters[0].title.startswith("楔子")
    assert chapters[1].title == "第二十八章 你们一起上吧"
    assert chapters[2].title == "第二十九章 另起波澜"
    # 起始位置仍然只是匹配位置（不影响切片）
    assert chapters[1].start_position == text.index("第二十八章")
    # 章节之间不重叠
    assert chapters[1].end_position == chapters[2].start_position


def test_read_text_slice_chinese_char_offsets():
    """回归测试：start/end 是字符偏移，UTF-8 多字节字符不能按字节切。

    修复前：f.seek(char_pos) 把字符偏移当字节偏移处理，中文小说章节
    内容会出现 \\ufffd 替换字符。
    """
    async def _run():
        text = (
            "书名: 字符测试\n"
            "作者: Tester\n"
            "\n"
            "第一章 开始\n"
            "这是第一段中文内容。\n"
            "\n"
            "第二章 旅途\n"
            "更多中文内容，讲述旅途见闻。\n"
        )
        char_start = text.index("第二章")
        char_end = len(text)
        with tempfile.NamedTemporaryFile(
            "wb", suffix=".txt", delete=False
        ) as f:
            f.write(text.encode("utf-8"))
            path = f.name
        try:
            content = await file_service.read_text_slice(
                path, char_start, char_end
            )
            assert content.startswith("第二章"), (
                f"期望以'第二章'开头，实际: {content[:30]!r}"
            )
            assert "旅途" in content
            assert "见闻" in content
            assert "\ufffd" not in content, "不应出现 Unicode 替换字符"
        finally:
            os.remove(path)

    asyncio.run(_run())


def test_parse_with_fixed_size_title_has_segment_number():
    chapters = parse_with_fixed_size("段落一。" * 200, chunk_size=50)
    assert len(chapters) >= 1
    assert all(c.title.startswith("第") and "段" in c.title for c in chapters), (
        f"标题应包含段号，实际: {[c.title for c in chapters]}"
    )
    # 段号应递增
    numbers = [c.chapter_number for c in chapters]
    assert numbers == sorted(numbers)
    assert numbers[0] == 1


def test_build_summary_does_not_filter_body_lines_with_keywords():
    """正文里出现'书名'/'作者'字样时不应被当成元数据过滤掉。"""
    text = (
        "书名: 真的书名\n"
        "作者: 真的作者\n"
        "\n"
        "故事情节里出现：'他高喊书名：张三是我的笔名'，"
        "以及一段对话：'作者：今天要写点什么好呢？'。\n"
    ).encode("utf-8")
    summary = _build_summary(text)
    assert "张三是我的笔名" in summary
    assert "今天要写点什么好呢" in summary


def test_build_summary_strips_real_metadata():
    text = (
        "title: Real Title\n"
        "author: Real Author\n"
        "\n"
        "正文段落开始，描述故事背景。\n"
    ).encode("utf-8")
    summary = _build_summary(text)
    assert "title:" not in summary
    assert "author:" not in summary
    assert "正文段落" in summary
