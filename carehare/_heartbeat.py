import asyncio
from typing import Callable

import pamqp.heartbeat

_HEARTBEAT_BYTES = pamqp.heartbeat.Heartbeat.marshal()


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
        self._n = 1
        self._n_silent_intervals = 0
        self._timer = self._loop.call_at(self._t0 + heartbeat / 2, self._beat)

    def _beat(self):
        """Must be called by self._timer."""
        self._n += 1
        self._n_silent_intervals += 1

        if self._n_silent_intervals >= 3:
            self._on_dead()
        else:
            self._timer = self._loop.call_at(
                self._t0 + self._heartbeat * self._n / 2, self._beat
            )

    def reset(self):
        self._n_silent_intervals = 0

    def cancel(self):
        self._timer.cancel()
        del self._timer
