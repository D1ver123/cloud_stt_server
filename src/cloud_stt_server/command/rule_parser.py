import re
from collections.abc import Iterable

from cloud_stt_server.command.base import TextCommandParser
from cloud_stt_server.command.models import RobotCommand


class RuleCommandParser(TextCommandParser):
    def __init__(self) -> None:
        self._rules = (
            _Rule("stop", ("停止", "停下", "暂停", "别动", "不要动")),
            _Rule("move_forward", ("前进", "向前", "往前", "朝前", "向前走")),
            _Rule("move_backward", ("后退", "向后", "往后", "倒退", "向后走")),
            _Rule("turn_left", ("左转", "向左转", "往左转", "左拐", "向左")),
            _Rule("turn_right", ("右转", "向右转", "往右转", "右拐", "向右")),
        )

    def parse(self, text: str) -> RobotCommand:
        raw_text = text.strip()
        normalized = _normalize_text(raw_text)
        if not normalized:
            return RobotCommand(
                intent="unknown",
                raw_text=raw_text,
                confidence=0.0,
                parser="rule",
            )

        for rule in self._rules:
            matched = rule.match(normalized)
            if matched is not None:
                return RobotCommand(
                    intent=rule.intent,
                    raw_text=raw_text,
                    params={"matched_text": matched},
                    confidence=1.0,
                    parser="rule",
                )

        return RobotCommand(
            intent="unknown",
            raw_text=raw_text,
            confidence=0.0,
            parser="rule",
        )


class _Rule:
    def __init__(self, intent: str, keywords: Iterable[str]) -> None:
        self.intent = intent
        self.keywords = tuple(_normalize_text(keyword) for keyword in keywords)

    def match(self, text: str) -> str | None:
        for keyword in self.keywords:
            if keyword and keyword in text:
                return keyword
        return None


def _normalize_text(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[\s,，。.!！?？、；;：:]+", "", text)
    return text
