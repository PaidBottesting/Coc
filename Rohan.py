import sqlite3
import random
import string
import aiohttp
from aiogram import Bot, Dispatcher, types, Router
from aiogram.filters import Command
from aiogram.client.default import DefaultBotProperties
from aiogram.types import Message
import asyncio
import datetime
from config import BOT_TOKEN, ADMIN_ID, COC_API_KEY

# Initialize DB
conn = sqlite3.connect('database.sqlite')
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, expire_at TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS keys (key TEXT, duration INTEGER, created_by INTEGER, used_by INTEGER DEFAULT NULL)''')
c.execute('''CREATE TABLE IF NOT EXISTS player_info (tag TEXT PRIMARY KEY, creation_date TEXT, last_seen TEXT, devices TEXT, transactions TEXT, telegram_user_id INTEGER)''')
conn.commit()

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()
router = Router()
dp.include_router(router)

# Custom CoC API Wrapper
class CoCAPI:
    def __init__(self, api_key):
        self.base_url = "https://api.clashofclans.com/v1"
        self.headers = {"Authorization": f"Bearer {api_key}"}

    async def fetch_player(self, tag):
        """Fetch player data with error handling."""
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{self.base_url}/players/%23{tag.strip('#')}", headers=self.headers) as resp:
                data = await resp.json()
                if 'reason' in data:
                    return None, f"❌ Error: {data.get('message', 'Unknown error')}"
                return data, None

    def infer_last_seen(self, data):
        attack_wins = data.get('attackWins', 0)
        defense_wins = data.get('defenseWins', 0)
        donations = data.get('donations', 0)
        if attack_wins > 0 or donations > 0:
            return "Recently (this season) 🕒"
        elif defense_wins > 0:
            return "Active base, no attacks recently 🛡️"
        else:
            return "Inactive for a while (1+ months) 💤"

    def infer_device(self, message):
        return "Mobile (via Telegram) 📱"  # Could be expanded with more Telegram hints later

coc_api = CoCAPI(COC_API_KEY)

# Helper functions
def generate_key():
    return "COC-" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

def add_user(user_id, duration_days):
    expire_at = datetime.datetime.utcnow() + datetime.timedelta(days=duration_days)
    c.execute('INSERT OR REPLACE INTO users (user_id, expire_at) VALUES (?, ?)', (user_id, expire_at.isoformat()))
    conn.commit()

# Handlers
@router.message(Command("start"))
async def start(message: Message):
    await message.answer("🎉 <b>Welcome to the CoC Bot!</b> 🎉\nUse /help to see all commands or /redeem <key> to get started! 🚀")

@router.message(Command("help"))
async def help_command(message: Message):
    help_text = """
🌟 <b>CoC Bot Commands</b> 🌟
/start - Kick things off! 🎉
/help - Show this menu 📜
/key [1day|3day|7day] - (Admin) Generate a key 🔑
/redeem <key> - Activate your access 🎟️
/info - Check your access status ⏳
/check <player_tag> - Get player stats 📊
/linktag <player_tag> - Link your CoC tag to Telegram 🔗
/setdevice <player_tag> <device> - Update your device info 📱
/addinfo <tag> <creation_date> <last_seen> <devices> <transactions> - (Admin) Add player data ✍️
/updateinfo <tag> <field> <new_value> - (Admin) Edit player data 🔧
/removeinfo <tag> - (Admin) Delete player data 🗑️
/viewinfo <tag> - (Admin) View player data 👀
"""
    await message.answer(help_text)

@router.message(Command("key"))
async def keygen(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()[1:]
    if not args or args[0] not in ['1day', '3day', '7day']:
        await message.answer("⚠️ Usage: /key 1day | 3day | 7day")
        return
    duration_map = {'1day': 1, '3day': 3, '7day': 7}
    key = generate_key()
    c.execute('INSERT INTO keys (key, duration, created_by) VALUES (?, ?, ?)', (key, duration_map[args[0]], message.from_user.id))
    conn.commit()
    await message.answer(f"✅ <b>Key Generated!</b> 🔑\n<code>{key}</code>\nValid for: {args[0]} ⏳")

@router.message(Command("redeem"))
async def redeem(message: Message):
    args = message.text.split()[1:]
    if not args:
        await message.answer("⚠️ Usage: /redeem <key>")
        return
    key = args[0]
    c.execute('SELECT key, duration, used_by FROM keys WHERE key=?', (key,))
    row = c.fetchone()
    if not row:
        await message.answer("❌ <b>Invalid key!</b>")
        return
    if row[2]:
        await message.answer("❌ <b>Key already used!</b>")
        return
    add_user(message.from_user.id, row[1])
    c.execute('UPDATE keys SET used_by=? WHERE key=?', (message.from_user.id, key))
    conn.commit()
    expire_at = datetime.datetime.utcnow() + datetime.timedelta(days=row[1])
    await message.answer(f"🎉 <b>Redeemed!</b> ✅\nAccess valid until: {expire_at.strftime('%Y-%m-%d %H:%M UTC')} ⏰")

@router.message(Command("info"))
async def info(message: Message):
    c.execute('SELECT expire_at FROM users WHERE user_id=?', (message.from_user.id,))
    row = c.fetchone()
    if row:
        expire_at = datetime.datetime.fromisoformat(row[0])
        left = expire_at - datetime.datetime.utcnow()
        if left.total_seconds() > 0:
            await message.answer(f"👤 <b>User: @{message.from_user.username}</b>\n✅ Access Active\nExpires in: {left.days} days, {(left.seconds // 3600)} hours ⏳")
        else:
            await message.answer("❌ <b>Access Expired!</b> Use /redeem <key> to renew.")
    else:
        await message.answer("❌ <b>No Access!</b> Use /redeem <key> to activate.")

@router.message(Command("linktag"))
async def link_tag(message: Message):
    c.execute('SELECT expire_at FROM users WHERE user_id=?', (message.from_user.id,))
    row = c.fetchone()
    if not row or datetime.datetime.fromisoformat(row[0]) < datetime.datetime.utcnow():
        await message.answer("❌ <b>No Access!</b> Use /redeem <key>")
        return
    args = message.text.split()[1:]
    if not args:
        await message.answer("⚠️ Usage: /linktag <player_tag>")
        return
    tag = args[0]
    device = coc_api.infer_device(message)
    c.execute('INSERT OR REPLACE INTO player_info (tag, devices, telegram_user_id) VALUES (?, ?, ?)', 
              (tag, device, message.from_user.id))
    conn.commit()
    await message.answer(f"🔗 <b>Tag Linked!</b> ✅\nTag: {tag}\nDevice: {device}")

@router.message(Command("setdevice"))
async def set_device(message: Message):
    c.execute('SELECT expire_at FROM users WHERE user_id=?', (message.from_user.id,))
    row = c.fetchone()
    if not row or datetime.datetime.fromisoformat(row[0]) < datetime.datetime.utcnow():
        await message.answer("❌ <b>No Access!</b> Use /redeem <key>")
        return
    args = message.text.split()[1:]
    if len(args) < 2:
        await message.answer("⚠️ Usage: /setdevice <player_tag> <device>")
        return
    tag, device = args[0], " ".join(args[1:])
    c.execute('UPDATE player_info SET devices=? WHERE tag=? AND telegram_user_id=?', 
              (device, tag, message.from_user.id))
    if c.rowcount > 0:
        conn.commit()
        await message.answer(f"📱 <b>Device Updated!</b> ✅\nTag: {tag}\nNew Device: {device}")
    else:
        await message.answer(f"❌ <b>Tag {tag} not linked to you!</b> Use /linktag first.")

@router.message(Command("check"))
async def check_player(message: Message):
    c.execute('SELECT expire_at FROM users WHERE user_id=?', (message.from_user.id,))
    row = c.fetchone()
    if not row or datetime.datetime.fromisoformat(row[0]) < datetime.datetime.utcnow():
        await message.answer("❌ <b>No Access!</b> Use /redeem <key>")
        return
    args = message.text.split()[1:]
    if not args:
        await message.answer("⚠️ Usage: /check <player_tag>")
        return
    tag = args[0]
    data, error = await coc_api.fetch_player(tag)
    c.execute('SELECT creation_date, last_seen, devices, transactions, telegram_user_id FROM player_info WHERE tag=?', (tag,))
    secret_info = c.fetchone()
    if not data:
        await message.answer(error or "❌ <b>Player Not Found!</b>\nCheck the tag and try again. 🏷️")
        return
    response = f"🏰 <b>{data.get('name', 'Unknown')}'s Profile</b> 🏰\n"
    response += f"📊 <b>Level:</b> {data.get('expLevel', 'N/A')} | <b>TH:</b> {data.get('townHallLevel', 'N/A')}\n"
    response += f"🏷️ <b>Tag:</b> {data.get('tag', tag)}\n"
    response += f"🏆 <b>Trophies:</b> {data.get('trophies', 'N/A')}\n"
    response += f"⚔️ <b>Attack Wins:</b> {data.get('attackWins', 0)}\n"
    response += f"🛡️ <b>Defense Wins:</b> {data.get('defenseWins', 0)}\n"
    response += f"🎁 <b>Donations:</b> {data.get('donations', 0)}\n"
    response += f"⏰ <b>Last Seen:</b> {coc_api.infer_last_seen(data)}\n\n"
    if secret_info:
        response += "🔍 <b>Extra Info</b> 🔍\n"
        response += f"📅 <b>Created:</b> {secret_info[0] or 'N/A'}\n"
        response += f"⏰ <b>Manual Last Seen:</b> {secret_info[1] or 'N/A'}\n"
        response += f"📱 <b>Device:</b> {secret_info[2] or 'N/A'}"
        if secret_info[4] == message.from_user.id:
            response += " (Yours! 🔗)"
        response += f"\n💰 <b>Transactions:</b> {secret_info[3] or 'N/A'}"
    else:
        device = coc_api.infer_device(message)
        c.execute('INSERT OR REPLACE INTO player_info (tag, devices, telegram_user_id) VALUES (?, ?, ?)', 
                  (tag, device, message.from_user.id))
        conn.commit()
        response += f"ℹ️ <b>Auto-Linked!</b> Device: {device} (Yours! 🔗)"
    await message.answer(response)

@router.message(Command("addinfo"))
async def addinfo(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()[1:]
    if len(args) < 5:
        await message.answer("⚠️ Usage: /addinfo <tag> <creation_date> <last_seen> <devices> <transactions>")
        return
    c.execute('INSERT OR REPLACE INTO player_info (tag, creation_date, last_seen, devices, transactions) VALUES (?, ?, ?, ?, ?)', tuple(args[:5]))
    conn.commit()
    await message.answer("✅ <b>Info Added!</b>")

@router.message(Command("updateinfo"))
async def updateinfo(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()[1:]
    if len(args) < 3:
        await message.answer("⚠️ Usage: /updateinfo <tag> <field> <new_value>")
        return
    allowed_fields = ['creation_date', 'last_seen', 'devices', 'transactions']
    if args[1] not in allowed_fields:
        await message.answer(f"❌ <b>Invalid field!</b> Use: {', '.join(allowed_fields)}")
        return
    c.execute(f'UPDATE player_info SET {args[1]}=? WHERE tag=?', (args[2], args[0]))
    conn.commit()
    await message.answer("✅ <b>Info Updated!</b>")

@router.message(Command("removeinfo"))
async def removeinfo(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()[1:]
    if not args:
        await message.answer("⚠️ Usage: /removeinfo <tag>")
        return
    tag = args[0]
    c.execute('DELETE FROM player_info WHERE tag=?', (tag,))
    conn.commit()
    await message.answer("🗑️ <b>Info Removed!</b>")

@router.message(Command("viewinfo"))
async def viewinfo(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()[1:]
    if not args:
        await message.answer("⚠️ Usage: /viewinfo <tag>")
        return
    tag = args[0]
    c.execute('SELECT * FROM player_info WHERE tag=?', (tag,))
    row = c.fetchone()
    if row:
        await message.answer(f"👀 <b>Player Info</b>\nTag: {row[0]}\nCreated: {row[1]}\nLast Seen: {row[2]}\nDevices: {row[3]}\nTransactions: {row[4]}")
    else:
        await message.answer("❌ <b>No info found!</b>")

async def main():
    print("Bot starting...")
    try:
        await dp.start_polling(bot)
    finally:
        conn.close()

if __name__ == '__main__':
    asyncio.run(main())