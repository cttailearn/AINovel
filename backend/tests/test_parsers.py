import pytest

from services.novel_service import (
    parse_with_fixed_size,
    parse_with_rule,
    ParseError,
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
