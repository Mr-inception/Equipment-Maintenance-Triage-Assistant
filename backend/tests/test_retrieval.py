from pathlib import Path

import pytest

from app.retrieval import KnowledgeBase, RetrievalError, default_kb_dir


@pytest.fixture(scope="module")
def kb():
    return KnowledgeBase.from_dir(default_kb_dir())


def test_all_three_equipment_types_loaded(kb):
    assert kb.equipment_types() == ["compressor", "motor", "pump"]


def test_bearing_temperature_query_finds_pump_section(kb):
    hits = kb.search("high bearing temperature", equipment_type="pump")
    assert hits and hits[0].chunk.id == "PUMP-1.1"


def test_equipment_filter_is_respected(kb):
    hits = kb.search("vibration", equipment_type="motor")
    assert hits and all(h.chunk.equipment_type == "motor" for h in hits)


def test_cavitation_noise_query(kb):
    hits = kb.search("crackling gravel noise low suction pressure", equipment_type="pump")
    assert hits[0].chunk.id == "PUMP-1.3"


def test_unknown_equipment_type_returns_no_hits_not_error(kb):
    assert kb.search("vibration", equipment_type="crane") == []


def test_empty_query_returns_no_hits(kb):
    assert kb.search("   ") == []


def test_missing_folder_raises_retrieval_error(tmp_path: Path):
    with pytest.raises(RetrievalError):
        KnowledgeBase.from_dir(tmp_path / "does-not-exist")


def test_folder_without_manuals_raises_retrieval_error(tmp_path: Path):
    with pytest.raises(RetrievalError):
        KnowledgeBase.from_dir(tmp_path)
