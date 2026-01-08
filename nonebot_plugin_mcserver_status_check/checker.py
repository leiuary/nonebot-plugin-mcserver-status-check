from __future__ import annotations

import concurrent.futures
import json
import socket
import struct
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from PIL import Image, ImageDraw, ImageFont
from mcstatus import JavaServer

from .config import Config
from .mc_renderer import calculate_required_width, generate_server_card, parse_inner_legacy

# Image Settings
TITLE_TEXT = "Minecraft Server Status"
FOOTER_TEXT_TEMPLATE = "{time} | Made by leiuary"
BG_COLOR = (30, 30, 30)
TEXT_COLOR = (255, 255, 255)
FOOTER_COLOR = (150, 150, 150)
ROW_GAP = 10

# --- 辅助函数 ---

def get_font_path(config: Config) -> str:
    """解析字体路径，如果未找到则检查本地目录。"""
    path = Path(config.msc_font_path)
    if path.exists():
        return str(path)
    
    # 尝试在与此文件相同的目录中查找
    local_path = Path(__file__).parent / config.msc_font_path
    if local_path.exists():
        return str(local_path)
        
    return config.msc_font_path

def pack_varint(d):
    """将整数打包为 VarInt (Minecraft 协议)。"""
    o = b''
    while True:
        b = d & 0x7F
        d >>= 7
        o += struct.pack("B", b | (0x80 if d > 0 else 0))
        if d == 0: break
    return o

def unpack_varint(sock):
    """从 socket 解包 VarInt。"""
    d = 0
    for i in range(5):
        b = sock.recv(1)
        if not b:
            return 0
        b = b[0]
        d |= (b & 0x7F) << (7 * i)
        if not (b & 0x80):
            return d
    return 0

