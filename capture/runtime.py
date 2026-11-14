"""Container programs for a bounded synthetic application-log experiment.

The HTTP interface accepts only numbered dummy requests and collector delivery.
Fixture controls run through a separate CLI, never through a request endpoint.
All receipts are fsynced before acknowledgment. Sequential fixture requests make
sender IDs stable and preserve the exact line received by the collector.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.request import Request, urlopen

LOCAL = "records/var/log/records-app/access.log"
COLLECTOR = "collector/collected/collected.log"
MODES = ("complete", "missing-local-record", "benign-gap")


def now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def append(path, data):
    """Durably append bytes before returning to the caller."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def request(url, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    req = Request(url, data=data, headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=5) as response:
        return json.load(response)


def make_server(role, root, address, collector_url):
    """Build a single-threaded server with independent local storage."""
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def respond(self, code, value):
            body = json.dumps(value).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            self.respond(200 if self.path == "/health" else 404, {"role": role})

        def do_POST(self):
            expected = "/receive" if role == "collector" else "/request"
            if self.path != expected:
                self.respond(404, {})
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 4096:
                    raise ValueError("invalid request size")
                payload = json.loads(self.rfile.read(size))
                seq = payload["seq"]
                if type(seq) is not int or not 1 <= seq <= 100:
                    raise ValueError("invalid sequence")
                if role == "collector":
                    line = payload["line"]
                    if not isinstance(line, str) or "\n" in line or "\r" in line:
                        raise ValueError("expected one original log line")
                    receipt = now()
                    record = (f"{receipt} logcol-01 fwd: origin=records "
                              f"file=/var/log/records-app/access.log seq={seq} msg={line}\n")
                    append(root / "evidence" / COLLECTOR, record.encode())
                    result = {"seq": seq, "received_at": receipt,
                              "sha256": hashlib.sha256(line.encode()).hexdigest()}
                else:
                    line = (f"{now()} rec-srv-01 testapp: user=demo action=read "
                            f"record=dummy-{seq} status=200 delivery_id={seq}")
                    # The pause is a real omission at the local sink, with coverage
                    # recorded by the fixture. Forwarding remains operational.
                    if not (root / "pause-local").exists():
                        append(root / "evidence" / LOCAL, (line + "\n").encode())
                    result = request(collector_url + "/receive", {"seq": seq, "line": line})
                    if result["sha256"] != hashlib.sha256(line.encode()).hexdigest():
                        raise ValueError("collector acknowledged different bytes")
                self.respond(200, result)
            except (ValueError, KeyError, OSError) as exc:
                self.respond(503, {"error": str(exc)})

    return HTTPServer(address, Handler)


def exercise(root, mode, service_url):
    """Execute three requests and save private actions outside the evidence tree."""
    if (root / "control.json").exists() or (root / "evidence").exists():
        raise RuntimeError("exercise requires a fresh service container")
    start = now()
    receipts = []
    actions = []
    gaps = []
    for seq in (1, 2, 3):
        if mode == "benign-gap" and seq == 2:
            gap_start = now()
            (root / "pause-local").touch()
        receipt = request(service_url + "/request", {"seq": seq})
        receipts.append(receipt)
        if mode == "missing-local-record" and seq == 2:
            local = root / "evidence" / LOCAL
            before = local.read_bytes()
            lines = before.splitlines(keepends=True)
            removed = lines[-1]
            if hashlib.sha256(removed.rstrip(b"\n")).hexdigest() != receipt["sha256"]:
                raise RuntimeError("receipt does not identify the line to remove")
            # Replace only the service's disposable local log after durable receipt.
            replacement = local.with_suffix(".tmp")
            replacement.write_bytes(b"".join(lines[:-1]))
            replacement.replace(local)
            actions.append({"action": "remove_local_line", "at": now(), "seq": seq,
                            "receipt": receipt, "removed_sha256": receipt["sha256"]})
        if mode == "benign-gap" and seq == 2:
            (root / "pause-local").unlink()
            gaps.append({"start": gap_start, "end": now(), "reason": "local sink paused for maintenance"})
            actions.append({"action": "pause_local_sink", **gaps[-1]})
        # ALIBI currently stores event times at second precision. Space requests
        # across seconds so the later local record brackets the retained line.
        time.sleep(1.05)
    control = {"mode": mode, "capture_start": start, "capture_end": now(),
               "receipts": receipts, "actions": actions, "known_gaps": gaps}
    (root / "control.json").write_text(json.dumps(control, indent=2) + "\n")
    return control


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("collector", "service", "health", "exercise"))
    parser.add_argument("--mode", choices=MODES, default="complete")
    args = parser.parse_args()
    if args.command == "health":
        request("http://127.0.0.1:8080/health")
    elif args.command == "exercise":
        exercise(Path("/data"), args.mode, "http://127.0.0.1:8080")
    else:
        make_server(args.command, Path("/data"), ("0.0.0.0", 8080), "http://collector:8080").serve_forever()


if __name__ == "__main__":
    main()
