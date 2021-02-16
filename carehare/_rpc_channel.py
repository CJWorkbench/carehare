import asyncio
from functools import singledispatchmethod

import pamqp.base
import pamqp.commands
import pamqp.exceptions

from ._channel import AcceptableFrame, Channel
from ._exceptions import ChannelClosedByServer, ConnectionClosed
from ._frame_writer import FrameWriter


class RpcChannel(Channel):
    def __init__(
        self,
        frame: pamqp.base.Frame,
        frame_writer: FrameWriter,
    ) -> None:
        self._frame_writer = frame_writer
        self.done: asyncio.Future[None] = asyncio.Future()

        self._frame_writer.send_frames(
            [
                pamqp.commands.Channel.Open(),
                frame,
                pamqp.commands.Channel.Close(
                    reply_code=0,
                    reply_text="",
                    class_id=0,
                    method_id=0,
                ),
            ]
        )

    @singledispatchmethod
    def accept_frame(self, frame: AcceptableFrame) -> None:
        raise NotImplementedError("Unexpected frame: %r" % frame)  # pragma: no cover

    @accept_frame.register
    def _(self, frame: pamqp.commands.Channel.OpenOk) -> None:
        pass

    def accept_channel_closed_by_server(
        self, frame: pamqp.commands.Channel.Close
    ) -> None:
        self.done.set_exception(
            ChannelClosedByServer(frame.reply_code or 0, frame.reply_text)
        )

    def accept_channel_closed_by_us(self) -> None:
        self.done.set_result(None)

    def accept_connection_closed(self, exc: ConnectionClosed) -> None:
        self.done.set_exception(exc)
