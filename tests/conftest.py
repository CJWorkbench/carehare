import pytest

from carehare import connect
from tests.util import SSL_CONTEXT, URL


@pytest.fixture
async def connection():
    async with connect(URL, ssl=SSL_CONTEXT) as connection:
        yield connection
