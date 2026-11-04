"""Real socket lifecycle tests for sequential isolated browser-test servers."""

import importlib.util
import socket
import sys
import unittest
from contextlib import closing
from pathlib import Path

path = Path(__file__).resolve().parents[2] / "scripts/serve_browser_tests.py"
spec = importlib.util.spec_from_file_location("browser_servers", path)
browser_servers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(browser_servers)


class BrowserPortTests(unittest.TestCase):
    def test_live_listener_is_rejected(self):
        with socket.socket() as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            with self.assertRaises(OSError):
                browser_servers.require_free_ports((listener.getsockname()[1],))
            # The probe must not stop or take over the existing service.
            with socket.create_connection(listener.getsockname(), timeout=2):
                connection, _ = listener.accept()
                connection.close()

    def test_closed_connection_in_time_wait_does_not_block_next_suite(self):
        with socket.socket() as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            address = listener.getsockname()
            with socket.create_connection(address, timeout=2) as client:
                connection, _ = listener.accept()
                with closing(connection):
                    # Make the server the active TCP closer so its local port
                    # enters TIME_WAIT, exactly as a stopped HTTP server can.
                    connection.shutdown(socket.SHUT_WR)
                    self.assertEqual(client.recv(1), b"")
        if sys.platform == "linux":
            with socket.socket() as old_probe:
                with self.assertRaises(OSError):
                    old_probe.bind(address)
        browser_servers.require_free_ports((address[1],))
