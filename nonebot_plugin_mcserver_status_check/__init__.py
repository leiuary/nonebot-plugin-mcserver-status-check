from __future__ import annotations

import asyncio
import io
from typing import Annotated, Set

from nonebot import get_plugin_config, on_command
from nonebot.adapters.onebot.v11 import Message, MessageSegment
from nonebot.exception import FinishedException
from nonebot.params import CommandArg
from nonebot.plugin import Matcher, PluginMetadata

from .config import Config
from .checker import generate_mcmotd_image, generate_single_server_image

__plugin_meta__ = PluginMetadata(
    name="Minecraft Server Status",
    description="一款原版风格、美观高效的 Minecraft 服务器状态查询插件",
    usage="\n".join([
        "指令:",
        "查服",
        "查服 [IP/别名]",
    ]),
    type="application",
    homepage="https://github.com/leiuary/nonebot-plugin-mcserver-status",
    supported_adapters={"nonebot.adapters.onebot.v11"},
    config=Config,
)

# Load configuration
plugin_config = get_plugin_config(Config)

# Determine command name and aliases
triggers = plugin_config.mcmotd_command_triggers
cmd_name = triggers[0] if triggers else "查服"
cmd_aliases: Set[str | tuple[str, ...]] = set(triggers[1:]) if len(triggers) > 1 else set()

# Define command
mcmotd: Matcher = on_command(cmd_name, aliases=cmd_aliases, priority=5, block=True)

@mcmotd.handle()
async def handle_mcmotd(args: Annotated[Message, CommandArg()]):
    arg_text = args.extract_plain_text().strip()
    
    if arg_text:
        # Single server query
        target_address = arg_text
        # Check if it matches an alias
        for server in plugin_config.mcmotd_server_list:
            if server.alias == arg_text:
                target_address = server.address
                break
        
        await mcmotd.send(f"正在查询服务器 {target_address}，请稍候...")
        
        try:
            image = await asyncio.to_thread(generate_single_server_image, target_address, plugin_config)
            
            if image:
                img_byte_arr = io.BytesIO()
                image.save(img_byte_arr, format='PNG')
                img_bytes = img_byte_arr.getvalue()
                await mcmotd.finish(MessageSegment.image(img_bytes))
            else:
                await mcmotd.finish("查询失败，未能生成状态图片。")
                
        except FinishedException:
            raise
        except Exception as e:
            await mcmotd.finish(f"发生错误: {str(e)}")
            
    else:
        # All servers query
        await mcmotd.send("正在查询服务器状态，请稍候...")
        
        try:
            image = await asyncio.to_thread(generate_mcmotd_image, plugin_config)
            
            if image:
                img_byte_arr = io.BytesIO()
                image.save(img_byte_arr, format='PNG')
                img_bytes = img_byte_arr.getvalue()
                await mcmotd.finish(MessageSegment.image(img_bytes))
            else:
                await mcmotd.finish("查询失败，未能生成状态图片。")
                
        except FinishedException:
            raise
        except Exception as e:
            await mcmotd.finish(f"发生错误: {str(e)}")

# List command
cmd_list = on_command("查服列表", priority=5, block=True)

@cmd_list.handle()
async def handle_list():
    msg = "已保存的服务器列表：\n"
    for server in plugin_config.mcmotd_server_list:
        alias_str = f" (别名: {server.alias})" if server.alias else ""
        msg += f"- {server.address}{alias_str}\n"
    await cmd_list.finish(msg.strip())
