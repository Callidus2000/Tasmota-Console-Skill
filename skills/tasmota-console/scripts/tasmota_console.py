#!/usr/bin/env python3
"""Tasmota HTTP command and console transport; no implicit device changes."""
import argparse
import base64
import json
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


class ClientError(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def normalize_host(host):
    if not host:
        raise ClientError("A device host is required; no discovery is performed.")
    if "://" not in host:
        host = "http://" + host
    try:
        u = urllib.parse.urlsplit(host)
        port = u.port
    except ValueError:
        raise ClientError("Invalid device address or port.") from None
    if (u.scheme not in ("http", "https") or not u.hostname or u.username is not None
            or u.password is not None or u.path not in ("", "/") or u.query or u.fragment
            or any(c.isspace() for c in u.netloc)):
        raise ClientError("Host must be a hostname, IP or HTTP(S) origin without credentials or path.")
    if port is not None and not 1 <= port <= 65535:
        raise ClientError("Invalid device port.")
    return u.scheme + "://" + u.netloc


def read_password(args):
    if args.password_env:
        value = os.environ.get(args.password_env)
        if value is None or value == "":
            raise ClientError("Password environment variable is missing or empty.")
        return value
    if args.password_file:
        try:
            value = Path(args.password_file).read_text(encoding="utf-8").rstrip("\r\n")
        except (OSError, UnicodeError):
            raise ClientError("Cannot read password file.") from None
        if not value:
            raise ClientError("Password file is empty.")
        return value
    return None


def redact(text, password=None):
    # This is deliberately not advertised as comprehensive: arbitrary rules and logs
    # can embed secrets under unknown names or in free-form payloads.
    if password:
        text = text.replace(password, "[REDACTED]")
        encoded = urllib.parse.quote(password, safe="")
        text = text.replace(encoded, "[REDACTED]")
    text = re.sub(r'(?i)("(?:password|webpassword|mqttpassword|wifipassword|token|apikey)"\s*:\s*")[^"]*(")', r'\1[REDACTED]\2', text)
    text = re.sub(r'(?i)(\b(?:webpassword|mqttpassword|password[12]?)\s+)[^\s;"}]+', r'\1[REDACTED]', text)
    return text


class TasmotaClient:
    def __init__(self, host, timeout=5, user="admin", password=None):
        self.origin = normalize_host(host)
        self.timeout = timeout
        self.password = password
        self.headers = {"Referer": self.origin + "/", "Accept": "*/*"}
        if password is not None:
            token = base64.b64encode((user + ":" + password).encode("utf-8")).decode("ascii")
            self.headers["Authorization"] = "Basic " + token
        # Never forward credentials through proxies or redirects.
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def request(self, path, params):
        url = self.origin + path + "?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
        req = urllib.request.Request(url, headers=self.headers)
        try:
            with self.opener.open(req, timeout=self.timeout) as response:
                body = response.read(2_000_001)
                if len(body) > 2_000_000:
                    raise ClientError("Response exceeds 2 MB; discarded.")
                return body.decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            code = exc.code
            exc.close()
            if code in (401, 403):
                raise ClientError("Access denied (HTTP %s); check authentication, admin mode and referer policy." % code) from None
            raise ClientError("Device returned HTTP %s; redirect responses are not followed." % code) from None
        except (urllib.error.URLError, TimeoutError, socket.timeout, OSError):
            raise ClientError("Connection failed or timed out; a sent command may already have executed. Do not blindly retry.") from None

    def command(self, command):
        if not command or not command.strip() or "\x00" in command or "\r" in command or "\n" in command:
            raise ClientError("A command must be a non-empty single line without NUL.")
        body = self.request("/cm", {"cmnd": command})
        try:
            result = json.loads(body)
        except json.JSONDecodeError:
            raise ClientError("Unexpected non-JSON /cm response; execution state is unknown. Check API/admin access and firmware.") from None
        if not isinstance(result, dict):
            raise ClientError("Unexpected /cm response type; execution state is unknown.")
        return result

    def logs(self, cursor):
        body = self.request("/cs", {"c2": str(cursor)})
        pieces = body.split("}1", 2)
        if len(pieces) != 3 or not pieces[0].isdigit() or pieces[1] not in ("0", "1") or not pieces[2].endswith("}1"):
            raise ClientError("Unexpected /cs response; check console access and firmware compatibility.")
        return int(pieces[0]), pieces[1] == "1", pieces[2][:-2]


def print_json(value, password=None):
    print(redact(json.dumps(value, ensure_ascii=False, indent=2), password))


def write_private_json(path, value):
    # Exclusive creation avoids overwriting a previous backup. Permissions on Windows
    # depend on inherited ACLs; 0600 is not a substitute for checking them.
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    except OSError:
        raise ClientError("Cannot create snapshot exclusively; check directory, permissions and whether the file exists.") from None


def create_parser():
    parser = argparse.ArgumentParser(description="Tasmota HTTP console. Commands are never retried automatically.")
    parser.add_argument("--host", help="device hostname, IP or HTTP(S) origin; required except for diagnose")
    parser.add_argument("--timeout", type=float, default=5, help="HTTP timeout in seconds (default: 5)")
    parser.add_argument("--user", default="admin", help="web username (default: admin)")
    auth = parser.add_mutually_exclusive_group()
    auth.add_argument("--password-env", metavar="ENV_NAME", help="read web password from this environment variable")
    auth.add_argument("--password-file", metavar="PATH", help="read web password from a private file")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("diagnose", help="local checks only; does not connect to a device")
    cmd = sub.add_parser("command", help="send one complete Tasmota command without retries")
    source = cmd.add_mutually_exclusive_group(required=True)
    source.add_argument("text", nargs="?", help="command text; use --stdin/--file for shell-sensitive content")
    source.add_argument("--file", help="UTF-8 file containing one complete command")
    source.add_argument("--stdin", action="store_true", help="read one complete command from stdin")
    logs = sub.add_parser("logs", help="poll the web console; may contain sensitive information")
    logs.add_argument("--seconds", type=float, default=10)
    logs.add_argument("--interval", type=float, default=2)
    logs.add_argument("--cursor", type=int, default=0, help="initial Tasmota log cursor, default 0 (buffer history)")
    snap = sub.add_parser("rules-snapshot", help="save raw Rule1-3 responses to a new private file")
    snap.add_argument("--output", required=True, help="new file outside the skill/repository, may contain secrets")
    return parser


def main(argv=None):
    parser = create_parser()
    args = parser.parse_args(argv)
    try:
        if args.action == "diagnose":
            print_json({"python": sys.version.split()[0], "executable": sys.executable,
                        "network_tested": False, "minimum_python": "3.9"})
            return 0
        if not 0 < args.timeout <= 300:
            raise ClientError("Timeout must be greater than 0 and at most 300 seconds.")
        password = read_password(args)
        client = TasmotaClient(args.host, args.timeout, args.user, password)
        if args.action == "command":
            if args.stdin:
                text = sys.stdin.read()
            elif args.file:
                try:
                    text = Path(args.file).read_text(encoding="utf-8")
                except (OSError, UnicodeError):
                    raise ClientError("Cannot read command file.") from None
            else:
                text = args.text
            text = text.rstrip("\r\n")
            result = client.command(text)
            print_json(result, password)
            if not result:
                print("Warning: empty response does not prove execution or completion.", file=sys.stderr)
            if any(k.lower() in ("command", "warning", "error") for k in result):
                print("Warning: inspect response; Tasmota may have rejected or not recognized the command.", file=sys.stderr)
        elif args.action == "logs":
            if not (0 < args.seconds <= 3600 and 0.1 <= args.interval <= 300 and args.cursor >= 0):
                raise ClientError("Invalid duration, interval or cursor.")
            deadline = time.monotonic() + args.seconds
            cursor = args.cursor
            while True:
                cursor, initialized, text = client.logs(cursor)
                if not initialized:
                    print("Warning: device reset its console log cursor; history may be incomplete or duplicated.", file=sys.stderr)
                if text:
                    print(redact(text, password), flush=True)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                time.sleep(min(args.interval, remaining))
            print("Final cursor: %s" % cursor, file=sys.stderr)
        elif args.action == "rules-snapshot":
            results = {}
            for i in range(1, 4):
                key = "Rule%d" % i
                result = client.command(key)
                # Reject unsupported/error responses and incomplete snapshots before writing.
                rule = next((v for k, v in result.items() if str(k).lower() == key.lower()), None)
                if (not isinstance(rule, dict) or not isinstance(rule.get("Rules"), str)
                        or not all(isinstance(rule.get(field), str) for field in ("State", "Once", "StopOnError"))
                        or type(rule.get("Length")) is not int
                        or len(rule["Rules"].encode("utf-8")) != rule["Length"]):
                    raise ClientError("Could not read %s; no snapshot written. Check Rules support and response." % key)
                results[key] = result
            write_private_json(args.output, {"format": 1, "device": client.origin, "rules": results})
            print("Snapshot created; it contains raw sensitive data. Verify file permissions and keep it outside repositories.")
        return 0
    except ClientError as exc:
        print("Error: " + str(exc), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted; any sent command may already have executed.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
