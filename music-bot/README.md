# 音樂 Bot

獨立的 Discord 音樂機器人，使用 discord.py + Wavelink + Lavalink。

與 `drawing-bot` 完全獨立：不同 Discord Application、不同 Token、獨立 `.venv`、獨立設定與日誌。

## v0.1 範圍

- 加入／離開語音頻道
- 透過 Lavalink 播放公開 HTTPS 直接音訊 URL(尚未支援 YouTube 搜尋)
- 指令：`/play <url>`、`/pause`、`/resume`、`/stop`、`/leave`

YouTube 搜尋將在確認語音播放鏈穩定後，透過 Lavalink 的 `youtube-source` 插件加入，不使用已棄用的內建 YouTube Source。

## 前置需求

- Java 17 以上(執行 Lavalink 用)
- Lavalink.jar(從官方 GitHub Releases 下載：https://github.com/lavalink-devs/Lavalink/releases)

## 安裝

```bash
cd music-bot
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## 設定

1. 複製 `.env.example` 為 `.env`，填入這隻 Bot 專屬的 Discord Token 與 Lavalink 密碼：

```
DISCORD_TOKEN=你的音樂bot token
LAVALINK_URI=http://127.0.0.1:2333
LAVALINK_PASSWORD=與application.yml中相同的密碼
```

2. 複製 `lavalink/application.yml.example` 為 `lavalink/application.yml`，修改 `lavalink.server.password` 為一組密碼，並確保與 `.env` 的 `LAVALINK_PASSWORD` 一致。

## 執行

先啟動 Lavalink(需要 Java)：

```bash
cd lavalink
java -jar Lavalink.jar
```

確認看到 Lavalink 啟動完成訊息後，再啟動 Bot：

```bash
python bot.py
```

## 目錄說明

- `bot.py`：主程式
- `lavalink/`：Lavalink 伺服器設定與執行檔(`.jar` 與 `application.yml` 已加入 .gitignore，不進版控)
- `logs/`：執行日誌(自動產生，已加入 .gitignore)
