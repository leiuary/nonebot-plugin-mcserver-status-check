import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "nonebot_plugin_mcserver_status_check"
    / "address.py"
)
spec = importlib.util.spec_from_file_location("mcserver_address", MODULE_PATH)
assert spec is not None and spec.loader is not None
address_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(address_module)
is_valid_server_address = address_module.is_valid_server_address


class ServerAddressTests(unittest.TestCase):
    def test_accepts_server_addresses(self):
        addresses = [
            "127.0.0.1",
            "192.168.1.1:25565",
            "127.0.0.1:1",
            "127.0.0.1:65535",
            "::1",
            "2001:db8::1",
            "[::1]",
            "[2001:db8::1]:25565",
            "::ffff:192.0.2.1",
            "example.org",
            "play.example.org:25565",
            "MC-1.Example.ORG",
            "example.org.",
            "xn--fsqu00a.xn--0zwm56d",
            "例子.测试",
            "例子.测试:25565",
            "a" * 63 + ".example",
        ]
        for address in addresses:
            with self.subTest(address=address):
                self.assertTrue(is_valid_server_address(address))

    def test_rejects_non_addresses_and_invalid_ports(self):
        addresses = [
            "",
            "hello",
            "常驻服",
            "12345",
            "127.0.0",
            "256.1.2.3",
            "192.168.001.1",
            "999.999.999.999:25565",
            "http://example.org",
            "https://example.org:25565",
            "example.org/path",
            "example.org?query=1",
            "example.org#fragment",
            "user@example.org",
            "example.org another.org",
            " example.org",
            "example.org\n",
            "-mc.example.org",
            "mc-.example.org",
            "mc_server.example.org",
            "example..org",
            "example.org..",
            "example.123",
            "example.org:",
            "example.org:0",
            "example.org:65536",
            "example.org:-1",
            "example.org:abc",
            "example.org:２５５６５",
            "[example.org]:25565",
            "[127.0.0.1]:25565",
            "[2001:db8::1",
            "[2001:db8::1]garbage",
            "[2001:db8::1]:65536",
            "[2001:db8::1]:",
            "2001:db8::not-an-ip",
            "::1%eth0/path",
            "a" * 64 + ".example",
            ".".join(["a" * 63] * 4),
        ]
        for address in addresses:
            with self.subTest(address=address):
                self.assertFalse(is_valid_server_address(address))


if __name__ == "__main__":
    unittest.main()
