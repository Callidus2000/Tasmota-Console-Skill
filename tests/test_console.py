import contextlib
import importlib.util
import io
import json
import os
import tempfile
import threading
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("console", ROOT / "scripts" / "tasmota_console.py")
console = importlib.util.module_from_spec(spec)
spec.loader.exec_module(console)
spec = importlib.util.spec_from_file_location("catalog", ROOT / "scripts" / "build_catalog.py")
catalog = importlib.util.module_from_spec(spec)
spec.loader.exec_module(catalog)


class Device(BaseHTTPRequestHandler):
    requests = []
    responses = {}

    def log_message(self, *args):
        pass

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path)
        params = urllib.parse.parse_qs(path.query, keep_blank_values=True)
        Device.requests.append((path.path, params, dict(self.headers)))
        if path.path == "/cs":
            status, body = Device.responses.get("logs", (200, "42}11}112:00:00 RUL: event }1 text}1"))
        else:
            command = params.get("cmnd", [""])[0]
            if command in Device.responses:
                status, body = Device.responses[command]
            elif command in ("Rule1", "Rule2", "Rule3"):
                rule = 'ON Event#go DO WebSend [host,user:secret] /x ENDON'
                status, body = 200, json.dumps({command: {"State": "ON", "Once": "OFF", "StopOnError": "OFF", "Length": len(rule.encode("utf-8")), "Rules": rule}})
            else:
                status, body = 200, json.dumps({"received": command})
        self.send_response(status)
        if status == 302:
            self.send_header("Location", "http://127.0.0.1:1/redirected")
        self.end_headers()
        self.wfile.write(body.encode())


