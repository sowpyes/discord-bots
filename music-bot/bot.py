import asyncio
import logging
import os
from logging.handlers import RotatingFileHandler
from urllib.parse import parse_qs, urlparse

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

QUEUE_MAX_SIZE = 50

YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be", "www.youtu.be"}
ALLOWED_URL_SCHEMES = {"http", "https"}
MAX_SEARCH_QUERY_LENGTH = 200
MAX_SEARCH_TERM_DISPLAY_LENGTH = 80

_SOURCE_LABELS = {"youtube": "YouTube", "http": "HTTP"}


class PlayInputError(Exception):
    """Raised for /play input that must be rejected before ever reaching Lavalink."""

    def __init__(self, user_message: str):
        self.user_message = user_message
        super().__init__(user_message)


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

# Keyed by guild id (not attached to the Player) so a guild always gets the
# same lock across reconnects. Guards queue get / play next / skip / track_end
# advance so at most one of them can be mutating a given guild's queue+player
# at a time.
_guild_locks: dict[int, asyncio.Lock] = {}


def _get_lock(guild_id: int) -> asyncio.Lock:
    lock = _guild_locks.get(guild_id)
    if lock is None:
        lock = asyncio.Lock()
        _guild_locks[guild_id] = lock
    return lock


def clear_player_state(guild_id: int) -> None:
    """Drop all auxiliary per-guild state (currently just the advance lock)."""
    _guild_locks.pop(guild_id, None)


def format_duration(milliseconds: int) -> str:
    total_seconds = max(0, milliseconds) // 1000
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def format_track(track: wavelink.Playable) -> str:
    duration = "直播／未知" if track.is_stream else format_duration(track.length)
    source_label = _SOURCE_LABELS.get(track.source, track.source)
    return f"{track.title} - {track.author} ({duration}) [{source_label}]"


async def play_next(player: wavelink.Player, reason: str) -> wavelink.Playable | None:
    """Pop the next track off this guild's queue and play it, or stop if empty.

    This is the only path allowed to advance playback for a guild -- the
    natural track_end handler, /skip, and the exception/stuck handlers all
    route through here instead of calling player.play()/player.stop()
    directly, so two triggers firing close together can't both start a track.
    """
    guild_id = player.guild.id
    async with _get_lock(guild_id):
        if player.queue.is_empty:
            try:
                await player.stop()
            except Exception:
                logger.exception(
                    "Failed to stop player after empty queue (guild=%s, reason=%s)", guild_id, reason
                )
            logger.info("Queue empty, stopped (guild=%s, reason=%s)", guild_id, reason)
            return None

        next_track = player.queue.get()
        try:
            await player.play(next_track)
        except Exception:
            logger.exception("Failed to play next track (guild=%s, reason=%s)", guild_id, reason)
            return None

        logger.info(
            "Advanced to next track (guild=%s, reason=%s): %s", guild_id, reason, next_track.title
        )
        return next_track


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

    if payload.player is None:
        return

    # Lavalink v4 sends lowerCamelCase reason strings: "finished", "stopped",
    # "replaced", "loadFailed", "cleanup". Only a natural finish should
    # auto-advance here -- manual stop leaves the queue cleared beforehand,
    # and /skip drives its own transition via play_next() directly, so both
    # end up with a non-"finished" reason and this handler correctly no-ops.
    if payload.reason == "finished":
        await play_next(payload.player, "finished")


@bot.event
async def on_wavelink_track_exception(payload: wavelink.TrackExceptionEventPayload):
    logger.error(
        "Track exception: %s - %s",
        payload.track.title if payload.track else "unknown",
        payload.exception,
    )
    if payload.player is not None:
        await play_next(payload.player, "exception")


@bot.event
async def on_wavelink_track_stuck(payload: wavelink.TrackStuckEventPayload):
    logger.error(
        "Track stuck: %s (threshold=%dms)",
        payload.track.title if payload.track else "unknown",
        payload.threshold,
    )
    if payload.player is not None:
        await play_next(payload.player, "stuck")


