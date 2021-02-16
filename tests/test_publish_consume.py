import asyncio

import pytest

import carehare
from tests.util import ASYNC_TEST


@ASYNC_TEST
async def test_publish_to_missing_exchange(connection):
    with pytest.raises(carehare.ChannelClosedByServer) as cm:
        await connection.publish(b"foo", exchange_name="missing-exchange")
    assert "404 NOT_FOUND" in str(cm.value)


@ASYNC_TEST
async def test_publish_and_consume(connection):
    await connection.queue_declare("messages", exclusive=True)

    await connection.publish(b"foo", routing_key="messages")
    await connection.publish(b"bar", routing_key="messages")

    async with connection.acking_consumer("messages") as consumer:
        iterator = consumer.__aiter__()
        assert await iterator.__anext__() == b"foo"
        assert await iterator.__anext__() == b"bar"
        consumer.close()
        with pytest.raises(StopAsyncIteration):
            await iterator.__anext__()


@ASYNC_TEST
async def test_publish_in_order(connection):
    await connection.queue_declare("messages", exclusive=True)

    messages = [str(i).encode("ascii") for i in range(100)]

    await asyncio.gather(
        *(connection.publish(message, routing_key="messages") for message in messages)
    )

    async with connection.acking_consumer("messages") as consumer:
        i = 0
        async for message in consumer:
            assert message == str(i).encode("ascii")
            i += 1
            if i == 100:
                consumer.close()


@ASYNC_TEST
async def test_consume_missing_queue(connection):
    with pytest.raises(carehare.ChannelClosedByServer) as cm:
        async with connection.acking_consumer("not-found"):
            pass

    assert "404 NOT_FOUND" in str(cm.value)


@ASYNC_TEST
async def test_consume_connection_closed(connection):
    await connection.queue_declare("messages", exclusive=True)
    with pytest.raises(carehare.ConnectionClosed):
        # Both `consumer.__aexit__()` and `async for` will raise
        async with connection.acking_consumer("messages") as consumer:
            connection._protocol.send_close_if_allowed()
            async for message in consumer:
                pass


@ASYNC_TEST
async def test_consume_close_many_times(connection):
    await connection.queue_declare("messages", exclusive=True)
    async with connection.acking_consumer("messages") as consumer:
        consumer.close()
        consumer.close()
        consumer.close()


@ASYNC_TEST
async def test_consume_close_during_ack(connection):
    await connection.queue_declare("messages", exclusive=True)
    await connection.publish(b"foo", routing_key="messages")
    await connection.publish(b"bar", routing_key="messages")
    async with connection.acking_consumer("messages") as consumer:
        async for message in consumer:
            assert message == b"foo"
            consumer.close()

    async with connection.acking_consumer("messages") as consumer:
        n = 0
        async for message in consumer:
            if n == 0:
                assert message == b"foo"
                n = 1
            elif n == 1:
                assert message == b"bar"
                consumer.close()


@ASYNC_TEST
async def test_publish_connection_closed(connection):
    await connection.queue_declare("messages", exclusive=True)
    future = connection.publish(b"foo", routing_key="messages")
    connection._protocol.send_close_if_allowed()
    with pytest.raises(carehare.ConnectionClosed):
        await future


@ASYNC_TEST
async def test_publish_nack(connection):
    await connection.queue_declare(
        "messages",
        exclusive=True,
        arguments={"x-max-length": 1, "x-overflow": "reject-publish"},
    )
    await connection.publish(b"foo", routing_key="messages")
    with pytest.raises(carehare.ServerSentNack):
        await connection.publish(b"bar", routing_key="messages")


@ASYNC_TEST
async def test_consume_ack(connection):
    await connection.queue_declare(
        "messages",
        exclusive=True,
        arguments={"x-max-length": 1, "x-overflow": "reject-publish"},
    )

    async with connection.acking_consumer("messages") as consumer:
        iterator = consumer.__aiter__()
        await connection.publish(b"foo", routing_key="messages")
        assert await iterator.__anext__() == b"foo"
        task = asyncio.create_task(iterator.__anext__())  # should ack
        await connection.publish(b"bar", routing_key="messages")
        assert await task == b"bar"


@ASYNC_TEST
async def test_publish_on_exchange(connection):
    # tests some RPC methods
    await connection.exchange_declare(exchange_name="groups", exchange_type="direct")
    await connection.queue_declare("foo", exclusive=True)
    await connection.queue_bind("foo", "groups", routing_key="bar")

    await connection.publish(b"bar", exchange_name="groups", routing_key="bar")

    async with connection.acking_consumer("foo") as consumer:
        async for message in consumer:
            assert message == b"bar"
            break

    # leak the exchange. It'll be shared among all tests.
