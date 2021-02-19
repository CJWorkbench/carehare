import asyncio
from typing import Callable

import pamqp.heartbeat

_HEARTBEAT_BYTES = pamqp.heartbeat.Heartbeat.marshal()

# The docs at https://www.rabbitmq.com/heartbeats.html are _really_
# confusing, because they bring up the term "heartbeat interval" which
# is used nowhere other than in the heartbeats.html file itself -- _and_
# all the RabbitMQ discussion-forum questions and issue reports that
# relate to the term in heartbeats.html.
#
# Here's the gist:
# * The server will send 2 packets per `heartbeat` seconds.
# * We, when receiving, will check every `heartbeat` seconds whether there
#   has been traffic in the last `heartbeat` seconds. If not, we die.
#   (This is what the RabbitMQ server does.)


class HeartbeatSender:
    """Periodically send heartbeat frames over `transport`.

    Calling convention:

    The caller should instantiate HeartbeatSender; it will then write to
    `transport` periodically. (This is incompatible with asyncio's "write
    flow control".)

    Call `cancel()` to clean up.
    """

    def __init__(self, transport: asyncio.WriteTransport, heartbeat: int):
        self._transport = transport
        self._heartbeat = heartbeat
        self._loop = asyncio.get_running_loop()
        self._t0 = self._loop.time()
        self._n = 1
        self._timer = self._loop.call_at(self._t0 + heartbeat / 2, self._beat)

    def _beat(self):
        """Must be called by self._timer."""
        self._transport.write(_HEARTBEAT_BYTES)
        self._n += 1
        self._timer = self._loop.call_at(
            self._t0 + self._heartbeat * self._n / 2, self._beat
        )

    def cancel(self):
        self._timer.cancel()
        del self._timer


class HeartbeatMonitor:
    """Call `on_dead()` if we have not received a frame in too long.

    From the spec:

        4.2.7 Heartbeat Frames:

        If a peer detects no incoming traffic (i.e. received octets) for two
        heartbeat intervals or longer, it should close the connection without
        following the Connection.Close/Close-Ok handshaking, and log an error.

    Calling convention:

    The Protocol should start a HeartbeatMonitor and call `monitor.reset()`
    whenever it receives a packet. The HeartBeatMonitor will call `on_dead()`
    if the connection is dropped.

    Call `cancel()` to clean up. (This will _not_ call `on_dead()`.)
    """

    def __init__(self, heartbeat: int, on_dead: Callable[[], None]):
        self._heartbeat = heartbeat
        self._on_dead = on_dead
        self._loop = asyncio.get_running_loop()
        self._t0 = self._loop.time()
        self._saw_data_since_last_beat = True
        self._n = 1
        self._timer = self._loop.call_at(self._t0 + heartbeat, self._beat)

    def _beat(self):
        """Must be called by self._timer."""
        if self._saw_data_since_last_beat:
            self._saw_data_since_last_beat = False
            self._n += 1
            self._timer = self._loop.call_at(
                self._t0 + self._heartbeat * self._n, self._beat
            )
        else:
            self._on_dead()

    def reset(self):
        self._saw_data_since_last_beat = True

    def cancel(self):
        self._timer.cancel()
        del self._timer
