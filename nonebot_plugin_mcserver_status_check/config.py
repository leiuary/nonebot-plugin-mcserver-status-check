from pydantic import BaseModel, Field
from typing import List, Optional, Union

class Server(BaseModel):
    address: str
    alias: Optional[str] = None

class Config(BaseModel):
    msc_server_list: List[Server] = Field(default_factory=list)
    msc_latency_interval: float = 0.1
    msc_latency_warmup: int = 2
    msc_latency_count: int = 3
    # True=去极值, False=平均值, "best"=最小值(最低延迟优先)
    msc_latency_trim: Union[bool, str] = True
    msc_show_timing_details: bool = False
    msc_font_path: str = "minecraft.ttf"
    msc_command_triggers: List[str] = Field(default_factory=lambda: ["查服"])
    msc_show_player_list: bool = False
