<div align="center">
    <a href="https://v2.nonebot.dev/store">
    <img src="https://raw.githubusercontent.com/fllesser/nonebot-plugin-template/refs/heads/resource/.docs/NoneBotPlugin.svg" width="310" alt="logo"></a>

## ✨ nonebot-plugin-mcserver-status ✨
[![LICENSE](https://img.shields.io/github/license/leiuary/nonebot-plugin-mcserver-status.svg)](./LICENSE)
[![pypi](https://img.shields.io/pypi/v/nonebot-plugin-mcserver-status.svg)](https://pypi.python.org/pypi/nonebot-plugin-mcserver-status)
[![python](https://img.shields.io/badge/python-3.10|3.11|3.12|3.13-blue.svg)](https://www.python.org)
[![uv](https://img.shields.io/badge/package%20manager-uv-black?style=flat-square&logo=uv)](https://github.com/astral-sh/uv)
<br/>
[![ruff](https://img.shields.io/badge/code%20style-ruff-black?style=flat-square&logo=ruff)](https://github.com/astral-sh/ruff)
[![pre-commit](https://results.pre-commit.ci/badge/github/leiuary/nonebot-plugin-mcserver-status/master.svg)](https://results.pre-commit.ci/latest/github/leiuary/nonebot-plugin-mcserver-status/master)

</div>

## 📖 介绍

- 支持同时查询多个服务器。
- 生成美观的状态卡片图片。
- 显示服务器图标 (Favicon)。
- 解析并渲染 Minecraft 颜色代码 (MOTD)。
- 详细的延迟测试（预热、多次测试取平均值、去极值）。
- 可配置的字体和显示选项。

## 💿 安装

<details open>
<summary>使用 nb-cli 安装</summary>
在 nonebot2 项目的根目录下打开命令行, 输入以下指令即可安装

    nb plugin install nonebot-plugin-mcserver-status --upgrade
使用 **pypi** 源安装

    nb plugin install nonebot-plugin-mcserver-status --upgrade -i "https://pypi.org/simple"
使用**清华源**安装

    nb plugin install nonebot-plugin-mcserver-status --upgrade -i "https://pypi.tuna.tsinghua.edu.cn/simple"


</details>

<details>
<summary>使用包管理器安装</summary>
在 nonebot2 项目的插件目录下, 打开命令行, 根据你使用的包管理器, 输入相应的安装命令

<details open>
<summary>uv</summary>

    uv add nonebot-plugin-mcserver-status
安装仓库 master 分支

    uv add git+https://github.com/leiuary/nonebot-plugin-mcserver-status@master
</details>

<details>
<summary>pdm</summary>

    pdm add nonebot-plugin-mcserver-status
安装仓库 master 分支

    pdm add git+https://github.com/leiuary/nonebot-plugin-mcserver-status@master
</details>
<details>
<summary>poetry</summary>

    poetry add nonebot-plugin-mcserver-status
安装仓库 master 分支

    poetry add git+https://github.com/leiuary/nonebot-plugin-mcserver-status@master
</details>

打开 nonebot2 项目根目录下的 `pyproject.toml` 文件, 在 `[tool.nonebot]` 部分追加写入

    plugins = ["nonebot_plugin_mcserver_status"]

</details>

<details>
<summary>使用 nbr 安装(使用 uv 管理依赖可用)</summary>

[nbr](https://github.com/fllesser/nbr) 是一个基于 uv 的 nb-cli，可以方便地管理 nonebot2

    nbr plugin install nonebot-plugin-mcserver-status
使用 **pypi** 源安装

    nbr plugin install nonebot-plugin-mcserver-status -i "https://pypi.org/simple"
使用**清华源**安装

    nbr plugin install nonebot-plugin-mcserver-status -i "https://pypi.tuna.tsinghua.edu.cn/simple"

</details>


## ⚙️ 配置

在 nonebot2 项目的`.env`文件中添加下表中的配置

```dotenv
# 服务器列表
MCMOTD_SERVER_LIST='[]'

# 延迟测试间隔(秒)
MCMOTD_LATENCY_INTERVAL=0.1

# 延迟测试预热次数
MCMOTD_LATENCY_WARMUP=1

# 延迟测试次数
MCMOTD_LATENCY_COUNT=3

# 是否去极值(去掉最大最小)
MCMOTD_LATENCY_TRIM=true

# 是否在控制台显示详细耗时
MCMOTD_SHOW_TIMING_DETAILS=false

# 字体文件
MCMOTD_FONT_PATH="minecraft.ttf"

# 触发指令列表
MCMOTD_COMMAND_TRIGGERS=["查服"]

# 是否在列表模式显示玩家名单
MCMOTD_SHOW_PLAYER_LIST=false
```

### 服务器列表配置示例

```dotenv
MCMOTD_SERVER_LIST='[
  {"address": "mc.hypixel.net", "alias": "Hypixel"},
  {"address": "play.example.com", "alias": "示例服"}
]'
```

## 🎉 使用
### 指令列表

- **查服**
  - 查询所有配置的服务器状态，生成汇总图片。
- **查服 [IP/别名]**
  - 单独查询指定服务器的状态。
- **查服列表**
  - 查看当前配置的服务器列表及别名。

### 🎨 效果图
如果有效果图的话

## 💡 特性

- 🎨 **原版风格**：完美还原 Minecraft 游戏内的服务器列表显示效果。
- ⚡ **高效并发**：支持多服务器并行查询，速度飞快。
- 📊 **精准延迟**：内置预热和去极值算法，提供最真实的延迟数据。
- 📝 **颜色支持**：完整支持 Minecraft 样式代码 (§) 和 JSON 格式 MOTD。
- 🖼️ **图标显示**：自动获取并显示服务器 Favicon。
- 👥 **玩家列表**：支持显示在线玩家列表（需服务器开启相关功能）。
