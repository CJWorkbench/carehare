# Refs in comments in this file point to https://www.rabbitmq.com/resources/specs/amqp0-9-1.pdf
from __future__ import annotations

import asyncio
import logging
import platform
import struct
from functools import singledispatchmethod
from typing import Dict, Optional, Tuple, Type, Union, cast

import pamqp.common
import pamqp.exceptions
import pamqp.frame
import pamqp.header

from . import _exceptions, _heartbeat
from ._channel import AcceptableFrame, Channel
from ._channel_id_store import ChannelIdStore
from ._consume_channel import ConsumeChannel
from ._exceptions import ConnectionClosed, ConnectionClosedByHeartbeatMonitor
from ._exchange_channel import ExchangeChannel
from ._frame_writer import FrameWriter
from ._rpc_channel import RpcChannel

logger = logging.getLogger(__name__)


def _safe_unmarshal_frame(
    buf: bytearray,
) -> Optional[
    Tuple[
        int,
        int,
        Union[
            pamqp.base.Frame,
            pamqp.body.ContentBody,
            pamqp.header.ContentHeader,
            pamqp.heartbeat.Heartbeat,
        ],
    ]
]:
    if len(buf) < 7:
        return None
    (size,) = struct.unpack("!I", buf[3:7])
    frame_size = size + 8  # 7 bytes for header, 1 byte for frame-end
    if len(buf) < frame_size:
        return None
    n_bytes, channel_id, frame = pamqp.frame.unmarshal(bytes(buf[:frame_size]))
    # pamqp unmarshals the ProtocolHeader; but we handle that one specially.
    assert not isinstance(frame, pamqp.header.ProtocolHeader)
    return n_bytes, channel_id, frame


