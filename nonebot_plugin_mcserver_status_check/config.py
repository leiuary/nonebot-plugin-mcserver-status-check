from pydantic import BaseModel
from typing import List, Optional

class Server(BaseModel):
    address: str
    alias: Optional[str] = None

class Config(BaseModel):
    msc_server_list: List[Server] = []
    msc_latency_interval: float = 0.1
    msc_latency_warmup: int = 2
    msc_latency_count: int = 3
    msc_latency_trim: bool = True
    msc_show_timing_details: bool = False
    msc_font_path: str = "minecraft.ttf"
    msc_command_triggers: List[str] = ["查服"]
    msc_show_player_list: bool = False
