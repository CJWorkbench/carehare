import asyncio
import ssl
from functools import partial
from pathlib import Path

import pytest

import carehare
from carehare._protocol import Protocol

HOST = "localhost"
PORT = 5671
USERNAME = "guest"
PASSWORD = "guest"
VIRTUAL_HOST = "/"
SSL_CONTEXT = ssl.create_default_context(
    cafile=str(Path(__file__).parent.parent / "test-server" / "server.cert")
)
SSL_CONTEXT.load_cert_chain(
    certfile=str(Path(__file__).parent.parent / "test-server" / "client.certchain"),
    keyfile=str(Path(__file__).parent.parent / "test-server" / "client.key"),
)


def ASYNC_TEST(fn):
    return pytest.mark.timeout(10)(pytest.mark.asyncio(fn))


@ASYNC_TEST
async def test_connect():
    transport, protocol = await asyncio.get_running_loop().create_connection(
        protocol_factory=partial(
            Protocol,
            username=USERNAME,
            password=PASSWORD,
            virtual_host=VIRTUAL_HOST,
        ),
        host=HOST,
        port=PORT,
        ssl=SSL_CONTEXT,
    )
    await protocol.open
    protocol.send_close_if_allowed()
    await protocol.closed


@ASYNC_TEST
async def test_connect_wrong_password():
    transport, protocol = await asyncio.get_running_loop().create_connection(
        protocol_factory=partial(
            Protocol,
            username=USERNAME,
            password="wrong",
            virtual_host=VIRTUAL_HOST,
        ),
        host=HOST,
        port=PORT,
        ssl=SSL_CONTEXT,
    )
    with pytest.raises(carehare.ConnectionClosedByServer) as cm:
        await protocol.open

    assert "403 ACCESS_REFUSED" in str(cm.value)


@ASYNC_TEST
async def test_connect_wrong_virtualhost():
    transport, protocol = await asyncio.get_running_loop().create_connection(
        protocol_factory=partial(
            Protocol,
            username=USERNAME,
            password=PASSWORD,
            virtual_host="/wrong",
        ),
        host=HOST,
        port=PORT,
        ssl=SSL_CONTEXT,
    )
    with pytest.raises(carehare.ConnectionClosedByServer) as cm:
        await protocol.open

    assert "530 NOT_ALLOWED" in str(cm.value)


@ASYNC_TEST
async def test_heartbeat_monitor():
    transport, protocol = await asyncio.get_running_loop().create_connection(
        protocol_factory=partial(
            Protocol,
            username=USERNAME,
            password=PASSWORD,
            virtual_host=VIRTUAL_HOST,
        ),
        host=HOST,
        port=PORT,
        ssl=SSL_CONTEXT,
    )
    await protocol.open

    transport.pause_reading()
    with pytest.raises(carehare.ConnectionClosedByHeartbeatMonitor):
        await protocol.closed


@ASYNC_TEST
async def test_heartbeat_sender():
    transport, protocol = await asyncio.get_running_loop().create_connection(
        protocol_factory=partial(
            Protocol,
            username=USERNAME,
            password=PASSWORD,
            virtual_host=VIRTUAL_HOST,
        ),
        host=HOST,
        port=PORT,
        ssl=SSL_CONTEXT,
    )
    await protocol.open

    # assume server asked for heartbeat=1. So if the connection is still
    # open, that's because we're sending heartbeats.
    await asyncio.sleep(2)

    protocol.send_close_if_allowed()
    await protocol.closed


@ASYNC_TEST
async def test_crash():
    transport, protocol = await asyncio.get_running_loop().create_connection(
        protocol_factory=partial(
            Protocol,
            username=USERNAME,
            password=PASSWORD,
            virtual_host=VIRTUAL_HOST,
        ),
        host=HOST,
        port=PORT,
        ssl=SSL_CONTEXT,
    )
    await protocol.open
    protocol.data_received(b"\x00\x00\x00\x00\x00\x00\x00\x00Fake RabbitMQ killed me")
    with pytest.raises(carehare.BadBytesFromServer):
        await protocol.closed
