class BadBytesFromServer(Exception):
    """The server did not give a correct frame"""


class ConnectionClosedByHeartbeatMonitor(Exception):
    """The server did not send any data in too long."""


class ConnectionClosedByServer(Exception):
    """The server sent a Close() frame."""

    def __init__(self, reply_code: int, reply_text: str) -> None:
        super().__init__(self, reply_code, reply_text)
        self.reply_code = reply_code
        self.reply_text = reply_text

    def __str__(self):
        return "RabbitMQ closed the connection: %d %s" % (
            self.reply_code,
            self.reply_text,
        )


class ConnectionClosed(Exception):
    """The connection is closed, so your operation cannot go on."""


class ServerSentNack(Exception):
    """The RabbitMQ sent a "nack" in publisher_confirms mode."""


class ChannelClosed(Exception):
    """The channel is closed, so your operation cannot go on."""


class ChannelClosedByServer(Exception):
    """The server sent a Close() frame."""

    def __init__(self, reply_code: int, reply_text: str) -> None:
        super().__init__(self, reply_code, reply_text)
        self.reply_code = reply_code
        self.reply_text = reply_text

    def __str__(self):
        return "RabbitMQ closed the channel: %d %s" % (
            self.reply_code,
            self.reply_text,
        )
