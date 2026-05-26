from cloud_stt_server.command import RuleCommandParser


def test_rule_parser_recognizes_motion_commands():
    parser = RuleCommandParser()

    assert parser.parse("请向前走").intent == "move_forward"
    assert parser.parse("机器人后退").intent == "move_backward"
    assert parser.parse("现在左转").intent == "turn_left"
    assert parser.parse("向右转一下").intent == "turn_right"
    assert parser.parse("马上停止").intent == "stop"


def test_rule_parser_preserves_raw_text_and_match_detail():
    parser = RuleCommandParser()

    command = parser.parse("请向前走。")

    assert command.raw_text == "请向前走。"
    assert command.params == {"matched_text": "向前"}
    assert command.confidence == 1.0
    assert command.parser == "rule"
    assert command.recognized is True


def test_rule_parser_returns_unknown_for_empty_or_unmatched_text():
    parser = RuleCommandParser()

    empty = parser.parse("  ")
    unknown = parser.parse("今天天气不错")

    assert empty.intent == "unknown"
    assert empty.recognized is False
    assert unknown.intent == "unknown"
    assert unknown.confidence == 0.0
