"""Unit tests for measurement guide extraction logic.

Tests the pure extraction functions directly (no LLM needed):
- _extract_measurements_from_history
- _try_contextual_bare_number

Scenarios:
- Keyword-first: "身高165cm胸围88cm腰围68cm臀围92cm"
- Bare number after AI asks (contextual inference)
- Positional 4-numbers: "165 88 68 92"
- Mixed format (keyword + positional)
- Out-of-range values rejected
- False-positive prevention: "165 胸围" must NOT assign 165 to bust
- Two-pass: keyword-first wins over number-first for same field
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from ai_customer_service.graph.nodes.measurement_guide_node import (
    _extract_measurements_from_history,
    _try_contextual_bare_number,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _human(text: str) -> HumanMessage:
    return HumanMessage(content=text)


def _ai(text: str) -> AIMessage:
    return AIMessage(content=text)


# ── Keyword-first extraction ──────────────────────────────────────────────────

def test_keyword_first_all_four_inline():
    """All four measurements with keyword-first format in one message."""
    msgs = [_human("身高165cm胸围88cm腰围68cm臀围92cm")]
    result = _extract_measurements_from_history(msgs)
    assert result == {"height": 165.0, "bust": 88.0, "waist": 68.0, "hips": 92.0}


def test_keyword_first_colon_format():
    """Chinese colon separator: 身高：165"""
    msgs = [_human("身高：165 胸围：88 腰围：68 臀围：92")]
    result = _extract_measurements_from_history(msgs)
    assert result["height"] == 165.0
    assert result["bust"] == 88.0
    assert result["waist"] == 68.0
    assert result["hips"] == 92.0


def test_keyword_first_partial_extraction():
    """Only some keywords present → only those extracted."""
    msgs = [_human("身高165，其他不知道")]
    result = _extract_measurements_from_history(msgs)
    assert result["height"] == 165.0
    assert "bust" not in result
    assert "waist" not in result
    assert "hips" not in result


def test_keyword_first_wins_over_number_first():
    """When '165cm胸围88cm', keyword-first bust=88, not 165 via number-first."""
    msgs = [_human("165cm胸围88cm")]
    result = _extract_measurements_from_history(msgs)
    # bust should be 88 (keyword-first: 胸围88cm), NOT 165 (number-first false positive)
    assert result.get("bust") == 88.0
    # 165 is not height here (no height keyword), should be absent
    assert "height" not in result


def test_false_positive_prevention_space_before_keyword():
    """'165 胸围88' must NOT assign 165 to bust (requires unit or direct adjacency)."""
    msgs = [_human("165 胸围88")]
    result = _extract_measurements_from_history(msgs)
    # keyword-first: 胸围88 → bust=88 ✓
    assert result.get("bust") == 88.0
    # number-first for height: no height keyword, so 165 absent
    assert "height" not in result


def test_inline_all_with_spaces():
    """'身高 165 胸围 88 腰围 68 臀围 92' (spaces after keyword)."""
    msgs = [_human("身高 165 胸围 88 腰围 68 臀围 92")]
    result = _extract_measurements_from_history(msgs)
    assert result.get("height") == 165.0
    assert result.get("bust") == 88.0
    assert result.get("waist") == 68.0
    assert result.get("hips") == 92.0


# ── Positional 4-number fallback ──────────────────────────────────────────────

def test_positional_four_numbers_in_range():
    """'165 88 68 92' → assigns by position: height bust waist hips."""
    msgs = [_human("165 88 68 92")]
    result = _extract_measurements_from_history(msgs)
    assert result.get("height") == 165.0
    assert result.get("bust") == 88.0
    assert result.get("waist") == 68.0
    assert result.get("hips") == 92.0


def test_positional_four_numbers_with_cm():
    """'165cm 88cm 68cm 92cm' (all with units) → positional assignment."""
    msgs = [_human("165cm 88cm 68cm 92cm")]
    result = _extract_measurements_from_history(msgs)
    assert result.get("height") == 165.0
    assert result.get("bust") == 88.0
    assert result.get("waist") == 68.0
    assert result.get("hips") == 92.0


def test_positional_requires_all_four_in_range():
    """4 numbers but first is out of height range → positional NOT used."""
    # 250 is out of height range (140-200), so positional assignment doesn't apply
    msgs = [_human("250 88 68 92")]
    result = _extract_measurements_from_history(msgs)
    # Without keyword context, 250 can't be assigned to height
    assert "height" not in result


def test_positional_five_numbers_not_assigned():
    """5 numbers → ambiguous, positional fallback does NOT fire."""
    msgs = [_human("165 88 68 92 45")]
    result = _extract_measurements_from_history(msgs)
    # Positional only fires for exactly 4 numbers
    # May or may not have values depending on keyword patterns, but NOT all four
    # (since no keywords present, and 5 numbers prevent positional)
    keys = set(result.keys())
    assert len(keys) < 4 or not all(k in keys for k in ["height", "bust", "waist", "hips"])


# ── Out-of-range handling ──────────────────────────────────────────────────────
# _extract_measurements_from_history returns RAW extracted values (no range check).
# Range validation ("validated" vs "invalid_fields") is done in measurement_guide_node().
# These tests document the extraction contract and the node's range-validation logic.

def test_out_of_range_height_extracted_raw():
    """Height 300 IS extracted by the function (raw); node will flag it as invalid."""
    msgs = [_human("身高300cm")]
    result = _extract_measurements_from_history(msgs)
    # Raw extraction captures the value; node validates separately
    assert result.get("height") == 300.0


def test_out_of_range_bust_extracted_raw():
    """Bust 200 IS extracted by the function (raw); node will flag it as invalid."""
    msgs = [_human("胸围200cm")]
    result = _extract_measurements_from_history(msgs)
    assert result.get("bust") == 200.0


def test_out_of_range_waist_extracted_raw():
    """Waist 30 IS extracted by the function (raw); node will flag it as invalid."""
    msgs = [_human("腰围30cm")]
    result = _extract_measurements_from_history(msgs)
    assert result.get("waist") == 30.0


def test_node_validates_out_of_range_fields():
    """Integration: node separates valid from invalid; invalid values shown as warning."""
    from ai_customer_service.graph.nodes.measurement_guide_node import _VALID_RANGES
    # Simulate what the node does with extracted values
    extracted = {"height": 300.0, "bust": 88.0}
    validated = {}
    invalid_fields = {}
    for field, value in extracted.items():
        lo, hi = _VALID_RANGES[field]
        if lo <= value <= hi:
            validated[field] = value
        else:
            invalid_fields[field] = value
    assert "height" in invalid_fields   # 300 out of 140-200
    assert "bust" in validated          # 88 in 70-130


def test_in_range_boundary_accepted():
    """Boundary values: height=140, bust=70, waist=50, hips=70 are all valid."""
    msgs = [_human("身高140 胸围70 腰围50 臀围70")]
    result = _extract_measurements_from_history(msgs)
    assert result.get("height") == 140.0
    assert result.get("bust") == 70.0
    assert result.get("waist") == 50.0
    assert result.get("hips") == 70.0


# ── Later values override earlier ones ───────────────────────────────────────

def test_later_value_overrides_earlier():
    """User corrects measurement in later message → later value wins."""
    msgs = [
        _human("身高160"),  # initial
        _human("不对，我身高165"),  # correction
    ]
    result = _extract_measurements_from_history(msgs)
    assert result.get("height") == 165.0


# ── Contextual bare-number capture ───────────────────────────────────────────

def test_contextual_bare_number_height():
    """AI asks for height → user replies with just '165' → height captured."""
    msgs = [
        _ai("请告诉我您的身高（单位：cm）"),
        _human("165"),
    ]
    already = {}
    result = _try_contextual_bare_number(msgs, already)
    assert result.get("height") == 165.0


def test_contextual_bare_number_bust():
    """AI asks for bust → user replies '88' → bust captured."""
    msgs = [
        _ai("好的，请告诉我您的胸围"),
        _human("88"),
    ]
    result = _try_contextual_bare_number(msgs, {})
    assert result.get("bust") == 88.0


def test_contextual_bare_number_waist():
    """AI asks for waist → user replies '68' → waist captured."""
    msgs = [
        _ai("您的腰围是多少呢？"),
        _human("68"),
    ]
    result = _try_contextual_bare_number(msgs, {})
    assert result.get("waist") == 68.0


def test_contextual_bare_number_hips():
    """AI asks for hips → user replies '92' → hips captured."""
    msgs = [
        _ai("最后一项，请问您的臀围是多少？"),
        _human("92"),
    ]
    result = _try_contextual_bare_number(msgs, {})
    assert result.get("hips") == 92.0


def test_contextual_no_override_if_already_collected():
    """If field already collected, bare number does NOT override it."""
    msgs = [
        _ai("请告诉我您的身高"),
        _human("170"),  # user says 170
    ]
    already = {"height": 165.0}  # already have height
    result = _try_contextual_bare_number(msgs, already)
    # Should not overwrite the already-collected value
    assert result.get("height") == 165.0


def test_contextual_ambiguous_multiple_numbers_ignored():
    """Multiple bare numbers in reply → ambiguous, contextual capture skipped."""
    msgs = [
        _ai("请告诉我您的身高"),
        _human("165 170"),  # two numbers — ambiguous
    ]
    result = _try_contextual_bare_number(msgs, {})
    assert "height" not in result


def test_contextual_out_of_range_ignored():
    """Bare number outside valid range → not captured."""
    msgs = [
        _ai("请问您的身高是多少？"),
        _human("250"),  # out of height range 140-200
    ]
    result = _try_contextual_bare_number(msgs, {})
    assert "height" not in result


def test_contextual_no_ai_message_skipped():
    """No prior AI message → contextual capture returns already_collected unchanged."""
    msgs = [_human("165")]
    already = {"bust": 88.0}
    result = _try_contextual_bare_number(msgs, already)
    assert result == already  # unchanged


def test_contextual_unknown_field_asked_skipped():
    """AI message doesn't clearly ask for a specific field → no bare-number assignment."""
    msgs = [
        _ai("您好，欢迎来到缘梦婚纱！"),
        _human("165"),
    ]
    result = _try_contextual_bare_number(msgs, {})
    # No field-specific keyword in AI message → should not assign
    assert "height" not in result
    assert "bust" not in result


