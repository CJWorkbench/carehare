import ssl
from pathlib import Path

import pytest


def ASYNC_TEST(fn):
    return pytest.mark.timeout(5)(pytest.mark.asyncio(fn))


SSL_CONTEXT = ssl.create_default_context(
    cafile=str(Path(__file__).parent.parent / "test-server" / "server.cert")
)
SSL_CONTEXT.load_cert_chain(
    certfile=str(Path(__file__).parent.parent / "test-server" / "client.certchain"),
    keyfile=str(Path(__file__).parent.parent / "test-server" / "client.key"),
)

URL = "amqps://guest:guest@localhost"
