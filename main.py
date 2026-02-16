import os
import sys
import json
import asyncio
import logging
import sqlite3
import hashlib
import aiohttp
import discord
import datetime
from typing import Union, Optional, List, Dict, Any
from discord.ext import commands, tasks
from discord import app_commands

class NexusInfrastructure(commands.Bot):
    def __init__(self):
        self.config = {
            "version": "4.2.0-stable",
            "build": hashlib.md5(str(datetime.datetime.now()).encode()).hexdigest()[:8],
            "hex_color": 0x2b2d31,
            "assets": {"success": "✅", "error": "❌", "load": "⚙️"}
        }
        
        super().__init__(
            command_prefix=self._get_prefix,
            intents=discord.Intents.all(),
            help_command=None,
            case_insensitive=True
        )
        
        self.db_path = "internal_registry.db"
        self.session: Optional[aiohttp.ClientSession] = None
        self._cache: Dict[str, Any] = {}
        self.boot_time = datetime.datetime.now(datetime.timezone.utc)
        
        self._setup_logging()
        self._initialize_database()

    def _setup_logging(self):
        self.logger = logging.getLogger('NexusInternal')
        self.logger.setLevel(logging.DEBUG)
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter('\033[90m%(asctime)s\033[0m [\033[96m%(levelname)s\033[0m] %(message)s'))
        self.logger.addHandler(handler)

    def _initialize_database(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS guild_settings (
                    guild_id INTEGER PRIMARY KEY,
                    prefix TEXT DEFAULT '!',
                    authorized_roles TEXT,
                    logging_channel INTEGER
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS security_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    target_id INTEGER,
                    action TEXT,
                    executor_id INTEGER,
                    timestamp DATETIME
                )
            """)
            conn.commit()

    async def _get_prefix(self, bot, message):
        if not message.guild:
            return '!'
        gid = message.guild.id
        if f"pref_{gid}" not in self._cache:
            with sqlite3.connect(self.db_path) as conn:
                res = conn.execute("SELECT prefix FROM guild_settings WHERE guild_id = ?", (gid,)).fetchone()
                self._cache[f"pref_{gid}"] = res[0] if res else '!'
        return self._cache[f"pref_{gid}"]

    async def setup_hook(self):
        self.session = aiohttp.ClientSession()
        self.background_telemetry.start()
        self.logger.info(f"Subsystems initialized. Build: {self.config['build']}")

    @tasks.loop(seconds=60)
    async def background_telemetry(self):
        await self.wait_until_ready()
        payload = {
            "hb": round(self.latency * 1000, 2),
            "guilds": len(self.guilds),
            "users": sum(g.member_count for g in self.guilds if g.member_count)
        }
        self.logger.debug(f"Telemetry pulse: {payload['hb']}ms latency")

    async def on_message(self, message):
        if message.author.bot or not message.guild:
            return
        await self.process_commands(message)

    @commands.group(name="system", invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def system_group(self, ctx):
        embed = discord.Embed(title="System Management Interface", color=self.config['hex_color'])
        embed.add_field(name="Kernel", value=f"v{self.config['version']}", inline=True)
        embed.add_field(name="Build Hash", value=f"`{self.config['build']}`", inline=True)
        embed.set_footer(text="Access Level: Administrator")
        await ctx.send(embed=embed)

    @system_group.command(name="prefix")
    async def set_prefix(self, ctx, new_prefix: str):
        if len(new_prefix) > 5:
            return await ctx.send("Prefix too long.")
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT OR REPLACE INTO guild_settings (guild_id, prefix) VALUES (?, ?)", (ctx.guild.id, new_prefix))
        self._cache[f"pref_{ctx.guild.id}"] = new_prefix
        await ctx.send(f"Dynamic prefix updated to: `{new_prefix}`")

    @commands.command(name="metrics")
    async def metrics(self, ctx):
        delta_uptime = datetime.datetime.now(datetime.timezone.utc) - self.boot_time
        hours, remainder = divmod(int(delta_uptime.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        
        description = (
            f"**Uptime:** `{hours}h {minutes}m {seconds}s`\n"
            f"**Websocket:** `{round(self.latency * 1000, 2)}ms`\n"
            f"**Memory Mapping:** `{len(self._cache)} cached objects`"
        )
        
        embed = discord.Embed(description=description, color=self.config['hex_color'])
        embed.set_author(name="Operational Metrics", icon_url=self.user.avatar.url)
        await ctx.send(embed=embed)

    @commands.command(name="secure_clear")
    @commands.has_permissions(manage_messages=True)
    async def secure_clear(self, ctx, amount: int = 10):
        await ctx.message.delete()
        purged = await ctx.channel.purge(limit=amount)
        log_embed = discord.Embed(title="Security Event: Purge", color=0xff4747)
        log_embed.add_field(name="Vector", value=ctx.channel.mention)
        log_embed.add_field(name="Quantity", value=str(len(purged)))
        log_embed.add_field(name="Authorized by", value=ctx.author.mention)
        await ctx.send(embed=log_embed, delete_after=10)

    @commands.command(name="node_test")
    async def node_test(self, ctx, host: str = "https://discord.com"):
        start = datetime.datetime.now()
        async with self.session.get(host) as resp:
            diff = (datetime.datetime.now() - start).total_seconds() * 1000
            status = resp.status
        await ctx.send(f"Node response from `{host}`: `{status}` in `{round(diff, 2)}ms`")

    @app_commands.command(name="sync", description="Force sync application command tree")
    @app_commands.checks.has_permissions(administrator=True)
    async def sync_tree(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        synced = await self.tree.sync()
        await interaction.followup.send(f"Synchronized {len(synced)} global command nodes.")

async def run_instance():
    instance = NexusInfrastructure()
    async with instance:
        try:
            await instance.start("YOUR_TOKEN_HERE")
        except KeyboardInterrupt:
            await instance.close()

if __name__ == "__main__":
    try:
        asyncio.run(run_instance())
    except Exception as _e:
        sys.stderr.write(f"Fatal Startup Error: {_e}\n")