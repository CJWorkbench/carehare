carehare
========

Asyncio RabbitMQ client that handles all the edge cases.

Installation
------------

``pip install carehare``

Usage
-----

Consumer (``async for``)::

    try:
        async with carehare.connect("amqps://guest:guest@localhost/") as connection:
            try:
                await connection.queue_declare("my-queue", exclusive=True)
                async with connection.acking_consumer("my-queue") as consumer:
                    async for message in consumer:
                        print(repr(message))
                        # ... if we raise an exception here, we won't ack.
                        #
                        # ... if we `break` from this loop, we won't ack.
                        #
                        # Call `consumer.close()` before (or instead of) `break`
                        # to abort iteration.
            except carehare.ChannelClosedByServer:
                logger.info("RabbitMQ told this one consumer to go away")
            except carehare.ConnectionClosed:
                # Either RabbitMQ is telling us an error (and the outer context
                # manager will throw it), or we called connection.close()
                # ourselves (so we want to close).
                pass
    except carehare.ConnectionClosedByServer:
        # str(error) will give the RabbitMQ error message
        logger.error("RabbitMQ closed our connection")
    except carehare.ConnectionClosedByHeartbeatMonitor:
        logger.error("RabbitMQ went away")

Consumer (``next_delivery``)::

    try:
        async with carehare.connect("amqps://guest:guest@localhost/") as connection:
            try:
                await connection.queue_declare("my-queue", exclusive=True)
                async with connection.acking_consumer("my-queue") as consumer:
                    while True:
                        message, delivery_tag = await consumer.next_delivery()
                        # You must ack() (with no await). If RabbitMQ doesn't
                        # receive this ack, it may deliver the same message to
                        # another client.
                        consumer.ack(delivery_tag)
                        if message.startswith(b"okay, go away now"):
                            break
            except carehare.ChannelClosedByServer:
                logger.info("RabbitMQ told this one consumer to go away")
            except carehare.ConnectionClosed:
                # Either RabbitMQ is telling us an error (and the outer context
                # manager will throw it), or we called connection.close()
                # ourselves (so we want to close).
                pass
    except carehare.ConnectionClosedByServer:
        # str(error) will give the RabbitMQ error message
        logger.error("RabbitMQ closed our connection")
    except carehare.ConnectionClosedByHeartbeatMonitor:
        logger.error("RabbitMQ went away")

Publisher::

    try:
        async with carehare.connect("amqps://guest:guest@localhost/") as connection:
            try:
                await connection.publish(b"Hello, world!", routing_key="my-queue")
            except carehare.ServerSentNack:
                logger.warn("Failed to publish message")
            except carehare.ChannelClosedByServer:
                # str(err) will give the RabbitMQ error message -- for instance,
                # "404 NOT_FOUND" if the exchange does not exist
                logger.error("Problem with the exchange")
    except carehare.ConnectionClosedByServer:
        # str(error) will give the RabbitMQ error message
        logger.error("RabbitMQ closed our connection")
    except carehare.ConnectionClosedByHeartbeatMonitor:
        logger.error("RabbitMQ went away")

Design decisions
----------------

``carehare`` is designed to turn RabbitMQ's asynchronous error system into
_understandable_ Python exceptions.

Channels
~~~~~~~~

Carehare doesn't let you control RabbitMQ Channels. They aren't Pythonic. (In
RabbitMQ, an exception on a channel closes the channel -- and cancels all its
pending operations.)

Instead, carehare uses channels to handle errors. For instance, Queue.Declare
costs three operations: Channel.Open, Queue.Declare, Channel.Close. Since the
operation has its own channel, it won't interfere with other operations if it
causes an exception.

There's a speed-up for publishing: we lazily open a Channel per *exchange*.
Error codes like "not found", "access refused" and "not implemented" will make
carehare raise an exception on all pending publishes on the same exchange. Don't
worry: a normal "Nack" ("message wasn't delivered") will only make your single
message fail.

