"""Tests for the Chery Connect API client (no network, no HA needed).

Run with: python3 -m unittest discover -s tests -v
The client only needs a session object with async-context-manager
``post``/``get`` methods, so the tests use small fakes. Neither
``homeassistant`` nor ``aiohttp`` is installed in this VM, so the test
loads ``const``/``api`` directly (bypassing the package ``__init__``,
which imports Home Assistant) and stubs ``aiohttp`` with the two
names the client touches (``ClientTimeout``, ``ClientError``).
"""

import importlib.util
import sys
import types
import unittest
from pathlib import Path

_COMPONENTS = Path(__file__).resolve().parents[1] / "custom_components" / "chery_connect"

if "aiohttp" not in sys.modules:
    _aiohttp_stub = types.ModuleType("aiohttp")

    class _ClientTimeout:
        def __init__(self, total=None):
            self.total = total

    class _ClientError(Exception):
        pass

    _aiohttp_stub.ClientTimeout = _ClientTimeout
    _aiohttp_stub.ClientError = _ClientError
    sys.modules["aiohttp"] = _aiohttp_stub

_pkg = types.ModuleType("chery_connect")
_pkg.__path__ = [str(_COMPONENTS)]
sys.modules["chery_connect"] = _pkg


def _load_submodule(name):
    spec = importlib.util.spec_from_file_location(
        f"chery_connect.{name}", _COMPONENTS / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[f"chery_connect.{name}"] = module
    spec.loader.exec_module(module)
    return module


_load_submodule("const")
_api = _load_submodule("api")

BlockedError = _api.BlockedError
CheryConnectApiClient = _api.CheryConnectApiClient
InvalidAuthError = _api.InvalidAuthError
InvalidOtpError = _api.InvalidOtpError
parse_float = _api.parse_float
parse_odometer = _api.parse_odometer


class _FakeResponse:
    """Minimal stand-in for an aiohttp response."""

    def __init__(self, status, payload):
        self.status = status
        self._payload = payload

    async def json(self, content_type=None):
        return self._payload


class _FakeContextManager:
    """Async context manager wrapping a fake response."""

    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        return self._response

    async def __aexit__(self, *exc):
        return False


class _FakeSession:
    """Fake aiohttp session recording the last request."""

    def __init__(self):
        self.calls = []
        self.next_response = _FakeResponse(200, {})

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append(("POST", url, json, headers))
        return _FakeContextManager(self.next_response)

    def get(self, url, headers=None, timeout=None):
        self.calls.append(("GET", url, None, headers))
        return _FakeContextManager(self.next_response)


class TestParsing(unittest.TestCase):
    """Odometer / float parsing matches the app's behaviour."""

    def test_parse_odometer_with_commas(self):
        self.assertEqual(parse_odometer("12,345"), 12345.0)

    def test_parse_odometer_plain(self):
        self.assertEqual(parse_odometer("12345"), 12345.0)

    def test_parse_float_none_and_empty(self):
        self.assertIsNone(parse_float(None))
        self.assertIsNone(parse_float(""))
        self.assertIsNone(parse_float("abc"))

    def test_parse_float_string(self):
        self.assertEqual(parse_float("88.5"), 88.5)


class TestApiClient(unittest.IsolatedAsyncioTestCase):
    """OTP flow, auth errors and request shapes."""

    async def test_request_otp_payload(self):
        session = _FakeSession()
        session.next_response = _FakeResponse(200, {"res": "ok", "rescode": 1})
        client = CheryConnectApiClient(session)
        payload = await client.request_otp("0500000000", "12-345-67")
        self.assertEqual(payload["rescode"], 1)
        method, url, body, headers = session.calls[0]
        self.assertEqual(method, "POST")
        self.assertTrue(url.endswith("login/otp"))
        self.assertEqual(body["appid"], 34)
        self.assertEqual(body["MobilePhone"], "0500000000")
        self.assertEqual(body["VNumber"], "12-345-67")
        self.assertNotIn("Authorization", headers)

    async def test_request_otp_blocked(self):
        session = _FakeSession()
        session.next_response = _FakeResponse(200, {"res": "no", "rescode": -2})
        client = CheryConnectApiClient(session)
        with self.assertRaises(BlockedError):
            await client.request_otp("0500000000", "12-345-67")

    async def test_check_otp_returns_token(self):
        session = _FakeSession()
        session.next_response = _FakeResponse(
            200, {"token": "a" * 20, "resText": "ok"}
        )
        client = CheryConnectApiClient(session)
        token = await client.check_otp("0500000000", "12-345-67", "123456")
        self.assertEqual(token, "a" * 20)
        self.assertEqual(client.token, "a" * 20)

    async def test_check_otp_short_token_rejected(self):
        session = _FakeSession()
        session.next_response = _FakeResponse(200, {"token": "short"})
        client = CheryConnectApiClient(session)
        with self.assertRaises(InvalidOtpError):
            await client.check_otp("0500000000", "12-345-67", "123456")

    async def test_401_raises_invalid_auth(self):
        session = _FakeSession()
        session.next_response = _FakeResponse(401, {})
        client = CheryConnectApiClient(session, token="x" * 20)
        with self.assertRaises(InvalidAuthError):
            await client.get_vehicle_info()

    async def test_bearer_header_sent(self):
        session = _FakeSession()
        session.next_response = _FakeResponse(200, {"Odometer": "1,000"})
        client = CheryConnectApiClient(session, token="t" * 20)
        data = await client.get_vehicle_info()
        self.assertEqual(data["Odometer"], "1,000")
        _, _, _, headers = session.calls[0]
        self.assertEqual(headers["Authorization"], "Bearer " + "t" * 20)

    async def test_test_token_uses_get(self):
        session = _FakeSession()
        session.next_response = _FakeResponse(200, {})
        client = CheryConnectApiClient(session, token="t" * 20)
        self.assertTrue(await client.test_token())
        method, url, _, _ = session.calls[0]
        self.assertEqual(method, "GET")
        self.assertTrue(url.endswith("TestToken"))


if __name__ == "__main__":
    unittest.main()
