from __future__ import annotations

import asyncio
from functools import singledispatchmethod
from typing import Dict, List

import pamqp.base
import pamqp.body
import pamqp.commands
import pamqp.exceptions
import pamqp.header

from ._channel import Channel
from ._exceptions import ChannelClosedByServer, ConnectionClosed, ServerSentNack
from ._frame_writer import FrameWriter


class ExchangeChannel(Channel):
    def __init__(
        self,
        exchange_name: str,
        *,
        frame_writer: FrameWriter,
    ) -> None:
        self.exchange_name = exchange_name
        self._frame_writer = frame_writer
        self._delivering: Dict[int, asyncio.Future] = {}
        self._next_delivery_tag = 1

        self._frame_writer.send_frames(
            [
                pamqp.commands.Channel.Open(),
                pamqp.commands.Confirm.Select(nowait=True),
            ]
        )

    @singledispatchmethod
    def accept_frame(self, frame) -> None:
        raise NotImplementedError("Unexpected frame: %r" % frame)  # pragma: no cover

    @accept_frame.register  # type: ignore[no-redef]
    def _(self, frame: pamqp.commands.Channel.OpenOk) -> None:
        pass

    def _find_delivery_tags(self, delivery_tag: int, multiple: bool) -> List[int]:
        if multiple:
            return [tag for tag in self._delivering.keys() if tag <= delivery_tag]
        else:
            return [delivery_tag]

    @accept_frame.register  # type: ignore[no-redef]
    def _(self, frame: pamqp.commands.Basic.Ack) -> None:
        for tag in self._find_delivery_tags(frame.delivery_tag, frame.multiple):
            self._delivering.pop(tag).set_result(None)

    @accept_frame.register  # type: ignore[no-redef]
    def _(self, frame: pamqp.commands.Basic.Nack) -> None:
        for tag in self._find_delivery_tags(frame.delivery_tag, frame.multiple):
            self._delivering.pop(tag).set_exception(ServerSentNack())

    def accept_channel_closed_by_server(
        self, frame: pamqp.commands.Channel.Close
    ) -> None:
        exc = ChannelClosedByServer(frame.reply_code or 0, frame.reply_text)
        for delivery in self._delivering.values():
            delivery.set_exception(exc)
        self._delivering.clear()

    def accept_channel_closed_by_us(self) -> None:
        raise NotImplementedError(
            "We never send Channel.Close; how did we get here?"
        )  # pragma: no cover

    def accept_connection_closed(self, exc: ConnectionClosed) -> None:
        for delivery in self._delivering.values():
            delivery.set_exception(exc)
        self._delivering.clear()

    def publish(self, message: bytes, routing_key: str = "") -> asyncio.Future[None]:
        self._frame_writer.send_frames(
            [
                pamqp.commands.Basic.Publish(
                    exchange=self.exchange_name, routing_key=routing_key
                ),
                pamqp.header.ContentHeader(body_size=len(message)),
                pamqp.body.ContentBody(value=message),
            ]
        )
        done: asyncio.Future[None] = asyncio.Future()
        self._delivering[self._next_delivery_tag] = done
        self._next_delivery_tag += 1
        return done
