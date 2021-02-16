import asyncio
import logging
from typing import Callable, List, Optional, Union

import pamqp.body
import pamqp.frame
import pamqp.header

logger = logging.getLogger(__name__)


class FrameWriter:
    def __init__(
        self,
        transport: asyncio.WriteTransport,
        channel_id: int,
        on_closing: Optional[Callable[[], None]] = None,
    ) -> None:
        self._transport = transport
        self._channel_id = channel_id
        self._on_closing = on_closing
        self._closing: bool = False

    def send_close(self):
        if self._closing:
            return

        self.send_frame(
            pamqp.commands.Channel.Close(
                reply_code=0, reply_text="", class_id=0, method_id=0
            )
        )
        self._closing = True
        if self._on_closing is not None:
            self._on_closing()

    def send_frame(
        self,
        frame: Union[
            pamqp.base.Frame, pamqp.body.ContentBody, pamqp.header.ContentHeader
        ],
    ) -> None:
        """Write a single frame to the transport, tagged with our channel_id

        Does not back-pressure.
        """
        if self._closing:
            logger.debug("not sending frame because we are closing: %r", frame)
            return

        logger.debug("send_frame: %r", frame)
        self._transport.write(pamqp.frame.marshal(frame, self._channel_id))

    def send_frames(
        self,
        frames: List[
            Union[pamqp.base.Frame, pamqp.body.ContentBody, pamqp.header.ContentHeader]
        ],
    ) -> None:
        """Write frames to the transport, tagged with our channel_id

        Does not back-pressure.
        """
        logger.debug("send_frames: %r", frames)
        self._transport.write(
            b"".join(pamqp.frame.marshal(frame, self._channel_id) for frame in frames)
        )
