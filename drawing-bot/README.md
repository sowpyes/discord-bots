# 繪圖 Bot

獨立的 Discord 繪圖機器人，使用 discord.py + Pollinations.ai 圖片生成 API。

## 安裝

```bash
cd drawing-bot
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## 設定

複製 `.env.example` 為 `.env`，填入自己的 Discord Bot Token：

```
DISCORD_TOKEN=你的token
```

## 執行

```bash
python bot.py
```

## 指令

- `/draw <prompt>`：輸入文字描述，生成一張圖片。

## 目錄說明

- `bot.py`：主程式
- `logs/`：執行日誌（自動產生，已加入 .gitignore）
- 此 Bot 與 `music-bot` 完全獨立，不共用 Token、設定或程式碼。