Exceptions
~~~~~~~~~~

"Exceptions" are hardly exceptional: as a programmer, they are your job. These
ones are designed to help you solve them.

Connection methods return ``asyncio.Future`` objects. You must await each one
and handle its errors.

Even though you're using Python async context managers, exceptions can't
happen *everywhere*. Carehare will only raise when you ``await`` a response
from RabbitMQ. 

In particular, ``consumer.ack()`` will never raise! You must call it from the
main event loop, but you won't await it.

To code safely, catch these exceptions religiously:

* ``carehare.ChannelClosedByServer``: RabbitMQ did not like the command you
  just ran. Read the exception message for details. After you receive this
  message, you may continue using the RabbitMQ connection.
* ``carehare.ConnectionClosed``: When the connection shuts down, every pending
  ``Future`` will raise this. Only the actual ``Connection`` context manager
  will raise the underlying exception: a ``carehare.ConnectionClosedByServer``
  with a descriptive error message.

Carehare won't raise ``asyncio.Cancelled``.

Back-pressure
~~~~~~~~~~~~~

The core logic is synchronous. It's simpler to reason about. The downside:
neither RabbitMQ nor users will wait for buffers to empty before sending more
data.

Use application-level logic to make sure you don't run out of memory:

* Consuming? Don't worry. Use ``prefetch_count`` to limit the number of messages
  RabbitMQ sends. Always ack: carehare won't permit ``no-ack``.
* Publishing? Carehare forces "publisher confirms", so each publish returns a
  ``Future``. Your application is responsible for not calling publish() too many
  times simultaneously. Use an ``asyncio.Semaphore`` or reason about your
  specific use (for instance, "my server will host max 100 clients, and each
  client can only publish one message at a time").

Comparison to other async RabbitMQ clients
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Other clients tend to try and achieve "RabbitMQ in Python". They fail when it
comes to exceptions:

* ``aiormq``: If your code generates an error during consume, aiormq (4.1.1)
  will catch it and ignore it -- stalling your program.
* ``aioamqp``: If your connection produces an unexpected error, aioamqp will
  catch it and ignore it -- stalling your program. Also, the latest release was
  in 2019.

This author believes it's too confusing to model RabbitMQ's API in Python.
Instead, carehare models your *intent* in Python.

Dependencies
------------

You'll need Python 3.8+ and a RabbitMQ server.

If you have Docker, here's how to start a development server::

    test-server/prepare-certs.sh  # Create SSL certificates used in tests
    docker run --rm -it \
         -p 5671:5671 \
         -p 5672:5672 \
         -p 15672:15672 \
         -v "/$(pwd)"/test-server:/test-server \
         -e RABBITMQ_SSL_CACERTFILE=/test-server/ca.cert \
         -e RABBITMQ_SSL_CERTFILE=/test-server/server.cert \
         -e RABBITMQ_SSL_KEYFILE=/test-server/server.key \
         -e RABBITMQ_SSL_VERIFY=verify_peer \
         -e RABBITMQ_SSL_FAIL_IF_NO_PEER_CERT=true \
         -e RABBITMQ_CONFIG_FILE=/test-server/rabbitmq \
         rabbitmq:3.8.11-management-alpine

During testing, see the RabbitMQ management interface at http://localhost:15672.

Contributing
------------

To add features and fix bugs
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

First, start a development RabbitMQ server (see above).

Now take on the development cycle:

#. ``tox`` # to ensure tests pass.
#. Write new tests in ``tests/`` and make sure they fail.
#. Write new code in ``carehare/`` to make the tests pass.
#. Submit a pull request.

To deploy
~~~~~~~~~

Use `semver <https://semver.org/>`_.

#. ``git push`` and make sure Travis tests all pass.
#. ``git tag vX.X.X``
#. ``git push --tags``

TravisCI will push to PyPi.
