from pydantic import BaseModel
from typing import List, Optional

class Server(BaseModel):
    address: str
    alias: Optional[str] = None

class Config(BaseModel):
    mcmotd_server_list: List[Server] = [
        Server(address="slv4.starlight.cool", alias="sl"),
        Server(address="north.starlight.cool", alias="sl北方"),
        Server(address="south.starlight.cool", alias="sl南方"),
        Server(address="mc.lazyalienserver.top", alias="las"),
        Server(address="mod.sdustmc.cn", alias="周目"),
        Server(address="minigame.sdustmc.cn", alias="小游戏"),
        Server(address="web.sitmc.club:1501"),
        Server(address="2b2t.org", alias="2b2t"),
    ]
    mcmotd_latency_interval: float = 0.1
    mcmotd_latency_warmup: int = 5
    mcmotd_latency_count: int = 5
    mcmotd_latency_trim: bool = True
    mcmotd_show_timing_details: bool = False
    mcmotd_font_path: str = "minecraft.ttf"
    mcmotd_command_triggers: List[str] = ["查服"]
    mcmotd_show_player_list: bool = False
