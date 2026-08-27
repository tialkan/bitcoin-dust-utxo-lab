#!/usr/bin/env python3
"""A SOCKS5 proxy that maps synthetic public IPs onto local ports.

Why this exists. addrman refuses non-routable addresses
(AddrManImpl::AddSingle), so loopback regtest nodes cannot be placed in
it, and a synthetic routable address has nothing listening behind it.
That blocks any measurement of peer selection.

Giving each node -proxy pointed here closes the gap without touching the
host's network configuration: the node believes it is dialling
51.<n>.0.1, this proxy connects it to 127.0.0.1:(base_port + n).

Addresses are spread one per /16 on purpose. ThreadOpenConnections
allows only one automatic outbound peer per IPv4 /16 netgroup, so
addresses sharing a /16 would collapse into one usable candidate and
dominate the result.
"""

import socket
import socketserver
import struct
import threading


class Handler(socketserver.BaseRequestHandler):
    base_port = 0

    def handle(self):
        sock = self.request
        try:
            # Greeting: VER, NMETHODS, METHODS...
            head = self._recv_exact(sock, 2)
            if not head or head[0] != 0x05:
                return
            self._recv_exact(sock, head[1])
            sock.sendall(b"\x05\x00")  # no authentication

            # Request: VER, CMD, RSV, ATYP
            req = self._recv_exact(sock, 4)
            if not req or req[1] != 0x01:  # CONNECT only
                sock.sendall(b"\x05\x07\x00\x01" + b"\x00" * 6)
                return
            atyp = req[3]
            if atyp == 0x01:
                raw = self._recv_exact(sock, 4)
                dest = socket.inet_ntoa(raw)
            elif atyp == 0x03:
                ln = self._recv_exact(sock, 1)[0]
                dest = self._recv_exact(sock, ln).decode()
            else:
                sock.sendall(b"\x05\x08\x00\x01" + b"\x00" * 6)
                return
            self._recv_exact(sock, 2)  # port, ignored: the mapping decides it

            port = self.map_port(dest)
            if port is None:
                sock.sendall(b"\x05\x04\x00\x01" + b"\x00" * 6)
                return
            try:
                upstream = socket.create_connection(("127.0.0.1", port), timeout=10)
            except OSError:
                sock.sendall(b"\x05\x05\x00\x01" + b"\x00" * 6)
                return
            sock.sendall(b"\x05\x00\x00\x01" + socket.inet_aton("127.0.0.1")
                         + struct.pack(">H", port))
            self._pump(sock, upstream)
        except OSError:
            pass

    @classmethod
    def map_port(cls, dest):
        """51.<n>.0.1 -> base_port + n."""
        parts = dest.split(".")
        if len(parts) != 4 or parts[0] != "51":
            return None
        try:
            return cls.base_port + int(parts[1])
        except ValueError:
            return None

    @staticmethod
    def _recv_exact(sock, n):
        buf = b""
        while len(buf) < n:
            chunk = sock.recv(n - len(buf))
            if not chunk:
                return None
            buf += chunk
        return buf

    @staticmethod
    def _pump(a, b):
        def copy(src, dst):
            try:
                while True:
                    data = src.recv(65536)
                    if not data:
                        break
                    dst.sendall(data)
            except OSError:
                pass
            finally:
                for s in (src, dst):
                    try:
                        s.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
        t = threading.Thread(target=copy, args=(a, b), daemon=True)
        t.start()
        copy(b, a)
        t.join(timeout=5)


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def start(base_port):
    Handler.base_port = base_port
    srv = Server(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]
