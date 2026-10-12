"""Mock OpenAI-compatible LLM for live VxDesk assistant testing.

Serves GET /v1/models and POST /v1/chat/completions on 127.0.0.1:11440.
Turn 1 (no tool results yet): returns a tool_calls response creating a small workflow.
Turn 2 (tool results present): returns a final text answer.
"""
import json
from http.server import BaseHTTPRequestHandler, HTTPServer

WORKFLOW_GRAPH = {
    "nodes": [
        {"id": "n1", "type": "trigger.manual", "name": "Start", "position": {"x": 0, "y": 100}, "params": {}, "disabled": False},
        {"id": "n2", "type": "control.log", "name": "Say hello", "position": {"x": 220, "y": 100}, "params": {"message": "Hello from the AI assistant!"}, "disabled": False},
        {"id": "n3", "type": "control.wait", "name": "Short pause", "position": {"x": 440, "y": 100}, "params": {"ms": 300}, "disabled": False},
        {"id": "n4", "type": "control.log", "name": "Done", "position": {"x": 660, "y": 100}, "params": {"message": "All done."}, "disabled": False},
    ],
    "edges": [
        {"id": "e1", "source": "n1", "target": "n2", "sourceHandle": "default"},
        {"id": "e2", "source": "n2", "target": "n3", "sourceHandle": "default"},
        {"id": "e3", "source": "n3", "target": "n4", "sourceHandle": "default"},
    ],
    "variables": {},
}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def _json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.rstrip("/").endswith("/models"):
            self._json({"object": "list", "data": [{"id": "mock-kimi-v1", "object": "model"}]})
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        if not self.path.rstrip("/").endswith("/chat/completions"):
            return self._json({"error": "not found"}, 404)
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        msgs = body.get("messages", [])
        has_tool_result = any(m.get("role") == "tool" for m in msgs)
        if not has_tool_result:
            resp = {
                "id": "chatcmpl-mock1", "object": "chat.completion", "created": 1, "model": "mock-kimi-v1",
                "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {
                    "role": "assistant", "content": "I'll build that workflow for you — one moment.",
                    "tool_calls": [{
                        "id": "call_1", "type": "function",
                        "function": {"name": "create_workflow", "arguments": json.dumps({
                            "name": "AI hello demo",
                            "description": "Built by the assistant: logs a greeting, pauses, logs done.",
                            **WORKFLOW_GRAPH})}}]}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
            }
        else:
            resp = {
                "id": "chatcmpl-mock2", "object": "chat.completion", "created": 2, "model": "mock-kimi-v1",
                "choices": [{"index": 0, "finish_reason": "stop", "message": {
                    "role": "assistant",
                    "content": "Done! I created a workflow called “AI hello demo” with 4 steps and checked that it's valid. Open it from the list and press Run whenever you like."}}],
                "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
            }
        self._json(resp)


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", 11440), Handler).serve_forever()
