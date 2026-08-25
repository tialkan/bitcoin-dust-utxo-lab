#!/usr/bin/env python3
"""Minimal regtest driver for policy experiments.

Starts an isolated bitcoind on regtest with a caller-supplied set of
policy flags, exposes a thin RPC wrapper, and tears the node down
cleanly. Deliberately dependency-free: stdlib only, so a reviewer can
run it without setting up a Python environment.
"""

import base64
import json
import os
import shutil
import signal
import socket
import subprocess
import tempfile
import time
import urllib.request

RPC_USER = "lab"
RPC_PASS = "lab"


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class RegtestNode:
    def __init__(self, bitcoind, extra_args=None, datadir=None):
        self.bitcoind = os.path.abspath(bitcoind)
        self.extra_args = list(extra_args or [])
        self.rpc_port = _free_port()
        self.p2p_port = _free_port()
        self._tmp = datadir is None
        self.datadir = datadir or tempfile.mkdtemp(prefix="regtest-lab-")
        self.proc = None
        self._id = 0

    def start(self, timeout=60):
        args = [
            self.bitcoind,
            "-regtest",
            f"-datadir={self.datadir}",
            f"-rpcport={self.rpc_port}",
            f"-port={self.p2p_port}",
            f"-rpcuser={RPC_USER}",
            f"-rpcpassword={RPC_PASS}",
            "-listen=0",
            "-fallbackfee=0.0002",
            "-server=1",
        ] + self.extra_args
        self.logfile = open(os.path.join(self.datadir, "stdout.log"), "w")
        self.proc = subprocess.Popen(args, stdout=self.logfile, stderr=subprocess.STDOUT)
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"bitcoind exited early:\n{self.tail_log()}")
            try:
                self.rpc("getblockchaininfo")
                return self
            except Exception:
                time.sleep(0.3)
        raise RuntimeError(f"bitcoind did not come up:\n{self.tail_log()}")

    def tail_log(self, n=25):
        for name in ("stdout.log", os.path.join("regtest", "debug.log")):
            path = os.path.join(self.datadir, name)
            if os.path.exists(path):
                with open(path, errors="replace") as fh:
                    lines = fh.readlines()[-n:]
                if lines:
                    return "".join(lines)
        return "(no log)"

    def rpc(self, method, *params):
        self._id += 1
        payload = json.dumps(
            {"jsonrpc": "1.0", "id": str(self._id), "method": method, "params": list(params)}
        ).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.rpc_port}/",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": "Basic "
                + base64.b64encode(f"{RPC_USER}:{RPC_PASS}".encode()).decode(),
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                body = json.load(resp)
        except urllib.error.HTTPError as e:
            # bitcoind returns a JSON-RPC error body with HTTP 500; surface it
            # instead of letting urllib swallow the reason.
            try:
                body = json.load(e)
            except Exception:
                raise
        if body.get("error"):
            raise RPCError(body["error"])
        return body["result"]

    def stop(self):
        if self.proc and self.proc.poll() is None:
            try:
                self.rpc("stop")
                self.proc.wait(timeout=60)
            except Exception:
                self.proc.send_signal(signal.SIGTERM)
                self.proc.wait(timeout=30)
        if getattr(self, "logfile", None):
            self.logfile.close()

    def cleanup(self):
        self.stop()
        if self._tmp and os.path.isdir(self.datadir):
            shutil.rmtree(self.datadir, ignore_errors=True)

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.cleanup()


class RPCError(Exception):
    def __init__(self, err):
        self.code = err.get("code")
        self.message = err.get("message", "")
        super().__init__(f"[{self.code}] {self.message}")
