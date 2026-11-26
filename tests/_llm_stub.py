"""Tiny real HTTP servers that speak just enough of the OpenAI chat protocol, so a test can prove which server a
request reached and what it carried."""
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class LlmStub:
    def __init__(self, models=(), reply="ok", refuse=0, usage=None, host="127.0.0.1"):
        """refuse: an HTTP status to answer every request with (401 for a server that wants a key). usage: the usage
        object of every answer (default: 5 prompt tokens and 1 completion token, no charge). host: the one address
        it listens on ("::1" for a server on IPv6 only; OSError where the machine has none)."""
        self.requests = []
        stub, stub_models, stub_reply = self, list(models), reply
        stub_usage = usage or {"prompt_tokens": 5, "completion_tokens": 1}

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _record(self, body):
                stub.requests.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": body,
                                      "host": self.headers.get("Host")})

            def _json(self, payload):
                if refuse:
                    payload = {"error": {"message": "Unauthorized"}}
                data = json.dumps(payload).encode("utf-8")
                self.send_response(refuse or 200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                self._record(None)
                self._json({"data": [{"id": name} for name in stub_models]})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                self._record(body)
                if refuse or not body.get("stream"):
                    self._json({"model": body["model"], "choices": [{"message": {"content": stub_reply}, "finish_reason": "stop"}],
                                "usage": stub_usage})
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                rows = [{"model": body["model"], "choices": [{"delta": {"content": stub_reply}, "finish_reason": None}]},
                        {"model": body["model"], "choices": [{"delta": {}, "finish_reason": "stop"}]},
                        {"choices": [], "usage": stub_usage}]
                for row in rows:
                    self.wfile.write(("data: " + json.dumps(row) + "\n\n").encode("utf-8"))
                self.wfile.write(b"data: [DONE]\n\n")

        family = socket.AF_INET6 if ":" in host else socket.AF_INET
        self.server = type("Server", (ThreadingHTTPServer,), {"address_family": family})((host, 0), Handler)
        self.host = f"http://{f'[{host}]' if ':' in host else host}:{self.server.server_address[1]}"
        self.url = self.host + "/v1"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def chats(self):
        return [r for r in self.requests if r["body"] is not None]


def unused_url():
    """An address nothing is listening on (the port was just free), for a server that is down."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return f"http://127.0.0.1:{probe.getsockname()[1]}/v1"
