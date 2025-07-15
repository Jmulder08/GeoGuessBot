import logging
import os

from discord import Intents
from discord.ext import commands

logger = logging.getLogger("discord")
logger.setLevel(logging.DEBUG)
handler = logging.FileHandler(filename="discord.log", encoding="utf-8", mode="w")
handler.setFormatter(
    logging.Formatter("%(asctime)s:%(levelname)s:%(name)s: %(message)s")
)
logger.addHandler(handler)

with open("secrets.txt", "r") as f:
    secrets = f.read().splitlines()
    TOKEN = secrets[2]

intents = Intents.default()
intents.members = True
bot = commands.Bot(command_prefix=">", intents=intents)


@bot.event
async def on_ready():
    print("Bot active")


@bot.command()
async def ping(ctx):
    print("ping?")
    await ctx.send(f"Ping is {round(bot.latency * 1000)}ms")


@bot.command()
@commands.has_permissions(administrator=True)
async def purge(ctx, limit=50):
    await ctx.channel.purge(limit=limit)


@bot.command()
@commands.has_permissions(administrator=True)
async def reload(ctx, extension):
    bot.reload_extension(f"cogs.{extension}")
    await ctx.send(f"{extension} reloaded!")


# for filename in os.listdir("./cogs"):
#     if filename.endswith(".py"):
#         bot.load_extension(f"cogs.{filename[:-3]}")

bot.run(TOKEN)
