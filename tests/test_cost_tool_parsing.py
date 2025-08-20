import logging

import pytest

from app.tools.finops.cost_tool import AzureCosts, ParsingError


def _make_tool() -> AzureCosts:
    return AzureCosts.__new__(AzureCosts)


def test_parse_date_invalid_logs(caplog):
    tool = _make_tool()
    with caplog.at_level(logging.WARNING):
        assert tool._parse_date("not-a-date") is None
    assert "not-a-date" in caplog.text


def test_parse_date_invalid_strict():
    tool = _make_tool()
    with pytest.raises(ParsingError):
        tool._parse_date("not-a-date", tolerant=False)


def test_parse_thresholds_invalid_logs(caplog):
    tool = _make_tool()
    with caplog.at_level(logging.WARNING):
        assert tool._parse_thresholds("abc") is None
    assert "abc" in caplog.text


def test_parse_thresholds_invalid_strict():
    tool = _make_tool()
    with pytest.raises(ParsingError):
        tool._parse_thresholds([0.5, "bad"], tolerant=False)
