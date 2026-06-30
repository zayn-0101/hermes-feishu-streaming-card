from hermes_feishu_card.render import MAIN_CONTENT_CHUNK_CHARS
from hermes_feishu_card.text import (
    StreamingTextNormalizer,
    normalize_stream_text,
    should_flush_text,
    split_markdown_blocks,
)


def test_normalize_removes_think_tags():
    raw = "<think>我在分析</think>\n最终不会出现标签"
    assert normalize_stream_text(raw) == "我在分析\n最终不会出现标签"


def test_normalize_removes_mixed_case_think_tags():
    raw = "<THINK>我在分析</Think>\n最终不会出现标签"
    assert normalize_stream_text(raw) == "我在分析\n最终不会出现标签"


def test_normalize_handles_empty_input():
    assert normalize_stream_text("") == ""
    assert normalize_stream_text(None) == ""


def test_streaming_normalizer_removes_split_think_tags():
    normalizer = StreamingTextNormalizer()

    chunks = ["<thi", "nk>分片</thi", "nk>"]
    result = "".join(normalizer.feed(chunk) for chunk in chunks)

    assert result == "分片"


def test_streaming_normalizer_removes_mixed_case_split_think_tags():
    normalizer = StreamingTextNormalizer()

    chunks = ["<TH", "INK>分片</Th", "ink>"]
    result = "".join(normalizer.feed(chunk) for chunk in chunks)

    assert result == "分片"


def test_flushes_on_chinese_sentence_end():
    assert should_flush_text("我先分析这个问题。", elapsed_ms=50, max_wait_ms=800, max_chars=200)


def test_flushes_on_newline_boundary():
    assert should_flush_text("第一段\n", elapsed_ms=50, max_wait_ms=800, max_chars=200)


def test_flushes_on_wait_threshold():
    assert should_flush_text("半句话", elapsed_ms=801, max_wait_ms=800, max_chars=200)


def test_flushes_on_equal_wait_threshold():
    assert should_flush_text("半句话", elapsed_ms=800, max_wait_ms=800, max_chars=200)


def test_flushes_on_equal_max_chars():
    assert should_flush_text("四个字", elapsed_ms=50, max_wait_ms=800, max_chars=3)


def test_force_flushes_empty_buffer():
    assert should_flush_text("", elapsed_ms=0, max_wait_ms=800, max_chars=200, force=True)


def test_does_not_flush_tiny_fragment_too_early():
    assert not should_flush_text("半句话", elapsed_ms=100, max_wait_ms=800, max_chars=200)


def test_normalize_removes_thinking_tags():
    assert normalize_stream_text("<thinking>推理中</thinking>结果") == "推理中结果"
    assert normalize_stream_text("<THINKING>推理</THINKING>") == "推理"


def test_streaming_normalizer_handles_thinking_split_across_chunks():
    normalizer = StreamingTextNormalizer()
    assert normalizer.feed("hello<think") == "hello"
    assert normalizer.feed("ing>world") == "world"


def test_normalize_does_not_remove_plain_think_word():
    assert normalize_stream_text("I think so") == "I think so"
    assert normalize_stream_text("I am thinking") == "I am thinking"


# —— 表格统计 ————————————————————————————————

def test_count_markdown_tables_zero():
    from hermes_feishu_card.text import count_markdown_tables
    assert count_markdown_tables("hello world") == 0
    assert count_markdown_tables("| name | age |") == 0  # no separator


def test_count_markdown_tables_normal():
    from hermes_feishu_card.text import count_markdown_tables
    text = "| a | b |\n| --- | --- |\n| 1 | 2 |\n\n| x | y |\n| --- | --- |\n| 3 | 4 |"
    assert count_markdown_tables(text) == 2


def test_count_markdown_tables_seven():
    from hermes_feishu_card.text import count_markdown_tables
    text = "\n\n".join([f"| col |\n| --- |\n| {i} |" for i in range(7)])
    assert count_markdown_tables(text) == 7


def test_max_card_tables_constant():
    from hermes_feishu_card.text import MAX_CARD_TABLES
    assert MAX_CARD_TABLES == 5


def test_split_markdown_blocks_preserves_table_structure():
    table = "| 功能 | 说明 |\n| --- | --- |\n| ASR | 中文识别 |\n| VAD | 静音切割 |"
    text = "A" * 1000 + "\n\n" + table + "\n\n" + "B" * 1000

    chunks = split_markdown_blocks(text, 1200)

    table_chunks = [chunk for chunk in chunks if "| ASR |" in chunk]
    assert len(table_chunks) == 1
    assert table in table_chunks[0]


def test_split_markdown_blocks_preserves_fenced_code_block():
    code = "```python\nprint('hello')\nprint('world')\n```"
    text = "X" * 1000 + "\n\n" + code + "\n\n" + "Y" * 1000

    chunks = split_markdown_blocks(text, 1100)

    code_chunks = [chunk for chunk in chunks if "```python" in chunk]
    assert len(code_chunks) == 1
    assert code in code_chunks[0]


def test_split_markdown_blocks_splits_oversized_plain_text():
    text = "Hello world " * 500

    chunks = split_markdown_blocks(text, 1000)

    assert len(chunks) > 1
    assert "".join(chunks).replace("\n", "") == text.replace("\n", "")
    assert all(len(chunk) <= 1000 for chunk in chunks)


def test_split_markdown_blocks_prefers_list_item_boundaries():
    text = "\n".join(f"1. item {index} {'甲' * 40}" for index in range(80))

    chunks = split_markdown_blocks(text, 120)

    assert len(chunks) > 1
    assert all(len(chunk) <= 120 for chunk in chunks)
    assert all(chunk.startswith("1. ") for chunk in chunks[1:])
    assert "".join(chunks).replace("\n", "") == text.replace("\n", "")


def test_split_markdown_blocks_avoids_inline_code_split_when_possible():
    text = "前言\n\n" + " ".join("`alpha beta gamma delta epsilon`" for _ in range(80))

    chunks = split_markdown_blocks(text, 120)

    assert len(chunks) > 1
    assert all(len(chunk) <= 120 for chunk in chunks)
    for chunk in chunks:
        assert chunk.count("`") % 2 == 0


def test_split_markdown_blocks_handles_oversized_table_row_without_plain_fragments():
    oversized_value = "超长字段" * 700
    table = f"| 字段 | 内容 |\n| --- | --- |\n| key | {oversized_value} |\n"

    chunks = split_markdown_blocks(table, MAIN_CONTENT_CHUNK_CHARS)

    assert len(chunks) > 1
    assert all(len(chunk) <= MAIN_CONTENT_CHUNK_CHARS for chunk in chunks)
    for chunk in chunks:
        if "| --- | --- |" in chunk:
            lines = [line for line in chunk.splitlines() if line.strip()]
            assert len(lines) >= 3
            assert lines[0].startswith("|")
            assert lines[1].startswith("|")
            assert all(line.startswith("|") and line.endswith("|") for line in lines[2:])