def get_rgb_json(hostname, port):
    """
    使用原始协议连接到 Minecraft 服务器以检索完整的 JSON 状态。
    这样做是因为 mcstatus 有时会简化 JSON 结构。
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(5)
    try:
        sock.connect((hostname, port))
        protocol = 763 # MC 1.20.4 协议版本 (近似值)
        host_bytes = hostname.encode('utf-8')
        
        # 握手包
        data = (b'\x00' + pack_varint(protocol) + pack_varint(len(host_bytes)) + 
                host_bytes + struct.pack('!H', port) + pack_varint(1))
        sock.send(pack_varint(len(data)) + data)
        
        # 请求包
        sock.send(b'\x01\x00')
        time.sleep(0.1) 
        sock.send(b'\x01\x00') # 发送两次以确保在某些情况下能收到响应
        
        _ = unpack_varint(sock) # 包长度
        packet_id = unpack_varint(sock)
        
        if packet_id != 0: 
            raise Exception("Packet ID mismatch")
            
        json_len = unpack_varint(sock)
        buffer = b''
        while len(buffer) < json_len:
            chunk = sock.recv(min(4096, json_len - len(buffer)))
            if not chunk: break
            buffer += chunk
        
        # 服务器返回的是 UTF-8 文本，需要解码后再解析 JSON
        return json.loads(buffer.decode('utf-8', errors='replace'))
    finally:
        sock.close()

class MixedStatus:
    """
    结合了原始 JSON 数据和 mcstatus 延迟的混合状态对象。
    模仿渲染器预期的结构。
    """
    @dataclass
    class Players:
        online: int
        max: int
        sample: list[dict[str, Any]]

    def __init__(self, raw_json: dict[str, Any], mcstatus_latency: float, fail_count: int = 0):
        self.raw = raw_json
        self.latency = mcstatus_latency
        self.fail_count = fail_count
        self.favicon = raw_json.get("favicon")
        p = raw_json.get("players", {})
        self.players = self.Players(
            online=p.get("online", 0),
            max=p.get("max", 0),
            sample=p.get("sample", []),
        )

class OfflineStatus:
    """
    表示服务器连接失败。
    """
    def __init__(self, error_msg: str):
        self.raw = {
            "description": {"text": f"§c无法连接到服务器\n§7{error_msg}"},
            "players": {"online": 0, "max": 0},
            "favicon": None, "version": {"name": "Unknown"}
        }
        self.latency = -1
        self.players = MixedStatus.Players(online=0, max=0, sample=[])


# --- 核心逻辑 ---

def query_one_server(index, address, config: Config):
    """
    查询单个服务器的状态。
    执行预热 Ping，多次测试 Ping，并计算平均延迟。
    """
    print(f"⏳ [{index+1}] 查询: {address}")
    t_start = time.time()
    detailed_logs = []
    
    try:
        # --- 延迟测试 ---
        latencies = []
        last_std_status = None
        
        t_warmup_start = time.time()
        
        # 1. 预热
        if config.msc_latency_warmup > 0:
            for w_i in range(config.msc_latency_warmup):
                try:
                    t0 = time.time()
                    temp_server = JavaServer.lookup(address, timeout=5)
                    t1 = time.time()
                    temp_server.status()
                    t2 = time.time()
                    detailed_logs.append(f"预热#{w_i+1}: DNS={(t1-t0)*1000:.1f}ms, Query={(t2-t1)*1000:.1f}ms")
                    time.sleep(config.msc_latency_interval)
                except Exception:
                    detailed_logs.append(f"预热#{w_i+1}: 失败")
        t_warmup_end = time.time()

        # 2. 实际测试
        trim_enabled = (config.msc_latency_trim is True)
        # 如果是 min/best 模式，默认不需要像 trim 那样额外加次数，但为了更有可能撞到好线路，多测几次也没问题。
        # 这里为了保持去极值的一致性，如果是 True 则加2次。如果是字符串(min/best) 暂时不强制加2次，
        # 但用户可以通过增加 msc_latency_count 来控制测试次数。
        
        target_count = config.msc_latency_count + (2 if trim_enabled else 0)
        t_test_start = time.time()
        
        fail_count = 0
        for i in range(target_count):
            try:
                t0 = time.time()
                # 每次都重新 lookup 以避免连接复用问题
                server = JavaServer.lookup(address, timeout=5)
                t1 = time.time()
                st = server.status()
                t2 = time.time()
                
                dns_ms = (t1 - t0) * 1000
                query_ms = (t2 - t1) * 1000
                ping_ms = st.latency
                
                latencies.append(ping_ms)
                last_std_status = st
                detailed_logs.append(f"测试#{i+1}: DNS={dns_ms:.1f}ms, Query={query_ms:.1f}ms, Ping={ping_ms:.1f}ms")
            except Exception:
                fail_count += 1
                detailed_logs.append(f"测试#{i+1}: 失败")
            
            if i < target_count - 1:
                time.sleep(config.msc_latency_interval)
        t_test_end = time.time()
        
        if not latencies:
            raise Exception("无法连接到服务器 (所有尝试均失败)")

        # 3. 计算统计数据
        is_trimmed = False
        mode_note = "" # 用于日志打印的模式说明
        raw_latencies = list(latencies)
        
        # 方差始终基于原始数据计算
        raw_avg = sum(latencies) / len(latencies)
        variance = sum((x - raw_avg) ** 2 for x in latencies) / len(latencies)

        # 核心策略分流
        latency_mode = config.msc_latency_trim

        if isinstance(latency_mode, str) and latency_mode.lower() == "best":
            # 最小延迟优先模式
            avg_latency = min(latencies)
            mode_note = " (极速模式)"
        elif latency_mode is True and len(latencies) >= 3:
            # 去极值模式 (去掉最大最小)
            sorted_latencies = sorted(latencies)
            valid_latencies = sorted_latencies[1:-1]
            avg_latency = sum(valid_latencies) / len(valid_latencies)
            is_trimmed = True
            mode_note = " (已去极值)"
        else:
            # 默认平均值模式
            avg_latency = raw_avg
            mode_note = " (平均值)"

        # 记录结果
        latency_str = ", ".join([f"{l:.2f}" for l in raw_latencies])
        
        t_total = time.time() - t_start
        t_warmup = t_warmup_end - t_warmup_start
        t_test = t_test_end - t_test_start
        
        print(f"✅ [{index+1}] {address} -> 延迟: [{latency_str}] -> 结果: {avg_latency:.2f} ms{mode_note}, 方差: {variance:.2f}, 丢包: {fail_count}")
        
        if config.msc_show_timing_details:
            print(f"   🕒 耗时详情: 总计 {t_total:.2f}s (预热: {t_warmup:.2f}s, 测试: {t_test:.2f}s)")
            for log in detailed_logs:
                print(f"      -> {log}")

        # 4. 获取完整 JSON 数据
        # 我们需要真实的 host/port (已解析) 来获取原始 JSON
        final_server = JavaServer.lookup(address, timeout=5) 
        real_host = final_server.address.host
        real_port = final_server.address.port
        
        rgb_json = get_rgb_json(real_host, real_port)
        status_obj = MixedStatus(rgb_json, avg_latency, fail_count)
        
        return {
            "index": index, 
            "address": address, 
            "success": True, 
            "json": rgb_json, 
            "status_obj": status_obj
        }
        
    except Exception as e:
        err_str = str(e)
        if "Expecting value" in err_str: err_str = "服务器返回无效数据"
        elif "timed out" in err_str or "lifetime expired" in err_str: err_str = "连接超时"
        elif "getaddrinfo" in err_str: err_str = "域名解析失败"
        
        print(f"⚠️ [{index+1}] {address} 失败: {err_str}")
        
        offline_obj = OfflineStatus(err_str)
        return {
            "index": index, 
            "address": address, 
            "success": False, 
            "json": {"error": err_str}, 
            "status_obj": offline_obj
        }

def create_summary_image(combined_rows, config: Config) -> Optional[Image.Image]:
    """
    将单独的服务器行合并为带有标题和页脚的单个汇总图像。
    """
    if not combined_rows:
        return None

    # 加载字体
    font_path = get_font_path(config)
    try:
        font_title = ImageFont.truetype(font_path, 48)
        font_footer = ImageFont.truetype(font_path, 24)
    except:
        font_title = ImageFont.load_default()
        font_footer = ImageFont.load_default()

    # 计算尺寸
    dummy_draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    title_w = dummy_draw.textlength(TITLE_TEXT, font=font_title)
    title_h = 100 
    
    footer_text = FOOTER_TEXT_TEMPLATE.format(time=time.strftime('%Y-%m-%d %H:%M:%S'))
    footer_w = dummy_draw.textlength(footer_text, font=font_footer)
    footer_h = 40 

    content_w = combined_rows[0].width
    total_w = max(content_w, int(title_w + 60), int(footer_w + 60))
    
    list_h = sum(img.height for img in combined_rows) + (len(combined_rows)-1) * ROW_GAP
    total_h = title_h + list_h + footer_h
    
    # 绘制
    summary_img = Image.new('RGB', (total_w, total_h), BG_COLOR)
    draw = ImageDraw.Draw(summary_img)
    
    # 标题
    draw.text(((total_w - title_w) // 2, (title_h - 48) // 2), TITLE_TEXT, fill=TEXT_COLOR, font=font_title)
    
    # 服务器行
    curr_y = title_h
    for img in combined_rows:
        x_offset = (total_w - img.width) // 2
        summary_img.paste(img, (x_offset, curr_y))
        curr_y += img.height + ROW_GAP
        
    # 页脚
    draw.text((total_w - footer_w - 20, total_h - footer_h + 10), footer_text, fill=FOOTER_COLOR, font=font_footer)
    
    return summary_img

def generate_mcmotd_image(config: Config) -> Optional[Image.Image]:
    print(f"🚀 开始并行查询 {len(config.msc_server_list)} 个服务器...")
    
    font_path = get_font_path(config)

    # 并行查询
    query_results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        future_map = {executor.submit(query_one_server, i, server.address, config): i for i, server in enumerate(config.msc_server_list)}
        for future in concurrent.futures.as_completed(future_map):
            query_results.append(future.result())
    
    query_results.sort(key=lambda x: x["index"])

    # 1. 计算全局宽度以进行对齐
    max_width = 0
    for res in query_results:
        idx = res["index"]
        alias = config.msc_server_list[idx].alias
        w = calculate_required_width(res["address"], res["status_obj"], font_path=font_path, alias=alias)
        if w > max_width: max_width = w
    
    max_width = max(max_width, 800) # 最小宽度

    # 2. 生成单独的行
    combined_rows = []
    for res in query_results:
        idx = res["index"]
        alias = config.msc_server_list[idx].alias
        icon, info = generate_server_card(res["address"], res["status_obj"], fixed_width=max_width, font_path=font_path, alias=alias)
        
        # 合并图标 + 信息
        row_width = icon.width + info.width
        row_height = 128
        
        # 检查玩家列表
        player_img = None
        if config.msc_show_player_list and hasattr(res["status_obj"].players, 'sample') and res["status_obj"].players.sample:
             player_img = render_player_list(res["status_obj"].players.sample, row_width, font_path)
        
        if player_img:
            row_height += player_img.height

        row_img = Image.new('RGB', (row_width, row_height), (30, 30, 30))
        row_img.paste(icon, (0, 0))
        row_img.paste(info, (icon.width, 0))
        
        if player_img:
            row_img.paste(player_img, (0, 128))
        
        combined_rows.append(row_img)

    # 3. 生成汇总图片
    if combined_rows:
        return create_summary_image(combined_rows, config)
    return None

def render_player_list(players, width, font_path):
    if not players: return None
    
    try:
        font = ImageFont.truetype(font_path, 20)
    except:
        font = ImageFont.load_default()
        
    dummy = ImageDraw.Draw(Image.new("RGB", (1,1)))
    
    # 展平名称并处理颜色
    # 某些服务器在玩家列表中使用 '&' 表示颜色
    names = []
    for p in players:
        raw_name = p.get("name", "Unknown")
        # 将 & 替换为 § 以进行颜色解析，但仅当它看起来像颜色代码时
        # 目前进行简单替换
        names.append(raw_name.replace("&", "§"))
    
    # 检测这是否可能是消息列表（自定义信息）或真实的玩家列表
    # 标准：包含颜色代码、空格或非 ASCII 字符
    is_message_list = False
    for n in names:
        if "§" in n or " " in n:
            is_message_list = True
            break
        # 检查非 ascii (例如中文)
        if any(ord(c) > 127 for c in n):
            is_message_list = True
            break

    lines = []
    current_line = []
    current_width = 0
    max_width = width - 40 # 填充
    
    if is_message_list:
        # 每行一个条目
        for name in names:
            lines.append([name])
    else:
        # 紧凑模式（逗号分隔）
        for name in names:
            # 去除代码以计算宽度
            clean_name = name
            for i in range(10): clean_name = clean_name.replace(f"§{i}", "")
            for c in "abcdefklmnor": clean_name = clean_name.replace(f"§{c}", "")
            
            name_w = dummy.textlength(clean_name + ", ", font=font)
            
            if current_width + name_w > max_width and current_line:
                lines.append(current_line)
                current_line = [name]
                current_width = name_w
            else:
                current_line.append(name)
                current_width += name_w
                
        if current_line: lines.append(current_line)
    
    line_height = 24
    h = len(lines) * line_height + 20
    
    img = Image.new("RGB", (width, h), BG_COLOR)
    draw = ImageDraw.Draw(img)
    
    y = 10
    default_color = (200, 200, 200)
    
    for line in lines:
        x = 20
        for i, name in enumerate(line):
            # 如果不是最后一个且不在消息模式下，则添加分隔符
            separator = ", " if (not is_message_list and i < len(line) - 1) else ""
            full_text = name + separator
            
            # 解析并绘制段
            segments = parse_inner_legacy(full_text, default_color)
            for text, color in segments:
                draw.text((x, y), text, fill=color, font=font)
                x += dummy.textlength(text, font=font)
                
        y += line_height
        
    return img

def generate_single_server_image(address: str, config: Config) -> Optional[Image.Image]:
    font_path = get_font_path(config)
    
    # 查找别名
    alias = None
    for s in config.msc_server_list:
        if s.address == address:
            alias = s.alias
            break

    # 查询
    res = query_one_server(0, address, config)
    status = res["status_obj"]
    
    # 生成卡片
    w = calculate_required_width(address, status, font_path=font_path, alias=alias)
    w = max(w, 800)
    
    icon, info = generate_server_card(address, status, fixed_width=w, font_path=font_path, alias=alias)
    
    # 合并图标 + 信息
    row_width = icon.width + info.width
    row_height = 128
    row_img = Image.new('RGB', (row_width, row_height), BG_COLOR)
    row_img.paste(icon, (0, 0))
    row_img.paste(info, (icon.width, 0))
    
    # 玩家列表
    player_img = None
    if hasattr(status.players, 'sample') and status.players.sample:
        player_img = render_player_list(status.players.sample, row_width, font_path)
        
    # 标题和页脚
    try:
        font_title = ImageFont.truetype(font_path, 48)
        font_footer = ImageFont.truetype(font_path, 24)
    except:
        font_title = ImageFont.load_default()
        font_footer = ImageFont.load_default()
        
    dummy = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    
    title_w = dummy.textlength(TITLE_TEXT, font=font_title)
    title_h = 100
    
    footer_text = FOOTER_TEXT_TEMPLATE.format(time=time.strftime('%Y-%m-%d %H:%M:%S'))
    footer_w = dummy.textlength(footer_text, font=font_footer)
    footer_h = 40
    
    # 计算总高度
    total_h = title_h + row_height + (player_img.height if player_img else 0) + footer_h + ROW_GAP
    total_w = max(row_width, int(title_w + 60), int(footer_w + 40))
    
    # 创建最终图像
    final_img = Image.new("RGB", (total_w, total_h), BG_COLOR)
    draw = ImageDraw.Draw(final_img)
    
    # 绘制标题
    draw.text(((total_w - title_w) // 2, (title_h - 48) // 2), TITLE_TEXT, fill=TEXT_COLOR, font=font_title)
    
    # 粘贴行

    x_offset = (total_w - row_width) // 2
    final_img.paste(row_img, (x_offset, title_h))
    
    curr_y = title_h + row_height
    
    # Paste Player List
    if player_img:
        final_img.paste(player_img, (x_offset, curr_y))
        curr_y += player_img.height
        
    # Draw Footer
    draw.text((total_w - footer_w - 20, total_h - footer_h + 10), footer_text, fill=FOOTER_COLOR, font=font_footer)
    
    return final_img
