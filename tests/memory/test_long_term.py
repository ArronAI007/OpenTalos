from memory.long_term import rank_memories


def test_rank_memories_orders_more_overlap_first():
    ranked = rank_memories("数据分析", ["数据分析", "数据", "分析", "完全无关"])
    assert ranked[0] == "数据分析"  # 命中 3 个二元组，高于单命中的两条
    assert "完全无关" not in ranked


def test_rank_memories_filters_zero_overlap():
    assert rank_memories("苹果", ["用户喜欢香蕉", "用户喜欢苹果"]) == ["用户喜欢苹果"]


def test_rank_memories_matches_latin():
    assert rank_memories("python", ["I write Python daily", "I like cats"]) == ["I write Python daily"]


def test_rank_memories_empty_query_returns_empty():
    assert rank_memories("", ["任意"]) == []


def test_rank_memories_respects_limit():
    memories = [f"苹果{i}" for i in range(10)]
    assert len(rank_memories("苹果", memories, limit=3)) == 3
