from typing import Iterator, List


class ChannelIdStore:
    """Place to organize channel IDs.

    Callers should acquire() from here to find an unused channel ID. They
    should release() any channel ID that is no longer used, so that acquire()
    doesn't run out of options.
    """

    def __init__(self, channel_max: int):
        self._new: Iterator[int] = iter(range(1, channel_max))
        self._recycled: List[int] = []

    def acquire(self) -> int:
        if self._recycled:
            return self._recycled.pop()
        else:
            return next(self._new)

    def release(self, channel_id: int) -> None:
        self._recycled.append(channel_id)