class Protocol(asyncio.Protocol):
    def __init__(
        self, username: str = "guest", password: str = "guest", virtual_host: str = "/"
    ):
        self._username = username
        self._password = password
        self._virtual_host = virtual_host
        self._buffer = bytearray()
        # Negotiation frames, keyed by class. ref: 2.2.4
        self._lifecycle: Dict[Type[pamqp.base.Frame], pamqp.base.Frame] = {}
        self._channels: Dict[int, Channel] = {}
        self._closing_channels: Dict[int, Optional[pamqp.commands.Channel.Close]] = {}
        self._exchange_channels: Dict[str, ExchangeChannel] = {}
        self._heartbeat_monitor: Optional[_heartbeat.HeartbeatMonitor] = None
        self._heartbeat_sender: Optional[_heartbeat.HeartbeatSender] = None
        self.open: asyncio.Future[None] = asyncio.Future()
        self._crash_exc: Optional[Exception] = None
        self._close_frame: Optional[pamqp.commands.Connection.Close] = None
        self._closing: bool = False

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        assert isinstance(transport, asyncio.WriteTransport)
        self._transport = transport
        self._transport.write(pamqp.header.ProtocolHeader().marshal())  # ref: 2.2.4
        self._frame_writer = FrameWriter(transport, 0)

    def connection_lost(self, exc: Optional[Exception]) -> None:
        # ... we'll look to many places for exceptions that may supercede the
        # one asyncio gives us.
        if self._crash_exc:
            exc = self._crash_exc
        elif self._close_frame:
            exc = _exceptions.ConnectionClosedByServer(
                self._close_frame.reply_code or 0, self._close_frame.reply_text
            )

        if self._heartbeat_monitor is not None:
            self._heartbeat_monitor.cancel()

        if self._heartbeat_sender is not None:
            self._heartbeat_sender.cancel()

        logger.info("Connection lost: %r", exc)

        if self._channels:
            closed_exc = ConnectionClosed()
            for channel in list(self._channels.values()):
                channel.accept_connection_closed(closed_exc)
            self._channels.clear()
            self._closing_channels.clear()

        if self.open.done():
            if exc:
                self.closed.set_exception(exc)
            else:
                self.closed.set_result(None)
        else:
            assert exc is not None
            self.open.set_exception(exc)

    def data_received(self, data: bytes) -> None:
        if self._heartbeat_monitor is not None:
            self._heartbeat_monitor.reset()

        self._buffer.extend(data)
        self._handle_buffer_frames()

    def _crash(self, exc: Exception) -> None:
        self._crash_exc = exc
        if pamqp.commands.Connection.Tune not in self._lifecycle:
            # ref: 2.2.4
            # "There is no hand-shaking for errors on connections that are not
            # fully open. Following successful protocol header negotiation,
            # which is defined in detail later, and prior to sending or
            # receiving Open or Open-Ok, a peer that detects an error MUST close
            # the socket without sending any further data."
            logger.exception(
                "Disconnecting because of error during negotiation", exc_info=exc
            )
            self._transport.abort()
        else:
            logger.exception("Sending Connection.Close because of error", exc_info=exc)
            if (
                isinstance(exc, pamqp.exceptions.PAMQPException)
                and hasattr(exc, "name")
                and hasattr(exc, "value")
            ):
                self.send_close_if_allowed(reply_code=exc.value, reply_text=exc.name)  # type: ignore[attr-defined]
            elif isinstance(exc, NotImplementedError):
                self.send_close_if_allowed(reply_code=540, reply_text="NOT-IMPLEMENTED")
            else:
                self.send_close_if_allowed(reply_code=541, reply_text="INTERNAL-ERROR")
            # ... and we expect RabbitMQ to handshake the closure

    def _handle_buffer_frames(self) -> None:
        """Unmarshal and handle all whole frames on `self._buffer`.

        When this method returns, `self._buffer` will be empty or contain the
        start of an incomplete frame.

        Log and call `_crash()` if handling fails.
        """
        while True:
            try:
                frame_result = _safe_unmarshal_frame(self._buffer)
            except pamqp.exceptions.UnmarshalingException:
                logger.exception("Invalid frame from RabbitMQ server")
                self._crash(
                    _exceptions.BadBytesFromServer("Invalid frame from RabbitMQ server")
                )
                return

            if frame_result is None:
                break

            n_bytes, channel_id, frame = frame_result
            self._buffer = self._buffer[n_bytes:]
            self._handle_frame_or_crash(channel_id, frame)

    def _handle_frame_or_crash(
        self,
        channel_id: int,
        frame: Union[
            pamqp.base.Frame,
            pamqp.body.ContentBody,
            pamqp.header.ContentHeader,
            pamqp.heartbeat.Heartbeat,
        ],
    ) -> None:
        logger.debug("accept_frame: %r", frame)
        try:
            self.accept_frame(frame, channel_id)
        except (pamqp.exceptions.PAMQPException, NotImplementedError) as err:
            self._crash(err)
            return

    def _assert_channel_id_0(
        self, frame: Union[AcceptableFrame, pamqp.heartbeat.Heartbeat], channel_id: int
    ) -> None:
        # ref: 4.2.3
        #
        # "The channel number MUST be zero for all heartbeat frames, and for
        # method, header and body frames that refer to the Connection class. A
        # peer that receives a non-zero channel number for one of these frames
        # MUST signal a connection exception with reply code 503 (command
        # invalid)."
        if channel_id != 0:
            raise pamqp.exceptions.AMQPCommandInvalid(
                "Got channel_id=%d on frame %r" % (channel_id, frame)
            )

    def accept_frame(
        self, frame: Union[AcceptableFrame, pamqp.heartbeat.Heartbeat], channel_id: int
    ) -> None:
        """Handle a single frame from the server.

        Raise NotImplementedError if it is an unexpected or incorrect frame.
        """
        if self.open.done():
            return self._accept_frame_after_handshake(frame, channel_id)
        else:
            self._assert_channel_id_0(frame, channel_id)
            return self._accept_handshake_frame(frame)

    @singledispatchmethod
    def _accept_frame_after_handshake(self, frame, channel_id: int) -> None:
        channel = self._channels[channel_id]  # KeyError means bug here or on server
        channel.accept_frame(frame)

    @_accept_frame_after_handshake.register  # type: ignore[no-redef]
    def _(self, frame: pamqp.commands.Connection.Close, channel_id: int) -> None:
        self._close_frame = frame
        # ref: 2.2.4
        #  One peer (client or server) ends the connection (Close).
        #  The other peer hand-shakes the connection end (Close-Ok).
        self._frame_writer.send_frame(pamqp.commands.Connection.CloseOk())
        self._transport.close()  # asyncio will flush buffered data asynchronously

    @_accept_frame_after_handshake.register  # type: ignore[no-redef]
    def _(self, frame: pamqp.commands.Connection.CloseOk, channel_id: int) -> None:
        # ref: 2.2.4
        #  One peer (client or server) ends the connection (Close).
        #  The other peer hand-shakes the connection end (Close-Ok).
        self._transport.abort()  # calls self.connection_lost()

    @_accept_frame_after_handshake.register  # type: ignore[no-redef]
    def _(self, frame: pamqp.heartbeat.Heartbeat, channel_id: int) -> None:
        self._assert_channel_id_0(frame, channel_id)
        # _all_ network traffic counts as heartbeat frames, so we don't need to
        # do anything here. (We handle network traffic in self.data_received().)

    @_accept_frame_after_handshake.register  # type: ignore[no-redef]
    def _(self, frame: pamqp.commands.Channel.Close, channel_id: int) -> None:
        # We handle Channel.Close and Channel.Close-Ok because they can race:
        # the client and server can each send Close simultaneously, in which
        # case we want to

        # We always send close-ok...
        FrameWriter(self._transport, channel_id).send_frame(
            pamqp.commands.Channel.CloseOk()
        )

        if channel_id in self._closing_channels:
            # We sent a Close() ourselves; we're still waiting for server CloseOk()
            #
            # This frame from the server might be an exception; store it.
            self._closing_channels[channel_id] = frame
        elif channel_id in self._channels:
            # We never sent Close(), so this channel is done
            channel = self._channels.pop(channel_id)
            channel.accept_channel_closed_by_server(frame)
            self._channel_id_store.release(channel_id)
            if hasattr(channel, "exchange_name"):
                del self._exchange_channels[channel.exchange_name]
        else:
            logger.error(
                "RabbitMQ sent Close on nonexistent channel; responding ok anyway"
            )

    @_accept_frame_after_handshake.register  # type: ignore[no-redef]
    def _(self, frame: pamqp.commands.Channel.CloseOk, channel_id: int) -> None:
        close_frame = self._closing_channels.pop(channel_id)
        channel = self._channels.pop(channel_id)
        self._channel_id_store.release(channel_id)
        if hasattr(channel, "exchange_name"):
            del self._exchange_channels[channel.exchange_name]
        if close_frame is None:
            channel.accept_channel_closed_by_us()
        else:
            channel.accept_channel_closed_by_server(close_frame)

    @singledispatchmethod
    def _accept_handshake_frame(self, frame) -> None:
        raise NotImplementedError(
            "Unexpected frame during negotiation: %r" % frame
        )  # pragma: no cover

    @_accept_handshake_frame.register  # type: ignore [no-redef]
    def _(self, frame: pamqp.heartbeat.Heartbeat) -> None:
        pass  # already handled

    @_accept_handshake_frame.register  # type: ignore [no-redef]
    def _(self, frame: pamqp.commands.Connection.Start) -> None:
        assert pamqp.commands.Connection.Start not in self._lifecycle
        self._lifecycle[pamqp.commands.Connection.Start] = frame
        assert "PLAIN" in frame.mechanisms
        self._frame_writer.send_frame(
            pamqp.commands.Connection.StartOk(
                client_properties={
                    "platform": "%s %s (%s build %s)"
                    % (
                        platform.python_implementation(),
                        platform.python_version(),
                        *platform.python_build(),
                    ),
                    "product": "carehare",
                    "capabilities": {
                        "authentication_failure_close": True,
                        "publisher_confirms": True,
                    },
                    "information": "See https://github.com/cjworkbench/carehare",
                },
                mechanism="PLAIN",
                response=f"\x00{self._username}\x00{self._password}",
            ),
        )

    @_accept_handshake_frame.register  # type: ignore [no-redef]
    def _(self, frame: pamqp.commands.Connection.Tune) -> None:
        assert pamqp.commands.Connection.Start in self._lifecycle
        assert pamqp.commands.Connection.Tune not in self._lifecycle
        self._lifecycle[pamqp.commands.Connection.Tune] = frame
        self._frame_writer.send_frames(
            [
                pamqp.commands.Connection.TuneOk(
                    channel_max=frame.channel_max,
                    frame_max=frame.frame_max,
                    heartbeat=frame.heartbeat,
                ),
                pamqp.commands.Connection.Open(virtual_host=self._virtual_host),
            ]
        )
        self._heartbeat_sender = _heartbeat.HeartbeatSender(
            self._transport, frame.heartbeat
        )
        self._channel_id_store: ChannelIdStore = ChannelIdStore(frame.channel_max)

    @_accept_handshake_frame.register  # type: ignore [no-redef]
    def _(self, frame: pamqp.commands.Connection.OpenOk) -> None:
        assert pamqp.commands.Connection.Tune in self._lifecycle
        assert pamqp.commands.Connection.OpenOk not in self._lifecycle
        self._heartbeat_monitor = _heartbeat.HeartbeatMonitor(
            cast(
                pamqp.commands.Connection.Tune,
                self._lifecycle[pamqp.commands.Connection.Tune],
            ).heartbeat,
            on_dead=self._handle_heartbeat_monitor_dead,
        )
        self.open.set_result(None)
        self.closed: asyncio.Future[None] = asyncio.Future()

    @_accept_handshake_frame.register  # type: ignore [no-redef]
    def _(self, frame: pamqp.commands.Connection.Close) -> None:
        self._close_frame = frame

        if pamqp.commands.Connection.Tune in self._lifecycle:
            self._frame_writer.send_frame(pamqp.commands.Connection.CloseOk())
            self._transport.close()
        else:
            # ref: 2.2.4
            # "There is no hand-shaking for errors on connections that are not fully open"
            self._transport.abort()

        # Let `connection_lost()` complete self.open|self.closed.

    def _handle_heartbeat_monitor_dead(self):
        self._crash_exc = ConnectionClosedByHeartbeatMonitor()
        self._transport.abort()

    def send_close_if_allowed(self, reply_code: int = 0, reply_text: str = "") -> None:
        if not self.open.done():
            raise RuntimeError("Cannot send Close frame before opening.")

        if not self._closing and not self.closed.done():
            self._closing = True
            self._frame_writer.send_frame(
                pamqp.commands.Connection.Close(
                    reply_code=reply_code,
                    reply_text=reply_text,
                    class_id=0,
                    method_id=0,
                ),
            )

    def rpc(self, frame: pamqp.base.Frame) -> asyncio.Future[None]:
        """Call a method remotely, with no return value.

        This pattern is useful for, say, queue.declare and such. The steps:

            1. Allocate a channel ID.
            2. Send "Open channel" + [frame] + "Close channel".
            3. Listen for the server response. (A Close means, "Exception".
               A Close-Ok means, "Success".)
            4. Release the channel ID.

        We return the Future that is set by the server response.

        Raise pamqp.exceptions.Exception if the server responds with an error.
        """
        channel_id = self._channel_id_store.acquire()
        channel = RpcChannel(
            frame,
            frame_writer=FrameWriter(self._transport, channel_id),
        )
        self._channels[channel_id] = channel
        self._closing_channels[channel_id] = None  # RPC channels close during init
        return channel.done

    def acking_consumer(
        self, queue_name: str, *, prefetch_size: int, prefetch_count: int
    ) -> ConsumeChannel:
        def on_closing():
            self._closing_channels[channel_id] = None

        channel_id = self._channel_id_store.acquire()
        channel = ConsumeChannel(
            frame_writer=FrameWriter(
                self._transport, channel_id, on_closing=on_closing
            ),
            queue_name=queue_name,
            prefetch_size=prefetch_size,
            prefetch_count=prefetch_count,
        )
        self._channels[channel_id] = channel
        return channel

    def _get_exchange_channel(self, exchange_name: str) -> ExchangeChannel:
        if exchange_name not in self._exchange_channels:
            channel_id = self._channel_id_store.acquire()
            channel = ExchangeChannel(
                exchange_name,
                frame_writer=FrameWriter(self._transport, channel_id),
            )
            self._channels[channel_id] = channel
            self._exchange_channels[exchange_name] = channel
        return self._exchange_channels[exchange_name]

    def publish(
        self, message: bytes, *, exchange_name: str, routing_key: str
    ) -> asyncio.Future[None]:
        exchange_channel = self._get_exchange_channel(exchange_name)
        return exchange_channel.publish(message, routing_key=routing_key)
