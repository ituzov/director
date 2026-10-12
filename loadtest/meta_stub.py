"""Заглушка Graph API Instagram для нагрузочного теста: worker думает, что шлёт
в Meta, а сообщения никуда не уходят. Отвечает с задержкой, как настоящая Meta.

Сколько чего «отправлено»: GET /stats.
"""

import json
import os
import re
import threading
import time
import uuid
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Meta отвечает на отправку около 300 мс, проверено вживую 2026-10-11
DELAY = float(os.environ.get("STUB_DELAY", "0.3"))

counts: Counter[str] = Counter()
lock = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if re.search(r"/messages$", self.path.split("?")[0]):
            self._reply("message", {"recipient_id": "1", "message_id": f"m_{uuid.uuid4().hex}"})
        elif re.search(r"/replies$", self.path.split("?")[0]):
            self._reply("comment_reply", {"id": uuid.uuid4().hex})
        else:
            self._reply("unknown_post", {"success": True})

    def do_GET(self) -> None:
        if self.path == "/stats":
            with lock:
                body = dict(counts)
            self._send(200, body)
        elif "is_user_follow_business" in self.path:
            self._reply("follow_check", {"is_user_follow_business": True})
        else:
            self._reply("unknown_get", {})

    def _reply(self, kind: str, body: dict) -> None:
        time.sleep(DELAY)
        with lock:
            counts[kind] += 1
        self._send(200, body)

    def _send(self, status: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args: object) -> None:
        # без строки на каждый запрос: под нагрузкой это тысячи строк
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT", "8080"))), Handler).serve_forever()
