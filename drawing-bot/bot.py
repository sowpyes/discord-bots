import io
import logging
import os
import random
from logging.handlers import RotatingFileHandler

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

import config
import pollinations

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")

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
@app_commands.describe(
    prompt="想要生成的圖片描述",
    ratio="圖片比例，預設 square",
    model="使用的模型(可選，只能從允許清單中選擇)",
    seed="固定亂數種子以重現結果(可選，留空則隨機並回報實際使用的值)",
    private="是否標記為不出現在 Pollinations 公開動態，並以僅自己可見的方式回覆(預設 false)",
)
@app_commands.choices(
    ratio=[app_commands.Choice(name=r, value=r) for r in config.RATIO_SIZES],
    model=[app_commands.Choice(name=m, value=m) for m in config.ALLOWED_MODELS],
)
async def draw(
    interaction: discord.Interaction,
    prompt: str,
    ratio: app_commands.Choice[str] = None,
    model: app_commands.Choice[str] = None,
    seed: int = None,
    private: bool = False,
):
    ratio_value = ratio.value if ratio else config.DEFAULT_RATIO
    model_value = model.value if model else None
    resolved_seed = seed if seed is not None else random.randint(0, 2_147_483_647)

    await interaction.response.defer(ephemeral=private)

    try:
        pollinations.validate_prompt(prompt)
        pollinations.validate_model(model_value)
        pollinations.cooldown_tracker.check(interaction.user.id)
        if not pollinations.concurrency_gate.try_acquire():
            raise pollinations.ConcurrencyLimitError("系統忙碌中(已達同時生成上限)，請稍後再試。")
    except pollinations.GenerationError as exc:
        await interaction.followup.send(exc.user_message)
        return

    pollinations.cooldown_tracker.mark(interaction.user.id)
    logger.info(
        "User %s requested draw: ratio=%s model=%s seed=%s private=%s",
        interaction.user, ratio_value, model_value, resolved_seed, private,
    )

    try:
        result = await pollinations.generate_image(prompt, ratio_value, model_value, resolved_seed, private)
    except pollinations.GenerationError as exc:
        await interaction.followup.send(exc.user_message)
        return
    finally:
        pollinations.concurrency_gate.release()

    logger.info(
        "Draw succeeded for %s: model=%s size=%dx%d seed=%d elapsed=%.2fs bytes=%d sha256=%s",
        interaction.user, result.model, result.width, result.height,
        result.seed, result.elapsed_seconds, len(result.image_bytes), result.sha256_prefix,
    )

    filename = f"drawing.{result.extension}"
    file = discord.File(io.BytesIO(result.image_bytes), filename=filename)
    embed = discord.Embed(title="圖片生成完成")
    embed.add_field(name="提示詞", value=prompt[:1024], inline=False)
    embed.add_field(name="模型", value=result.model, inline=True)
    embed.add_field(name="尺寸", value=f"{result.width}x{result.height}", inline=True)
    embed.add_field(name="Seed", value=str(result.seed), inline=True)
    embed.add_field(name="耗時", value=f"{result.elapsed_seconds:.2f}s", inline=True)
    embed.set_image(url=f"attachment://{filename}")

    await interaction.followup.send(embed=embed, file=file)


@bot.tree.command(name="models", description="顯示目前允許使用的圖片生成模型")
async def models_cmd(interaction: discord.Interaction):
    lines = [
        f"- {m}" + ("(預設)" if m == config.DEFAULT_MODEL else "")
        for m in config.ALLOWED_MODELS
    ]
    await interaction.response.send_message("目前允許的模型：\n" + "\n".join(lines))


@bot.tree.command(name="status", description="顯示 Bot 與圖片生成服務狀態")
async def status_cmd(interaction: discord.Interaction):
    embed = discord.Embed(title="Drawing Bot 狀態")
    embed.add_field(name="Bot 狀態", value="🟢 運作中", inline=True)
    embed.add_field(name="Provider", value="Pollinations", inline=True)
    embed.add_field(name="Endpoint 類型", value="Legacy(免金鑰)", inline=True)
    embed.add_field(name="需要 API Key", value="否", inline=True)
    embed.add_field(
        name="並行生成",
        value=f"{pollinations.concurrency_gate.active}/{pollinations.concurrency_gate.limit}",
        inline=True,
    )
    embed.add_field(name="每人冷卻時間", value=f"{config.USER_COOLDOWN_SECONDS} 秒", inline=True)
    await interaction.response.send_message(embed=embed)


def main():
    if not TOKEN:
        logger.error("DISCORD_TOKEN not set. Please fill it in .env")
        return
    bot.run(TOKEN, log_handler=None)


if __name__ == "__main__":
    main()
