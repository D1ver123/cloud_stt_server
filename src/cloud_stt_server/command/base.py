from abc import ABC, abstractmethod

from cloud_stt_server.command.models import IntentRecognitionRequest, RobotCommand


class TextCommandParser(ABC):
    """Convert final ASR text into a normalized robot command."""

    @abstractmethod
    def parse(self, text: str) -> RobotCommand:
        raise NotImplementedError

    def parse_request(self, request: IntentRecognitionRequest) -> RobotCommand:
        return self.parse(request.query)
