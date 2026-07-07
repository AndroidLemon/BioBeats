# Tests for the OSCServer class: protocol conformance, dispatch routing, and socket release.

import socket
import threading
import time

from src.integrations.osc_server import OSCServer, OSCServerProtocol


def test_real_server_conforms_to_protocol():
    # Pass port=0 to bind to an ephemeral port without colliding.
    server = OSCServer(host="127.0.0.1", port=0)
    assert isinstance(server, OSCServerProtocol)
    # Clean up the socket directly since we didn't call serve()
    server._server.server_close()


def test_osc_server_releases_socket_on_shutdown():
    # Bind server to ephemeral port
    server = OSCServer(host="127.0.0.1", port=0)
    host, port = server._server.server_address

    # Serve in a background thread
    t = threading.Thread(target=server.serve)
    t.start()
    time.sleep(0.2)  # let it startup

    # Stop the server
    server.shutdown()
    t.join(timeout=2.0)

    # Now verify the port is bindable.
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind((host, port))
    finally:
        sock.close()
