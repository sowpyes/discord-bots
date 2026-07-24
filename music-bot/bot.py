import logging
import os
from logging.handlers import RotatingFileHandler
from urllib.parse import urlparse

import discord
import wavelink
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
LAVALINK_URI = os.getenv("LAVALINK_URI", "http://127.0.0.1:2333")
LAVALINK_PASSWORD = os.getenv("LAVALINK_PASSWORD", "")

os.makedirs("logs", exist_ok=True)

logger = logging.getLogger("music-bot")
logger.setLevel(logging.INFO)
_file_handler = RotatingFileHandler(
    "logs/music-bot.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
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


class MusicBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        node = wavelink.Node(uri=LAVALINK_URI, password=LAVALINK_PASSWORD)
        try:
            await wavelink.Pool.connect(nodes=[node], client=self)
        except Exception:
            logger.exception("Failed to connect to Lavalink node at %s", LAVALINK_URI)


bot = MusicBot()


@bot.event
async def on_ready():
    logger.info("Logged in as %s (ID: %s)", bot.user, bot.user.id)
    try:
        synced = await bot.tree.sync()
        logger.info("Synced %d slash command(s)", len(synced))
    except Exception:
        logger.exception("Failed to sync slash commands")


@bot.event
async def on_wavelink_node_ready(payload: wavelink.NodeReadyEventPayload):
    logger.info("Lavalink node ready: %s (session=%s)", payload.node.uri, payload.session_id)


@bot.event
async def on_wavelink_track_end(payload: wavelink.TrackEndEventPayload):
    logger.info(
        "Track ended: %s (reason=%s)",
        payload.track.title if payload.track else "unknown",
        payload.reason,
    )


@bot.event
async def on_wavelink_track_exception(payload: wavelink.TrackExceptionEventPayload):
    logger.error(
        "Track exception: %s - %s",
        payload.track.title if payload.track else "unknown",
        payload.exception,
    )


@bot.event
async def on_wavelink_track_stuck(payload: wavelink.TrackStuckEventPayload):
    logger.error(
        "Track stuck: %s (threshold=%dms)",
        payload.track.title if payload.track else "unknown",
        payload.threshold_ms,
    )


def _get_voice_client(interaction: discord.Interaction) -> wavelink.Player | None:
    return interaction.guild.voice_client if interaction.guild else None


def _redact_url(url: str) -> str:
    try:
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}/***"
    except Exception:
        return "<unparseable-url>"


def _lavalink_available() -> bool:
    return any(
        node.status is wavelink.NodeStatus.CONNECTED for node in wavelink.Pool.nodes.values()
    )


def _missing_voice_permissions(channel: discord.VoiceChannel, member: discord.Member) -> list[str]:
    perms = channel.permissions_for(member)
    missing = []
    if not perms.connect:
        missing.append("Connect")
    if not perms.speak:
        missing.append("Speak")
    return missing


async def _ensure_voice_client(
    interaction: discord.Interaction,
) -> tuple[wavelink.Player | None, str | None]:
    """Returns (player, error_message). If error_message is set, player is None."""
    if interaction.guild is None:
        return None, "此指令僅限在伺服器內使用。"

    if not _lavalink_available():
        return None, "Lavalink 伺服器目前未連線，請稍後再試或聯絡管理員確認伺服器狀態。"

    if not interaction.user.voice or not interaction.user.voice.channel:
        return None, "請先加入一個語音頻道。"

    voice_channel = interaction.user.voice.channel
    missing = _missing_voice_permissions(voice_channel, interaction.guild.me)
    if missing:
        return None, f"Bot 缺少必要權限：{', '.join(missing)}，請檢查身分組/頻道權限設定。"

    vc = _get_voice_client(interaction)
    try:
        if vc is None:
            vc = await voice_channel.connect(cls=wavelink.Player)
            logger.info("Joined voice channel: %s (guild=%s)", voice_channel.name, interaction.guild.id)
        elif vc.channel.id != voice_channel.id:
            await vc.move_to(voice_channel)
    except Exception:
        logger.exception("Failed to join voice channel (guild=%s)", interaction.guild.id)
        return None, "無法加入語音頻道，請稍後再試。"

    return vc, None


@bot.tree.command(name="join", description="加入你目前所在的語音頻道")
async def join(interaction: discord.Interaction):
    await interaction.response.defer()

    existing = _get_voice_client(interaction)
    if (
        existing is not None
        and interaction.user.voice
        and existing.channel.id == interaction.user.voice.channel.id
    ):
        await interaction.followup.send("已經在這個語音頻道了。")
        return

    vc, error = await _ensure_voice_client(interaction)
    if error:
        await interaction.followup.send(error)
        return

    await interaction.followup.send(f"已加入語音頻道：{vc.channel.name}")


@bot.tree.command(name="play", description="播放指定的音訊 URL")
@app_commands.describe(url="公開可存取的音訊檔案網址")
async def play(interaction: discord.Interaction, url: str):
    await interaction.response.defer()

    vc, error = await _ensure_voice_client(interaction)
    if error:
        await interaction.followup.send(error)
        return

    try:
        tracks = await wavelink.Playable.search(url)
    except Exception:
        logger.exception("Failed to resolve track from URL: %s", _redact_url(url))
        await interaction.followup.send("無法解析這個音訊網址，請確認是否為有效連結。")
        return

    if not tracks:
        logger.error("No playable track found for URL: %s", _redact_url(url))
        await interaction.followup.send("找不到可播放的音訊內容，請確認網址是否為有效的音訊檔案。")
        return

    track = tracks[0]

    try:
        await vc.play(track)
    except Exception:
        logger.exception("Failed to play track: %s", _redact_url(url))
        await interaction.followup.send("播放失敗，請稍後再試。")
        return

    logger.info("Playing track: %s (requested by %s, guild=%s)", track.title, interaction.user, interaction.guild.id)
    await interaction.followup.send(f"正在播放：{track.title}")


@bot.tree.command(name="pause", description="暫停目前播放")
async def pause(interaction: discord.Interaction):
    if interaction.guild is None:
        await interaction.response.send_message("此指令僅限在伺服器內使用。")
        return
    vc = _get_voice_client(interaction)
    if vc is None or not vc.playing:
        await interaction.response.send_message("目前沒有正在播放的音訊。")
        return
    await vc.pause(True)
    logger.info("Paused playback (guild=%s)", interaction.guild.id)
    await interaction.response.send_message("已暫停播放。")


@bot.tree.command(name="resume", description="繼續播放")
async def resume(interaction: discord.Interaction):
    if interaction.guild is None:
        await interaction.response.send_message("此指令僅限在伺服器內使用。")
        return
    vc = _get_voice_client(interaction)
    if vc is None or not vc.paused:
        await interaction.response.send_message("目前沒有暫停中的音訊。")
        return
    await vc.pause(False)
    logger.info("Resumed playback (guild=%s)", interaction.guild.id)
    await interaction.response.send_message("已繼續播放。")


@bot.tree.command(name="stop", description="停止播放")
async def stop(interaction: discord.Interaction):
    if interaction.guild is None:
        await interaction.response.send_message("此指令僅限在伺服器內使用。")
        return
    vc = _get_voice_client(interaction)
    if vc is None:
        await interaction.response.send_message("目前沒有連接語音頻道。")
        return
    await vc.stop()
    logger.info("Stopped playback (guild=%s)", interaction.guild.id)
    await interaction.response.send_message("已停止播放。")


@bot.tree.command(name="leave", description="離開語音頻道")
async def leave(interaction: discord.Interaction):
    if interaction.guild is None:
        await interaction.response.send_message("此指令僅限在伺服器內使用。")
        return
    vc = _get_voice_client(interaction)
    if vc is None:
        await interaction.response.send_message("目前沒有連接語音頻道。")
        return
    channel_name = vc.channel.name
    await vc.disconnect()
    logger.info("Left voice channel: %s (guild=%s)", channel_name, interaction.guild.id)
    await interaction.response.send_message("已離開語音頻道。")


def main():
    if not TOKEN:
        logger.error("DISCORD_TOKEN not set. Please fill it in .env")
        return
    if not LAVALINK_PASSWORD:
        logger.error("LAVALINK_PASSWORD not set. Please fill it in .env")
        return
    bot.run(TOKEN, log_handler=None)


if __name__ == "__main__":
    main()
