import asyncio
import ssl

import pytest

import carehare
from tests.util import ASYNC_TEST, SSL_CONTEXT, URL


@ASYNC_TEST
async def test_connect_invalid_scheme():
    with pytest.raises(ValueError) as cm:
        async with carehare.connect(
            URL.replace("amqps://", "http://"), ssl=SSL_CONTEXT
        ):
            pass
    assert "amqps://" in str(cm.value)


@ASYNC_TEST
async def test_connect_invalid_password():
    with pytest.raises(carehare.ConnectionClosedByServer) as cm:
        async with carehare.connect(URL.replace("guest", "wrong"), ssl=SSL_CONTEXT):
            pass
    assert cm.value.reply_code == 403
    assert "403 ACCESS_REFUSED" in str(cm.value)


@ASYNC_TEST
async def test_connect_ssl_error():
    with pytest.raises(ssl.SSLCertVerificationError):
        async with carehare.connect(URL.replace("guest", "wrong")):
            pass


@ASYNC_TEST
async def test_connect_vhost():
    async with carehare.connect(URL + "/myvhost", ssl=SSL_CONTEXT):
        pass


@ASYNC_TEST
async def test_connect_warn_on_empty_vhost(caplog):
    with pytest.warns(DeprecationWarning) as record:
        async with carehare.connect(URL + "/", ssl=SSL_CONTEXT):
            pass
    assert record[0].message.args[0] == (
        'Your RabbitMQ URL ends with a slash, which implies vhost "". This is, surprisingly, an error. carehare is interpreting this to mean "default vhost". To avoid this warning, remove the "/" from the end of your URL.'
    )


@ASYNC_TEST
async def test_value_error_on_invalid_vhost(caplog):
    with pytest.raises(ValueError):
        async with carehare.connect(URL + "/myvhost/", ssl=SSL_CONTEXT):
            pass


@ASYNC_TEST
async def test_connect_port():
    async with carehare.connect(
        URL.replace("localhost", "localhost:5671"), ssl=SSL_CONTEXT
    ):
        pass


@ASYNC_TEST
async def test_connect_warn_amqp_should_be_amqps():
    with pytest.raises(ValueError) as cm:
        async with carehare.connect(
            URL.replace("amqps://", "amqp://"), ssl=SSL_CONTEXT
        ):
            pass
    assert "you must not provide `ssl`" in str(cm.value)


@ASYNC_TEST
async def test_close_when_rabbitmq_closes_with_error():
    with pytest.raises(carehare.ConnectionClosedByServer) as cm:
        async with carehare.connect(URL, ssl=SSL_CONTEXT) as connection:
            connection._protocol._transport.write(
                b"\x00\x00\x00\x00\x00\x00\x00\x00hi! I'm not AMQP. You can crash now."
            )
            await asyncio.sleep(1)
    assert "501 FRAME_ERROR" in str(cm.value)


@ASYNC_TEST
async def test_connect_timeout():
    with pytest.raises(asyncio.TimeoutError):
        async with carehare.connect(URL, ssl=SSL_CONTEXT, connect_timeout=0.000000001):
            pass


@ASYNC_TEST
async def test_connect_manually():
    connection = carehare.Connection(url=URL, ssl=SSL_CONTEXT)
    await connection.connect()
    await connection.close()
    await connection.closed  # wait doubly -- to test the property is correct