def _get_voice_client(interaction: discord.Interaction) -> wavelink.Player | None:
    return interaction.guild.voice_client if interaction.guild else None


def _redact_url(url: str) -> str:
    try:
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}/***"
    except Exception:
        return "<unparseable-url>"


def _clean_search_term(text: str, limit: int = MAX_SEARCH_TERM_DISPLAY_LENGTH) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) > limit:
        return collapsed[: limit - 1] + "…"
    return collapsed


def _classify_play_input(raw: str) -> tuple[str, str]:
    """Returns (kind, value) where kind is "youtube_url", "url", or "search".

    Raises PlayInputError for input that must never reach Lavalink: empty
    input, disallowed URL schemes, YouTube playlist URLs, oversized search text.
    """
    text = raw.strip()
    if not text:
        raise PlayInputError("請輸入音訊網址、YouTube 網址或搜尋關鍵字。")

    parsed = urlparse(text)
    if parsed.scheme and parsed.scheme not in ALLOWED_URL_SCHEMES:
        raise PlayInputError(f"不支援的網址格式(scheme={parsed.scheme})，請提供 http/https 網址或搜尋關鍵字。")

    host = (parsed.hostname or "").lower()

    if parsed.scheme in ALLOWED_URL_SCHEMES and host in YOUTUBE_HOSTS:
        if parsed.path == "/playlist" or "list" in parse_qs(parsed.query):
            raise PlayInputError("目前版本尚未支援 YouTube 播放清單。")
        return "youtube_url", text

    if parsed.scheme in ALLOWED_URL_SCHEMES and host:
        return "url", text

    if len(text) > MAX_SEARCH_QUERY_LENGTH:
        raise PlayInputError(
            f"搜尋關鍵字長度 {len(text)} 超過上限 {MAX_SEARCH_QUERY_LENGTH} 字元，請縮短後再試。"
        )
    return "search", text


def _describe_play_source(kind: str, value: str) -> str:
    """A log-safe description: hostname + a short id prefix for URLs, cleaned/
    truncated text for search -- never a full URL query, token, or password."""
    if kind == "search":
        return f"search:{_clean_search_term(value, limit=80)}"

    parsed = urlparse(value)
    if kind == "youtube_url":
        video_id = parse_qs(parsed.query).get("v", [None])[0]
        if not video_id and parsed.hostname in {"youtu.be", "www.youtu.be"}:
            video_id = parsed.path.lstrip("/").split("/")[0]
        return f"youtube host={parsed.hostname} id_prefix={(video_id or '')[:6]}"

    return _redact_url(value)


def _classify_load_error(kind: str, exc: "wavelink.LavalinkLoadException") -> str:
    """Maps a Lavalink load error to one of the required user-facing categories.

    Keyword matching against Lavalink/youtube-source's error+cause text is
    best-effort -- exact wording isn't guaranteed across plugin versions, so
    this always has a distinct, non-generic fallback per input kind rather
    than collapsing everything into a single "cannot parse" message.
    """
    text = f"{exc.error} {exc.cause}".lower()

    if any(k in text for k in ("sign in", "not a bot", "not a robot", "confirm you")):
        return "YouTube 要求登入驗證或偵測為機器人操作，暫時無法播放，請稍後再試。"
    if "private" in text:
        return "這部影片為私人影片，無法播放。"
    if any(k in text for k in ("unavailable", "removed", "deleted", "no longer available")):
        return "這部影片不可用或已被移除。"
    if any(k in text for k in ("age restrict", "age-restrict", "confirm your age", "age verification")):
        return "這部影片有年齡限制，Bot 無法播放。"
    if ("region" in text or "country" in text) and "not available" in text:
        return "這部影片在目前地區無法播放。"
    if "source" in text and ("not available" in text or "unknown" in text or "no such" in text):
        return "YouTube 播放功能目前未就緒，請稍後再試或聯絡管理員。"

    if kind == "youtube_url":
        return "無法解析這個 YouTube 網址，請確認影片是否存在。"
    if kind == "search":
        return "找不到符合的搜尋結果，請換個關鍵字再試。"
    return "播放失敗，請稍後再試。"


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


async def _require_same_channel(
    interaction: discord.Interaction,
) -> tuple[wavelink.Player | None, str | None]:
    """Returns (player, error_message) for commands that require the invoking
    user to be in the same voice channel as the bot: /skip, /stop, /leave."""
    if interaction.guild is None:
        return None, "此指令僅限在伺服器內使用。"

    vc = _get_voice_client(interaction)
    if vc is None:
        return None, "目前沒有連接語音頻道。"

    if (
        not interaction.user.voice
        or not interaction.user.voice.channel
        or interaction.user.voice.channel.id != vc.channel.id
    ):
        return None, "請先加入 Bot 所在的語音頻道再使用此指令。"

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


@bot.tree.command(name="play", description="播放直接音訊網址、YouTube 網址或搜尋關鍵字")
@app_commands.describe(url="公開音訊網址、YouTube 網址，或想搜尋的關鍵字")
async def play(interaction: discord.Interaction, url: str):
    await interaction.response.defer()

    vc, error = await _ensure_voice_client(interaction)
    if error:
        await interaction.followup.send(error)
        return

    try:
        kind, value = _classify_play_input(url)
    except PlayInputError as exc:
        await interaction.followup.send(exc.user_message)
        return

    source_desc = _describe_play_source(kind, value)

    try:
        if kind == "search":
            result = await wavelink.Playable.search(value, source=wavelink.TrackSource.YouTube)
        else:
            result = await wavelink.Playable.search(value)
    except wavelink.LavalinkLoadException as exc:
        logger.error(
            "Failed to load track (kind=%s, source=%s): error=%s severity=%s cause=%s",
            kind, source_desc, exc.error, exc.severity, exc.cause,
        )
        await interaction.followup.send(_classify_load_error(kind, exc))
        return
    except Exception:
        logger.exception("Unexpected error loading track (kind=%s, source=%s)", kind, source_desc)
        await interaction.followup.send("發生未預期的錯誤，請稍後再試。")
        return

    if isinstance(result, wavelink.Playlist):
        await interaction.followup.send("目前版本尚未支援 YouTube 播放清單。")
        return

    if not result:
        logger.error("No playable track found (kind=%s, source=%s)", kind, source_desc)
        if kind == "search":
            await interaction.followup.send("找不到符合的搜尋結果，請換個關鍵字再試。")
        elif kind == "youtube_url":
            await interaction.followup.send("無法解析這個 YouTube 網址，請確認影片是否存在。")
        else:
            await interaction.followup.send("找不到可播放的音訊內容，請確認網址是否為有效的音訊檔案。")
        return

    track = result[0]
    search_term_line = f"\n搜尋詞：{_clean_search_term(value)}" if kind == "search" else ""

    async with _get_lock(interaction.guild.id):
        if vc.current is None:
            try:
                await vc.play(track)
            except Exception:
                logger.exception("Failed to play track (kind=%s, source=%s)", kind, source_desc)
                await interaction.followup.send("播放失敗，請稍後再試。")
                return
            logger.info(
                "Playing track: %s [%s] (requested by %s, guild=%s)",
                track.title, track.source, interaction.user, interaction.guild.id,
            )
            await interaction.followup.send(f"正在播放：{format_track(track)}{search_term_line}")
            return

        if vc.queue.count >= QUEUE_MAX_SIZE:
            await interaction.followup.send(f"佇列已滿(上限 {QUEUE_MAX_SIZE} 首)，請稍後再試。")
            return

        vc.queue.put(track)
        position = vc.queue.count
        logger.info(
            "Queued track at position %d: %s [%s] (requested by %s, guild=%s)",
            position, track.title, track.source, interaction.user, interaction.guild.id,
        )
        await interaction.followup.send(f"已加入佇列第 {position} 位：{format_track(track)}{search_term_line}")


@bot.tree.command(name="queue", description="顯示目前播放佇列")
async def queue_cmd(interaction: discord.Interaction):
    if interaction.guild is None:
        await interaction.response.send_message("此指令僅限在伺服器內使用。")
        return

    vc = _get_voice_client(interaction)
    if vc is None or (vc.current is None and vc.queue.is_empty):
        await interaction.response.send_message("目前沒有播放中的曲目，佇列也是空的。")
        return

    embed = discord.Embed(title="播放佇列")
    embed.add_field(
        name="正在播放",
        value=format_track(vc.current) if vc.current is not None else "(無)",
        inline=False,
    )

    upcoming = vc.queue[:10]
    if upcoming:
        lines = [f"{i}. {format_track(t)}" for i, t in enumerate(upcoming, start=1)]
        embed.add_field(name="接下來", value="\n".join(lines), inline=False)
    else:
        embed.add_field(name="接下來", value="(佇列是空的)", inline=False)

    embed.add_field(name="總排隊數", value=str(vc.queue.count), inline=True)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="nowplaying", description="顯示目前播放曲目資訊")
async def nowplaying(interaction: discord.Interaction):
    if interaction.guild is None:
        await interaction.response.send_message("此指令僅限在伺服器內使用。")
        return

    vc = _get_voice_client(interaction)
    if vc is None or vc.current is None:
        await interaction.response.send_message("目前沒有播放中的曲目。")
        return

    track = vc.current
    if track.is_stream:
        progress = "直播／未知"
    else:
        progress = f"{format_duration(vc.position)} / {format_duration(track.length)}"

    embed = discord.Embed(title="目前播放")
    embed.add_field(name="標題", value=track.title, inline=False)
    embed.add_field(name="作者", value=track.author, inline=False)
    embed.add_field(name="進度", value=progress, inline=True)
    embed.add_field(name="狀態", value="已暫停" if vc.paused else "播放中", inline=True)
    embed.add_field(name="佇列數量", value=str(vc.queue.count), inline=True)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="skip", description="跳過目前曲目")
async def skip(interaction: discord.Interaction):
    vc, error = await _require_same_channel(interaction)
    if error:
        await interaction.response.send_message(error)
        return

    if vc.current is None:
        await interaction.response.send_message("目前沒有播放中的曲目可跳過。")
        return

    skipped_title = vc.current.title
    next_track = await play_next(vc, "skip")
    logger.info("Skipped by %s (guild=%s): %s", interaction.user, interaction.guild.id, skipped_title)

    if next_track is not None:
        await interaction.response.send_message(f"已跳過，正在播放：{format_track(next_track)}")
    else:
        await interaction.response.send_message("已跳過，佇列已空。")


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


@bot.tree.command(name="stop", description="停止播放並清空佇列")
async def stop(interaction: discord.Interaction):
    vc, error = await _require_same_channel(interaction)
    if error:
        await interaction.response.send_message(error)
        return

    vc.queue.clear()
    try:
        await vc.stop()
    except Exception:
        logger.exception("Failed to stop playback (guild=%s)", interaction.guild.id)
        await interaction.response.send_message("停止播放時發生錯誤，請稍後再試。")
        return

    logger.info("Stopped playback and cleared queue (guild=%s)", interaction.guild.id)
    await interaction.response.send_message("已停止播放並清空佇列。")


@bot.tree.command(name="leave", description="離開語音頻道")
async def leave(interaction: discord.Interaction):
    vc, error = await _require_same_channel(interaction)
    if error:
        await interaction.response.send_message(error)
        return

    guild_id = interaction.guild.id
    channel_name = vc.channel.name
    vc.queue.clear()
    try:
        await vc.stop()
    except Exception:
        logger.exception("Failed to stop playback before leaving (guild=%s)", guild_id)
    try:
        await vc.disconnect()
    except Exception:
        logger.exception("Failed to disconnect voice client (guild=%s)", guild_id)
        await interaction.response.send_message("離開語音頻道時發生錯誤，請稍後再試。")
        return

    clear_player_state(guild_id)
    logger.info("Left voice channel: %s (guild=%s)", channel_name, guild_id)
    await interaction.response.send_message("已離開語音頻道，佇列已清空。")


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
