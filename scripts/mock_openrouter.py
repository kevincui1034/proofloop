#!/usr/bin/env python3
"""Mock OpenRouter server for the demo's LLM leg (stdlib only, 127.0.0.1).

Binds port 0 (ephemeral), prints the chosen port to stdout (flushed) so the
demo script can parse it, then answers any POST with a canned
chat-completions payload. The content is a fenced ```json block on purpose —
it exercises the fence-tolerant parser in _openai_compat.py.
"""

import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

RESPONSE = {
    "model": "openai/gpt-4o-mini",
    "usage": {"cost": 0.00042},
    "choices": [
        {
            "message": {
                "content": (
                    "```json\n"
                    + json.dumps(
                        {
                            "diagnosis": (
                                "The deploy is blocked because required "
                                "environment variables are missing on the "
                                "target and readiness checks have not run "
                                "against this worktree."
                            ),
                            "fix_steps": [
                                "Set the missing environment variables.",
                                "Run the tests through proofjury, then re-run the gate.",
                            ],
                        }
                    )
                    + "\n```"
                )
            }
        }
    ],
}


# Advisory-review requests (identified by the advisory system prompt) get a
# canned findings payload instead — one high-confidence discovery finding.
# The demo's checks-only leg never triggers this (no git diff in the demo
# workdir → the advisory judge is skipped); it exists so the mock leg can be
# explicitly configured to exercise the advisory surface end to end.
ADVISORY_RESPONSE = {
    "model": "openai/gpt-4o-mini",
    "usage": {"cost": 0.00042},
    "choices": [
        {
            "message": {
                "content": json.dumps(
                    {
                        "findings": [
                            {
                                "concern": (
                                    "The webhook send has no retry or failure "
                                    "handling; a transient 5xx silently drops "
                                    "the notification."
                                ),
                                "kind": "discovery",
                                "tier": 4,
                                "confidence": 0.82,
                                "grounded_in": [],
                                "target": "notifications.py:12",
                            }
                        ]
                    }
                )
            }
        }
    ],
}


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length)
        response = RESPONSE
        try:
            request = json.loads(raw)
            system = (request.get("messages") or [{}])[0].get("content", "")
            if "advisory reviewer" in system:
                response = ADVISORY_RESPONSE
        except (ValueError, AttributeError, IndexError):
            pass
        body = json.dumps(response).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # keep the demo output clean
        pass


def main() -> None:
    server = HTTPServer(("127.0.0.1", 0), Handler)
    print(server.server_address[1], flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