class TestDevice(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Device)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.host = "http://127.0.0.1:%s" % cls.server.server_port

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        Device.requests = []
        Device.responses = {}

    def test_command_roundtrip_and_encoding(self):
        command = 'Rule1 ON Event#test DO Backlog Publish abc {"text":"a+b & %value%"};Var1 %value% ENDON'
        result = console.TasmotaClient(self.host).command(command)
        self.assertEqual(result["received"], command)
        self.assertEqual(Device.requests[0][1]["cmnd"], [command])
        self.assertEqual(Device.requests[0][2]["Referer"], self.host + "/")

    def test_long_rule_is_single_request(self):
        command = "Rule1 " + ("ON Event#x DO Backlog Var1 %value%;Publish test + ENDON " * 40)
        result = console.TasmotaClient(self.host).command(command)
        self.assertEqual(result["received"], command)
        self.assertEqual(len(Device.requests), 1)

    def test_basic_auth_and_no_query_secret(self):
        console.TasmotaClient(self.host, password="abc+secret").command("Status 2")
        _, params, headers = Device.requests[0]
        self.assertEqual(params, {"cmnd": ["Status 2"]})
        self.assertEqual(headers["Authorization"], "Basic YWRtaW46YWJjK3NlY3JldA==")

    def test_console_cursor_and_delimiters(self):
        cursor, flag, text = console.TasmotaClient(self.host).logs(8)
        self.assertEqual((cursor, flag, text), (42, True, "12:00:00 RUL: event }1 text"))
        self.assertEqual(Device.requests[0][1], {"c2": ["8"]})

    def test_reject_bad_console_and_non_json(self):
        Device.responses["logs"] = (200, "<html>login</html>")
        Device.responses["Status 2"] = (200, "<html>login</html>")
        client = console.TasmotaClient(self.host)
        with self.assertRaises(console.ClientError):
            client.logs(0)
        with self.assertRaises(console.ClientError):
            client.command("Status 2")

    def test_http_errors_no_redirect_and_no_retry(self):
        for status in (401, 403, 302, 500):
            with self.subTest(status=status):
                Device.requests.clear()
                Device.responses["Power1 ON"] = (status, "ignored secret")
                with self.assertRaises(console.ClientError) as err:
                    console.TasmotaClient(self.host, password="secret").command("Power1 ON")
                self.assertNotIn("secret", str(err.exception))
                self.assertEqual(len(Device.requests), 1)

    def test_snapshot_raw_and_exclusive(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "snapshot.json"
            with contextlib.redirect_stdout(io.StringIO()) as output:
                code = console.main(["--host", self.host, "rules-snapshot", "--output", str(path)])
            self.assertEqual(code, 0)
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertIn("secret", saved["rules"]["Rule1"]["Rule1"]["Rules"])
            self.assertNotIn("secret", output.getvalue())
            if os.name != "nt":
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            before = path.read_bytes()
            with contextlib.redirect_stderr(io.StringIO()):
                code = console.main(["--host", self.host, "rules-snapshot", "--output", str(path)])
            self.assertEqual(code, 1)
            self.assertEqual(path.read_bytes(), before)

    def test_snapshot_incomplete_is_not_written(self):
        Device.responses["Rule2"] = (200, '{"Rule2": {"Rules": "incomplete"}}')
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stderr(io.StringIO()):
            path = Path(tmp) / "snapshot.json"
            self.assertEqual(console.main(["--host", self.host, "rules-snapshot", "--output", str(path)]), 1)
            self.assertFalse(path.exists())
            self.assertEqual(len(Device.requests), 2)

    def test_snapshot_refuses_truncated_rule(self):
        Device.responses["Rule1"] = (200, json.dumps({"Rule1": {"State": "ON", "Once": "OFF", "StopOnError": "OFF", "Length": 99, "Rules": "truncated"}}))
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stderr(io.StringIO()):
            path = Path(tmp) / "snapshot.json"
            self.assertEqual(console.main(["--host", self.host, "rules-snapshot", "--output", str(path)]), 1)
            self.assertFalse(path.exists())

    def test_stdin_does_not_split_special_rule(self):
        text = 'Rule1 ON Event#x DO Backlog Var1 %value%;Publish x {"v":"+"} ENDON\n'
        with mock.patch("sys.stdin", io.StringIO(text)), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(console.main(["--host", self.host, "command", "--stdin"]), 0)
        self.assertEqual(Device.requests[0][1]["cmnd"], [text.rstrip()])

    def test_command_file(self):
        text = 'Rule1 ON Event#test DO Publish x {"v":"%value%+"} ENDON'
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "command.txt"
            path.write_text(text + "\n", encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(console.main(["--host", self.host, "command", "--file", str(path)]), 0)
        self.assertEqual(Device.requests[0][1]["cmnd"], [text])


class TestLocal(unittest.TestCase):
    def test_host_validation(self):
        self.assertEqual(console.normalize_host("device.local:8080"), "http://device.local:8080")
        self.assertEqual(console.normalize_host("http://[::1]:80"), "http://[::1]:80")
        for host in ("", "file:///x", "http://user:pw@device", "http://a/path", "http://a/?cmnd=x", "http://a:abc", "http://a#x", "http://[::1"):
            with self.subTest(host=host), self.assertRaises(console.ClientError):
                console.normalize_host(host)

    def test_redact_and_password_sources(self):
        self.assertNotIn("supersecret", console.redact('{"WebPassword":"supersecret"} Password1 supersecret', "supersecret"))
        with mock.patch.dict(os.environ, {"TASMOTA_TEST_PASSWORD": "private"}):
            args = console.create_parser().parse_args(["--password-env", "TASMOTA_TEST_PASSWORD", "command", "Status 2"])
            self.assertEqual(console.read_password(args), "private")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "password"
            path.write_text("private\n", encoding="utf-8")
            args = console.create_parser().parse_args(["--password-file", str(path), "command", "Status 2"])
            self.assertEqual(console.read_password(args), "private")

    def test_command_rejects_multiline(self):
        client = console.TasmotaClient("127.0.0.1")
        for text in ("", " \t", "Power\nReset", "Power\x00off"):
            with self.assertRaises(console.ClientError):
                client.command(text)

    def test_diagnose_offline(self):
        with mock.patch.object(console.TasmotaClient, "request", side_effect=AssertionError("network")), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(console.main(["diagnose"]), 0)
            self.assertFalse(json.loads(output.getvalue())["network_tested"])

    def test_timeout_not_retried(self):
        client = console.TasmotaClient("127.0.0.1")
        with mock.patch.object(client.opener, "open", side_effect=TimeoutError()) as request:
            with self.assertRaises(console.ClientError) as err:
                client.command("Power1 TOGGLE")
        self.assertIn("already have executed", str(err.exception))
        self.assertEqual(request.call_count, 1)

    def test_catalog_full_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "site"
            catalog.build(output)
            index = json.loads((output / "index.json").read_text(encoding="utf-8"))
            entry = index["skills"][0]
            self.assertEqual(entry["name"], "tasmota-console")
            for name in entry["files"]:
                self.assertEqual((output / entry["name"] / name).read_bytes(), (ROOT / name).read_bytes())
            with self.assertRaises(FileExistsError):
                catalog.build(output)


if __name__ == "__main__":
    unittest.main()
