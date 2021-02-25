v0.0.5 - 2021-02-25
~~~~~~~~~~~~~~~~~~~

* Raise `ValueError` if user asks for SSL "amqp://" or non-SSL "amqps://".
  This conforms with the [URI spec](https://www.rabbitmq.com/uri-spec.html).

v0.0.4 - 2021-02-24
~~~~~~~~~~~~~~~~~~~

* Add `connection.queue_unbind()`

v0.0.3 - 2021-02-21
~~~~~~~~~~~~~~~~~~~

* Fix heartbeat-monitoring logic to avoid disconnect when beats happen at the
  exact wrong times.

v0.0.2 - 2021-02-19
~~~~~~~~~~~~~~~~~~~

* Add `connection.connect()` and `connection.closed`, for users who want to
  skip the async context manager.

v0.0.1 - 2021-02-18
~~~~~~~~~~~~~~~~~~~

* Initial release
