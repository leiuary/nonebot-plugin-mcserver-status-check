"""Generate a Minecraft-style preview using the public 2b2t server."""

from __future__ import annotations

import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PACKAGE = ROOT / "nonebot_plugin_mcserver_status_check"
SERVER_ADDRESS = "2b2t.org"
SERVER_ALIAS = "2b2t"

# Load the plugin modules without initializing the NoneBot plugin.
package = types.ModuleType("nonebot_plugin_mcserver_status_check")
package.__path__ = [str(PACKAGE)]
sys.modules[package.__name__] = package

from nonebot_plugin_mcserver_status_check.vanilla_screen_renderer import (  # noqa: E402
    render_server_list_image,
)


def main() -> None:
    from nonebot_plugin_mcserver_status_check.checker import query_one_server
    from nonebot_plugin_mcserver_status_check.config import Config

    config = Config(
        msc_latency_warmup=0,
        msc_latency_count=1,
        msc_latency_trim=False,
        msc_latency_interval=0,
    )
    result = query_one_server(0, SERVER_ADDRESS, config)
    status = result["status_obj"]
    raw = getattr(status, "raw", {}) or {}
    version = raw.get("version") or {}
    version_name = version if isinstance(version, str) else version.get("name", "Unknown")
    players = raw.get("players") or {}
    print(
        f"[{SERVER_ALIAS}] {SERVER_ADDRESS}: "
        f"{players.get('online', 0)}/{players.get('max', 0)}, {version_name}, "
        f"{getattr(status, 'latency', -1):.1f} ms"
    )

    # Match the single-server command: render the player sample returned by the server.
    image = render_server_list_image(
        [{
            "address": SERVER_ADDRESS,
            "alias": SERVER_ALIAS,
            "status_obj": status,
            "player_samples": getattr(status.players, "sample", None) or [],
        }],
    )
    output_path = ROOT / "preview-readme.png"
    image.save(output_path, optimize=True)
    print(f"Saved {output_path}")


if __name__ == "__main__":
    main()
