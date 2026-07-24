import asyncio
import io
import logging
import os
import time
from logging.handlers import RotatingFileHandler
from urllib.parse import quote

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
POLLINATIONS_BASE_URL = "https://image.pollinations.ai/prompt"

os.makedirs("logs", exist_ok=True)

logger = logging.getLogger("drawing-bot")
logger.setLevel(logging.INFO)
_file_handler = RotatingFileHandler(
    "logs/drawing-bot.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
)
_file_handler.setFormatter(
    logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
)
_console_handler = logging.StreamHandler()
_console_handler.setFormatter(
    logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
)
logger.addHandler(_file_handler)
logger.addHandler(_console_handler)

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    logger.info("Logged in as %s (ID: %s)", bot.user, bot.user.id)
    try:
        synced = await bot.tree.sync()
        logger.info("Synced %d slash command(s)", len(synced))
    except Exception:
        logger.exception("Failed to sync slash commands")


@bot.tree.command(name="draw", description="用文字描述生成一張圖片")
@app_commands.describe(prompt="想要生成的圖片描述")
async def draw(interaction: discord.Interaction, prompt: str):
    await interaction.response.defer()
    url = f"{POLLINATIONS_BASE_URL}/{quote(prompt)}"
    logger.info("User %s requested draw: %s", interaction.user, prompt)
    start = time.monotonic()

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                elapsed = time.monotonic() - start
                content_type = resp.headers.get("Content-Type", "")
                model_used = resp.headers.get("X-Model-Used", "unknown")

                if resp.status != 200:
                    logger.error(
                        "Pollinations API returned status %d (elapsed=%.2fs, model=%s)",
                        resp.status, elapsed, model_used,
                    )
                    await interaction.followup.send("圖片生成失敗，請稍後再試。")
                    return

                if not content_type.startswith("image/"):
                    body_preview = (await resp.read())[:200]
                    logger.error(
                        "Pollinations API returned non-image content-type=%s (elapsed=%.2fs): %r",
                        content_type, elapsed, body_preview,
                    )
                    await interaction.followup.send("圖片生成失敗（伺服器回傳非圖片內容），請稍後再試。")
                    return

                image_bytes = await resp.read()
    except asyncio.TimeoutError:
        logger.exception("Pollinations API request timed out (elapsed=%.2fs)", time.monotonic() - start)
        await interaction.followup.send("圖片生成逾時，請稍後再試。")
        return
    except Exception:
        logger.exception("Error while requesting Pollinations API")
        await interaction.followup.send("發生錯誤，請稍後再試。")
        return

    extension = "png" if content_type == "image/png" else "jpg"
    logger.info(
        "Draw succeeded for %s: model=%s, elapsed=%.2fs, bytes=%d",
        interaction.user, model_used, elapsed, len(image_bytes),
    )
    file = discord.File(io.BytesIO(image_bytes), filename=f"drawing.{extension}")
    await interaction.followup.send(content=f"提示詞：{prompt}", file=file)


def main():
    if not TOKEN:
        logger.error("DISCORD_TOKEN not set. Please fill it in .env")
        return
    bot.run(TOKEN, log_handler=None)


if __name__ == "__main__":
    main()
