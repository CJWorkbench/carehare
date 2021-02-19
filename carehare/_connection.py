from __future__ import annotations

import asyncio
import ssl
from functools import partial
from typing import Optional, Union, cast
from urllib.parse import urlparse

import pamqp.commands
import pamqp.common

from ._consume_channel import ConsumeChannel
from ._protocol import Protocol


class Connection:
    def __init__(
        self,
        url: str,
        *,
        ssl: Union[bool, ssl.SSLContext, None] = None,
        connect_timeout: Optional[float] = None,
    ):
        self._url = url
        self._ssl = ssl
        self._connect_timeout = connect_timeout

    async def connect(self) -> None:
        """Alternative to `async with` syntax.

        Return if we are connected. Raise if connect fails.

        Do not call this twice on one connection.
        """
        url = urlparse(self._url)
        if url.scheme not in {"amqp", "amqps"}:
            raise ValueError(
                "url must start with 'amqp://' or 'amqps://'; got: %r" % self._url
            )

        ssl = self._ssl
        if ssl is None:
            ssl = url.scheme == "amqps"

        addr = url.netloc.split("@")[-1].split(":")
        if len(addr) == 1:
            host = addr[0]
            port = {"amqp": 5672, "amqps": 5671}[url.scheme]
        else:
            host = addr[0]
            port = int(addr[1])

        transport, protocol = await asyncio.wait_for(
            asyncio.get_running_loop().create_connection(
                protocol_factory=partial(
                    Protocol,
                    username=url.username,
                    password=url.password,
                    virtual_host=url.path,
                ),
                host=host,
                port=port,
                ssl=ssl,
            ),
            timeout=self._connect_timeout,
        )
        self._protocol = cast(Protocol, protocol)
        await self._protocol.open

    async def __aenter__(self):
        await self.connect()
        return self

    @property
    def closed(self) -> asyncio.Future[None]:
        """Future that resolves when we are closed.

        If closing fails, this Future will have an exception.
        """
        return self._protocol.closed

    async def close(self):
        """Alternative to `async with` syntax.

        You may call this multiple times on a single connection.
        """
        self._protocol.send_close_if_allowed()
        await self.closed

    async def __aexit__(self, exc_type, exc_value, traceback):
        await self.close()  # or raise an exception atop the original exception

    def acking_consumer(
        self, queue_name: str, *, prefetch_size: int = 0, prefetch_count: int = 1
    ) -> ConsumeChannel:
        """Consume messages asynchronously.

        Usage:

            async with connection.acking_consumer("my-queue") as consumer:
                async for message in consumer:
                    print("hi! %r" % message)

        After the inner block completes, the consumer will ack the message.

        If your inner block raises an exception, the message will _not_ be
        acked. Once the outer block exits, RabbitMQ may deliver the message
        to another consumer.

        You may call `consumer.close()` to stop the flow of messages in the
        `async for` loop. You probably shouldn't call it from _within_ the
        `async for` loop because a low-traffic queue won't yield to your code
        in a timely manner.

        `prefetch_size` and `prefetch_count` hint to RabbitMQ how much of a
        backlog should be on this queue. Smaller numbers are "fairer" because a
        slow consumer won't hold on to many messages. Larger numbers are
        "faster" because messages will be available locally before your acks
        reach the server.
        """
        return self._protocol.acking_consumer(
            queue_name=queue_name,
            prefetch_size=prefetch_size,
            prefetch_count=prefetch_count,
        )

    def publish(
        self, message: bytes, *, exchange_name: str = "", routing_key: str = ""
    ) -> asyncio.Future[None]:
        return self._protocol.publish(
            message, exchange_name=exchange_name, routing_key=routing_key
        )

    def exchange_declare(
        self,
        exchange_name: str,
        *,
        exchange_type: str = "direct",
        passive: bool = False,
        durable: bool = False,
        auto_delete: bool = False,
        internal: bool = False,
        arguments: pamqp.common.Arguments = None,
    ) -> asyncio.Future[None]:
        return self._protocol.rpc(
            pamqp.commands.Exchange.Declare(
                exchange=exchange_name,
                exchange_type=exchange_type,
                passive=passive,
                durable=durable,
                auto_delete=auto_delete,
                internal=internal,
                nowait=True,
                arguments=arguments,
            )
        )

    def queue_bind(
        self,
        queue_name: str,
        exchange_name: str,
        *,
        routing_key: str = "",
        arguments: pamqp.common.Arguments = None,
    ) -> asyncio.Future[None]:
        return self._protocol.rpc(
            pamqp.commands.Queue.Bind(
                queue=queue_name,
                exchange=exchange_name,
                routing_key=routing_key,
                nowait=True,
                arguments=arguments,
            )
        )

    def queue_declare(
        self,
        queue_name: str,
        *,
        passive: bool = False,
        durable: bool = False,
        exclusive: bool = False,
        auto_delete: bool = False,
        arguments: pamqp.common.Arguments = None,
    ) -> asyncio.Future[None]:
        return self._protocol.rpc(
            pamqp.commands.Queue.Declare(
                queue=queue_name,
                passive=passive,
                durable=durable,
                exclusive=exclusive,
                auto_delete=auto_delete,
                nowait=True,
                arguments=arguments,
            )
        )


def connect(
    url: str,
    *,
    ssl: Union[bool, ssl.SSLContext, None] = None,
    connect_timeout: Optional[float] = None,
) -> Connection:
    return Connection(url, ssl=ssl, connect_timeout=connect_timeout)
