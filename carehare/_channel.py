from typing import Protocol, Union

import pamqp.base
import pamqp.body
import pamqp.header

from ._exceptions import ConnectionClosed

AcceptableFrame = Union[
    pamqp.base.Frame, pamqp.body.ContentBody, pamqp.header.ContentHeader
]


class Channel(Protocol):
    def accept_frame(self, frame: AcceptableFrame) -> None:
        """Handle a frame from the server.

        You can implement this as a @functools.singledispatchmethod.

        This method will never receive a `pamqp.commands.Channel.Close` or
        `pamqp.commands.Channel.CloseOk`. These are handled by the protocol,
        to handle races pertaining to closing on both ends.
        """
        raise NotImplementedError  # pragma: no cover

    def accept_channel_closed_by_server(self, frame: pamqp.commands.Channel.Close):
        """Handle the fact that this channel is shutting down normally.

        If implementor methods have returned any Futures, this method must
        complete those Futures.

        This is guaranteed to be the last method called by the protocol, and
        it's guaranteed not to be called twice.
        """

    def accept_channel_closed_by_us(self) -> None:
        """Handle the fact that we closed this channel.

        This will only occur if we sent a `Channel.Close` frame ourselves.

        This is guaranteed to be the last method called by the protocol, and
        it's guaranteed not to be called twice.
        """

    def accept_connection_closed(self, exc: ConnectionClosed) -> None:
        """Handle the fact that we're no longer connected to the server.

        If implementor methods have returned any Futures, this method must
        complete those Futures.

        This is guaranteed to be the last method called by the protocol, and
        it's guaranteed not to be called twice.
        """
