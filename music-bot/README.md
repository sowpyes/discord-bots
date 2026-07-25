# 音樂 Bot

獨立的 Discord 音樂機器人，使用 discord.py + Wavelink + Lavalink。

與 `drawing-bot` 完全獨立：不同 Discord Application、不同 Token、獨立 `.venv`、獨立設定與日誌。

## v0.2 範圍

- 加入／離開語音頻道
- 透過 Lavalink 播放公開 HTTPS 直接音訊 URL(尚未支援 YouTube 搜尋)
- 每個 Guild 使用獨立的播放佇列與播放狀態，Guild 之間互不影響
- 曲目自然播放完畢時自動播放佇列中的下一首；佇列清空後維持語音連線，不會自動離開
- 佇列上限 50 首，超過會拒絕加入(不會無限制增長)
- `/stop`、`/leave` 會清空佇列並停止播放，不會接著自動播放下一首

指令：

- `/play <url>`：目前沒有播放中曲目時立即播放，否則加入佇列
- `/queue`：顯示目前播放曲目與接下來最多 10 首、總排隊數
- `/nowplaying`：顯示目前曲目、播放進度、暫停狀態、佇列數量
- `/skip`：跳過目前曲目，佇列有下一首則立即播放，否則停止
- `/pause`、`/resume`：暫停／繼續播放
- `/stop`：停止播放並清空佇列
- `/leave`：清空佇列、停止播放並離開語音頻道

`/skip`、`/stop`、`/leave` 需要與 Bot 在同一個語音頻道才能使用。

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
