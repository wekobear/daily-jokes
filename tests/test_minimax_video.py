"""Real local HTTP contracts for MiniMax; never contacts the paid provider."""

import base64
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import struct
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request
import zlib


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from minimax_video import MiniMaxClient, MiniMaxError, build_i2v_payload, load_env


TEST_KEY = "contract-test-secret-not-a-real-key"
MP4 = struct.pack(">I", 24) + b"ftypisom\x00\x00\x02\x00isomiso2" + struct.pack(">I", 8) + b"mdat"


def png_bytes():
    def chunk(kind, content):
        return struct.pack(">I", len(content)) + kind + content + struct.pack(">I", zlib.crc32(kind + content))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">2I5B", 256, 256, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress((b"\0" + b"\x7f\x7f\x7f" * 256) * 256))
        + chunk(b"IEND", b"")
    )


@contextmanager
def provider_server(mode="normal", statuses=None):
    observed = []
    remaining = list(statuses or ["queued", "running", "succeeded"])

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def respond(self, data, status=200, content_type="application/json"):
            if not isinstance(data, bytes):
                data = json.dumps(data).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            observed.append(("POST", self.path, dict(self.headers), json.loads(raw)))
            if mode == "lost-submit":
                self.connection.shutdown(socket.SHUT_RDWR)
                self.connection.close()
                return
            if mode == "rejected":
                self.respond({"type": "error", "error": {"message": f"Bad key {TEST_KEY}; Bearer {TEST_KEY}"}, "request_id": "request-123"}, 401)
                return
            if mode == "server-error":
                self.respond({"type": "error", "error": {"message": "Internal error"}}, 500)
                return
            if mode == "invalid-json":
                self.respond(b"not json")
                return
            if mode == "missing-task":
                self.respond({"ok": True})
                return
            if mode == "redirect":
                self.send_response(307)
                self.send_header("Location", "/redirected")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.respond({"task_id": "task-123"})

        def do_GET(self):
            observed.append(("GET", self.path, dict(self.headers), None))
            if self.path.startswith("/v2/query/video_generation?"):
                self.respond({"items": [], "total": 0})
                return
            if self.path == "/v2/query/video_generation/task-123":
                status = remaining.pop(0) if len(remaining) > 1 else remaining[0]
                task = {"id": "task-123", "model": "MiniMax-H3", "status": status}
                if status == "succeeded":
                    task.update(content={"url": f"http://127.0.0.1:{self.server.server_port}/clip.mp4"}, usage={"output_seconds": 5})
                if status == "failed":
                    task["error"] = {"code": "1026", "message": "Rejected with " + TEST_KEY}
                if mode == "wrong-task":
                    task["id"] = "another-task"
                if mode == "missing-url":
                    task.pop("content", None)
                self.respond({"task": task})
                return
            if self.path == "/clip.mp4":
                if mode == "html-download":
                    self.respond(b"<html>expired</html>", content_type="text/html")
                elif mode == "empty-download":
                    self.respond(b"", content_type="video/mp4")
                elif mode == "expired-download":
                    self.respond({"error": "Expired"}, 403)
                else:
                    self.respond(MP4, content_type="video/mp4")
                return
            self.respond({"error": "Not found"}, 404)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", observed
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


class MiniMaxContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.image = self.directory / "scene.png"
        self.image.write_bytes(png_bytes())
        self.payload = build_i2v_payload(self.image, "小熊抬头，用普通话说：今天也要开心。")

    def tearDown(self):
        self.temp.cleanup()

    def test_submit_poll_download_real_http_contract(self):
        with provider_server() as (url, observed):
            client = MiniMaxClient(TEST_KEY, base_url=url, timeout=3)
            task_id = client.submit(self.payload)
            tasks = [client.query(task_id) for _ in range(3)]
            self.assertEqual([t["status"] for t in tasks], ["queued", "running", "succeeded"])
            destination = client.download(tasks[-1]["content"]["url"], self.directory / "video.mp4")
        self.assertEqual(destination.read_bytes(), MP4)
        post = observed[0]
        self.assertEqual(post[:2], ("POST", "/v2/video_generation"))
        self.assertEqual(post[2]["Authorization"], "Bearer " + TEST_KEY)
        self.assertEqual(post[2]["Content-Type"], "application/json")
        self.assertEqual(post[3]["model"], "MiniMax-H3")
        self.assertEqual(post[3]["ratio"], "adaptive")
        encoded = post[3]["content"][1]["image_url"]["url"]
        self.assertTrue(encoded.startswith("data:image/png;base64,"))
        self.assertEqual(base64.b64decode(encoded.split(",", 1)[1]), self.image.read_bytes())
        self.assertNotIn("Authorization", observed[-1][2])
        self.assertEqual(len([r for r in observed if r[0] == "POST"]), 1)

    def test_ambiguous_submissions_are_never_retried(self):
        for mode in ("lost-submit", "server-error", "invalid-json", "missing-task"):
            with self.subTest(mode=mode), provider_server(mode) as (url, observed):
                client = MiniMaxClient(TEST_KEY, base_url=url, timeout=2)
                with self.assertRaises(MiniMaxError) as caught:
                    client.submit(self.payload)
                self.assertTrue(caught.exception.uncertain)
                self.assertNotIn(TEST_KEY, str(caught.exception))
                self.assertEqual(len(observed), 1)

    def test_error_body_key_is_redacted_and_request_id_preserved(self):
        with provider_server("rejected") as (url, observed):
            with self.assertRaises(MiniMaxError) as caught:
                MiniMaxClient(TEST_KEY, base_url=url).submit(self.payload)
        error = caught.exception
        self.assertEqual(error.status_code, 401)
        self.assertEqual(error.request_id, "request-123")
        self.assertFalse(error.uncertain)
        self.assertNotIn(TEST_KEY, str(error))
        self.assertIn("[REDACTED]", str(error))
        self.assertEqual(len(observed), 1)

    def test_post_redirect_does_not_forward_key_or_create_second_task(self):
        with provider_server("redirect") as (url, observed):
            with self.assertRaises(MiniMaxError) as caught:
                MiniMaxClient(TEST_KEY, base_url=url).submit(self.payload)
        self.assertEqual(caught.exception.status_code, 307)
        self.assertEqual(len(observed), 1)

    def test_terminal_failures_return_sanitized_task_details(self):
        for status in ("failed", "cancelled"):
            with self.subTest(status=status), provider_server(statuses=[status]) as (url, _):
                task = MiniMaxClient(TEST_KEY, base_url=url).query("task-123")
                self.assertEqual(task["status"], status)
                self.assertNotIn(TEST_KEY, json.dumps(task))

    def test_query_rejects_wrong_id_unknown_status_or_missing_download(self):
        for mode, status in (("wrong-task", "running"), ("normal", "unknown"), ("missing-url", "succeeded")):
            with self.subTest(mode=mode), provider_server(mode, [status]) as (url, _):
                with self.assertRaises(MiniMaxError):
                    MiniMaxClient(TEST_KEY, base_url=url).query("task-123")

    def test_bad_download_leaves_no_output_or_partial_file(self):
        for mode in ("html-download", "empty-download", "expired-download"):
            with self.subTest(mode=mode), provider_server(mode) as (url, _):
                with self.assertRaises(MiniMaxError):
                    MiniMaxClient(TEST_KEY, base_url=url).download(url + "/clip.mp4", self.directory / "out.mp4")
            self.assertFalse((self.directory / "out.mp4").exists())
            self.assertEqual(list(self.directory.glob(".minimax-*")), [])

    def test_download_size_limit_and_existing_file_are_preserved(self):
        with provider_server() as (url, observed):
            client = MiniMaxClient(TEST_KEY, base_url=url)
            destination = self.directory / "existing.mp4"
            destination.write_bytes(b"user-owned-file")
            with self.assertRaises(MiniMaxError):
                client.download(url + "/clip.mp4", destination)
            self.assertEqual(destination.read_bytes(), b"user-owned-file")
            self.assertEqual(observed, [])
            with self.assertRaises(MiniMaxError):
                client.download(url + "/clip.mp4", self.directory / "large.mp4", max_bytes=16)
            self.assertFalse((self.directory / "large.mp4").exists())
            self.assertEqual(list(self.directory.glob(".minimax-*")), [])

    def test_read_only_list_tasks_authentication_check(self):
        with provider_server() as (url, observed):
            result = MiniMaxClient(TEST_KEY, base_url=url).list_tasks(page_num=2, page_size=3)
        self.assertEqual(result, {"items": [], "total": 0})
        self.assertEqual(observed[0][:2], ("GET", "/v2/query/video_generation?page_num=2&page_size=3"))

    def test_injected_opener_receives_timeout_and_request(self):
        class FailingOpener:
            def __init__(self):
                self.calls = []

            def open(self, request, timeout):
                self.calls.append((request, timeout))
                raise urllib.error.URLError("transport leaked " + TEST_KEY)

        opener = FailingOpener()
        client = MiniMaxClient(TEST_KEY, timeout=7, opener=opener)
        with self.assertRaises(MiniMaxError) as caught:
            client.submit(self.payload)
        self.assertNotIn(TEST_KEY, str(caught.exception))
        self.assertTrue(caught.exception.uncertain)
        self.assertEqual(len(opener.calls), 1)
        self.assertEqual(opener.calls[0][1], 7)

    def test_generation_options_are_validated_before_submission(self):
        invalid = [
            {"duration": 3}, {"duration": 5.0}, {"duration": True}, {"resolution": "1080P"},
            {"model": "unknown"}, {"model": "MiniMax-H3-Max", "duration": 4},
            {"model": "MiniMax-H3-Max", "resolution": "2K"},
        ]
        for options in invalid:
            with self.subTest(options=options), self.assertRaises(MiniMaxError):
                build_i2v_payload(self.image, "hello", **options)
        for prompt in ("", " " * 10, "字" * 7001):
            with self.subTest(prompt_length=len(prompt)), self.assertRaises(MiniMaxError):
                build_i2v_payload(self.image, prompt)
        payload = build_i2v_payload(self.image, "hello", model="MiniMax-H3-Max", duration=5, resolution="480P")
        self.assertEqual(payload["resolution"], "480P")

    def test_configuration_rejects_unsafe_base_urls(self):
        for url in ("http://example.com", "https://user:password@example.com", "https://example.com/api", "https://example.com?key=secret", "file:///tmp/key"):
            with self.subTest(url=url), self.assertRaises(MiniMaxError):
                MiniMaxClient(TEST_KEY, base_url=url)
        for timeout in (0, -1, float("nan"), float("inf")):
            with self.subTest(timeout=timeout), self.assertRaises(MiniMaxError):
                MiniMaxClient(TEST_KEY, timeout=timeout)

    def test_env_is_literal_and_existing_values_win(self):
        marker = self.directory / "must-not-exist"
        environment_file = self.directory / ".env"
        environment_file.write_text(
            "# config\nMINIMAX_API_KEY=file-key\n"
            "JOKE_TEST_QUOTED='hello # world'\n"
            f"JOKE_TEST_LITERAL=$(touch {marker})\n"
            "JOKE_TEST_BACKTICK=`whoami`\n"
            "JOKE_TEST_URL=https://example.com/#fragment # note\n"
            "export JOKE_TEST_EMPTY=\n",
            encoding="utf-8",
        )
        with patch.dict(os.environ, {"MINIMAX_API_KEY": "existing-key"}, clear=True):
            parsed = load_env(environment_file)
            self.assertEqual(os.environ["MINIMAX_API_KEY"], "existing-key")
            self.assertEqual(parsed["MINIMAX_API_KEY"], "file-key")
            self.assertEqual(os.environ["JOKE_TEST_QUOTED"], "hello # world")
            self.assertEqual(os.environ["JOKE_TEST_LITERAL"], f"$(touch {marker})")
            self.assertEqual(os.environ["JOKE_TEST_BACKTICK"], "`whoami`")
            self.assertEqual(os.environ["JOKE_TEST_URL"], "https://example.com/#fragment")
            self.assertEqual(os.environ["JOKE_TEST_EMPTY"], "")
            load_env(environment_file, override=True)
            self.assertEqual(os.environ["MINIMAX_API_KEY"], "file-key")
        self.assertFalse(marker.exists())

    def test_invalid_env_does_not_partially_change_environment_or_leak_values(self):
        path = self.directory / ".env"
        path.write_text("JOKE_TEST_FIRST=ok\nTHIS_IS_A_SECRET_WITHOUT_EQUALS\n", encoding="utf-8")
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(MiniMaxError) as caught:
                load_env(path)
            self.assertNotIn("JOKE_TEST_FIRST", os.environ)
            self.assertNotIn("THIS_IS_A_SECRET", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