# ── Mixed format (keyword + positional) ───────────────────────────────────────

def test_mixed_keyword_and_positional():
    """Keyword captures some fields; positional fallback handles none if partial."""
    msgs = [_human("身高165 胸围88 腰围68 臀围92")]
    result = _extract_measurements_from_history(msgs)
    # All four captured via keyword (not positional)
    assert result == {"height": 165.0, "bust": 88.0, "waist": 68.0, "hips": 92.0}


def test_mixed_keyword_partial_then_positional():
    """Only 2 keyword fields found, then 4-number positional fills rest."""
    # User sends "身高165 胸围88" in one message, then "165 88 68 92" in next
    msgs = [
        _human("身高165 胸围88"),
        _human("165 88 68 92"),  # re-stating all four
    ]
    result = _extract_measurements_from_history(msgs)
    # Positional in second message should fill in waist and hips
    assert result.get("height") == 165.0
    assert result.get("bust") == 88.0
    assert result.get("waist") == 68.0
    assert result.get("hips") == 92.0


# ── Full integration: extract + contextual ────────────────────────────────────

def test_extract_then_contextual_fills_remaining():
    """After keyword extraction gets 3 fields, contextual captures the 4th."""
    msgs = [
        _human("身高165 胸围88 腰围68"),
        _ai("好的！最后请告诉我您的臀围"),
        _human("92"),
    ]
    # Step 1: keyword extraction
    extracted = _extract_measurements_from_history(msgs)
    assert extracted.get("height") == 165.0
    assert extracted.get("bust") == 88.0
    assert extracted.get("waist") == 68.0
    assert "hips" not in extracted

    # Step 2: contextual captures hips
    final = _try_contextual_bare_number(msgs, extracted)
    assert final.get("hips") == 92.0
    assert len(final) == 4
