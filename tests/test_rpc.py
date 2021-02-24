import pytest

import carehare
from tests.util import ASYNC_TEST, SSL_CONTEXT, URL


@ASYNC_TEST
async def test_queue_declare(connection):
    await connection.queue_declare("hi", exclusive=True)


@ASYNC_TEST
async def test_queue_declare_not_ok(connection):
    await connection.queue_declare("conflict", exclusive=True)

    async with carehare.connect(URL, ssl=SSL_CONTEXT) as connection2:
        with pytest.raises(carehare.ChannelClosedByServer) as cm:
            await connection2.queue_declare("conflict", exclusive=True)
        assert cm.value.reply_code == 405
        assert "405 RESOURCE_LOCKED" in str(cm.value)


@ASYNC_TEST
async def test_multiple_rpcs(connection):
    # We reuse channel IDs
    await connection.queue_declare("queue1", exclusive=True)
    await connection.queue_declare("queue2", exclusive=True)


@ASYNC_TEST
async def test_queue_bind_unbind(connection):
    await connection.exchange_declare("bind-test")
    await connection.queue_declare("queue1", exclusive=True)
    await connection.queue_bind("queue1", "bind-test", routing_key="hi")
    await connection.queue_unbind("queue1", "bind-test", routing_key="hi")


@ASYNC_TEST
async def test_queue_declare_connection_closed(connection):
    future = connection.queue_declare("queue", exclusive=True)
    await connection.close()
    with pytest.raises(carehare.ConnectionClosed):
        await future
