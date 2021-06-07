v1.0.0 - 2021-06-07
~~~~~~~~~~~~~~~~~~~

* Support non-default vhosts. (Before, there was a "/" too many.) [#2]
  This is a major-version bump.
* Warn (and choose default vhost) if users end their amqp:// URLs with "/".

v0.0.11 - 2021-05-14
~~~~~~~~~~~~~~~~~~~~

* `Connection.publish()`: raise `ConnectionClosed` instead of stalling when the
  connection has been closed before `publish()` was called.

v0.0.10 - 2021-03-04
~~~~~~~~~~~~~~~~~~~~

* Nix assertion that fails with uvloop
* Fix send and receive of zero-length message

v0.0.9 - 2021-03-04
~~~~~~~~~~~~~~~~~~~

No changes

v0.0.8 - 2021-02-28
~~~~~~~~~~~~~~~~~~~

* Publish large messages in `frame_max`-sized chunks

v0.0.7 - 2021-02-26
~~~~~~~~~~~~~~~~~~~

* Add debug logging to heartbeat monitor.

v0.0.6 - 2021-02-25
~~~~~~~~~~~~~~~~~~~

* Nix errant `print()`.

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
