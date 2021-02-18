from __future__ import annotations

import asyncio
import logging
from functools import singledispatchmethod
from typing import Callable, List, NamedTuple, Optional, Tuple

import pamqp.base
import pamqp.body
import pamqp.commands
import pamqp.exceptions
import pamqp.header

from ._channel import AcceptableFrame, Channel
from ._exceptions import ChannelClosed, ChannelClosedByServer, ConnectionClosed
from ._frame_writer import FrameWriter

logger = logging.getLogger(__name__)


class _Delivery(NamedTuple):
    deliver: pamqp.commands.Basic.Deliver
    header: Optional[pamqp.header.ContentHeader] = None
    body: List[pamqp.body.ContentBody] = []

    def add_HEADER(self, header: pamqp.header.ContentHeader) -> _Delivery:
        """Return this _Delivery with its header frame."""
        return self._replace(header=header)

    def add_BODY(self, body: pamqp.body.ContentBody) -> _Delivery:
        """Return a _Delivery with an added body frame."""
        return self._replace(body=self.body + [body])


async def _next_delivery(
    queue: asyncio.Queue, closed: asyncio.Future
) -> Tuple[bytes, int]:
    delivery_task = asyncio.create_task(queue.get())
    done, pending = await asyncio.wait(
        (delivery_task, closed), return_when=asyncio.FIRST_COMPLETED
    )
    if delivery_task in done:
        delivery = delivery_task.result()
        return (
            b"".join(body.value for body in delivery.body),
            delivery.deliver.delivery_tag,
        )
    else:  # `self.closed` in Done
        delivery_task.cancel()
        closed.result()  # raise exception if there is one
        raise ChannelClosed


class ConsumeChannelIterator:
    def __init__(
        self,
        queue: asyncio.Queue[_Delivery],
        closed: asyncio.Future[None],
        ack: Callable[[int], None],
    ):
        self._queue = queue
        self._closed = closed
        self._ack = ack
        self._yielded_delivery_tag: Optional[int] = None

    def __aiter__(self):
        return self  # pragma: no cover

    async def __anext__(self):
        if self._yielded_delivery_tag is not None:
            self._ack(self._yielded_delivery_tag)

        try:
            message, self._yielded_delivery_tag = await _next_delivery(
                self._queue, self._closed
            )
            return message
        except ChannelClosed:
            raise StopAsyncIteration from None
        # Other exceptions we'll re-raise.


class ConsumeChannel(Channel):
    """A Channel that presents messages as an async iterator."""

    def __init__(
        self,
        frame_writer: FrameWriter,
        *,
        queue_name: str,
        prefetch_size: int,
        prefetch_count: int,
    ):
        self._frame_writer = frame_writer
        self._delivery: Optional[_Delivery] = None
        self._queue: asyncio.Queue[_Delivery] = asyncio.Queue()
        self.closed: asyncio.Future[None] = asyncio.Future()

        self._frame_writer.send_frames(
            [
                pamqp.commands.Channel.Open(),
                pamqp.commands.Basic.Qos(
                    prefetch_size=prefetch_size, prefetch_count=prefetch_count
                ),
                pamqp.commands.Basic.Consume(
                    queue=queue_name, consumer_tag="carehare", nowait=True
                ),
            ]
        )

    def ack(self, delivery_tag: int):
        """Write Basic.Ack to RabbitMQ.

        This method is _synchronous_: it marks the _beginning_ of an ack. You
        can't know whether RabbitMQ will receive the ack.

        If you call this during channel close or connection close, nothing will
        happen.
        """
        self._frame_writer.send_frame(
            pamqp.commands.Basic.Ack(delivery_tag=delivery_tag),
        )

    @singledispatchmethod
    def accept_frame(self, frame: AcceptableFrame) -> None:
        raise NotImplementedError("Unexpected frame: %r" % frame)  # pragma: no cover

    @accept_frame.register  # type: ignore[no-redef]
    def _(self, frame: pamqp.commands.Channel.OpenOk) -> None:  # type: ignore[no-redef]
        pass

    def _raise_if_delivery_is_set(self):
        if self._delivery:
            # ref: 4.2.6
            # Note that any non-content frame explicitly marks the end of the
            # content. Although the size of the content is well-known from the
            # content header (and thus also the number of content frames), this
            # allows for a sender to abort the sending of content without the
            # need to close the channel.
            #
            # Guidelines for implementers:
            #  A peer that receives an incomplete or badly-formatted content
            # MUST raise a connection exception with reply code 505 (unexpected
            # frame). This includes missing content headers, wrong class IDs in
            # content headers, missing content body frames, etc.
            #
            # ... [adamhooper, 2021-02-15] these two paragraphs seem to
            # conflict; isn't a 'connection exception' a hard error? Let's call
            # it a hard error.
            raise pamqp.exceptions.AMQPUnexpectedFrame(
                "RabbitMQ server did not finish sending body"
            )

    @accept_frame.register  # type: ignore[no-redef]
    def _(self, frame: pamqp.commands.Basic.QosOk) -> None:  # type: ignore[no-redef]
        self._raise_if_delivery_is_set()

    @accept_frame.register  # type: ignore[no-redef]
    def _(self, frame: pamqp.commands.Basic.Deliver) -> None:  # type: ignore[no-redef]
        self._raise_if_delivery_is_set()
        self._delivery = _Delivery(frame)

    @accept_frame.register  # type: ignore[no-redef]
    def _(self, frame: pamqp.header.ContentHeader) -> None:  # type: ignore[no-redef]
        assert self._delivery is not None
        assert self._delivery.header is None
        self._delivery = self._delivery.add_HEADER(frame)  # Raises AMQPUnexpectedFrame

    @accept_frame.register  # type: ignore[no-redef]
    def _(self, frame: pamqp.body.ContentBody) -> None:  # type: ignore[no-redef]
        assert self._delivery is not None
        assert self._delivery.header is not None
        delivery = self._delivery.add_BODY(frame)

        if (
            sum(len(frame.value) for frame in delivery.body)
            >= self._delivery.header.body_size
        ):
            self._queue.put_nowait(delivery)
            self._delivery = None
        else:
            self._delivery = delivery

    async def next_delivery(self) -> Tuple[bytes, int]:
        """Receive a (message, delivery_tag) tuple from RabbitMQ.

        The caller must call consumer.ack(delivery_tag), or RabbitMQ may deliver
        the message to another client.

        Raise ConnectionClosed if we (or RabbitMQ) closed the connection.

        Raise ChannelClosedByServer if RabbitMQ sends us an error.

        Raise ChannelClosed if we closed the channel.
        """
        # raise ConnectionClosed, ChannelClosedByServer
        return await _next_delivery(self._queue, self.closed)

    def close(self):
        if not self.closed.done():
            self._frame_writer.send_close()
            # RabbitMQ will send Channel.Close, and then we'll resolve self.closed

    def accept_channel_closed_by_server(
        self, frame: pamqp.commands.Channel.Close
    ) -> None:
        self.closed.set_exception(
            ChannelClosedByServer(frame.reply_code or 0, frame.reply_text)
        )

    def accept_channel_closed_by_us(self) -> None:
        self.closed.set_result(None)

    def accept_connection_closed(self, exc: ConnectionClosed) -> None:
        self.closed.set_exception(exc)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        if exc_type:
            logger.exception("Closing consumer")
        self.close()
        await self.closed

    def __aiter__(self):
        return ConsumeChannelIterator(self._queue, self.closed, self.ack)
