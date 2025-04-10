import sqlite3
import random
import string
import aiohttp
import html
from aiogram import Bot, Dispatcher, types, Router
from aiogram.filters import Command
from aiogram.client.default import DefaultBotProperties
from aiogram.types import Message
import asyncio
import datetime
from config import BOT_TOKEN, ADMIN_ID, COC_API_KEY, BRAWL_API_KEY

# Initialize DB
conn = sqlite3.connect('database.sqlite')
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, expire_at TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS keys (key TEXT PRIMARY KEY, duration INTEGER, created_by INTEGER, used_by TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS player_info (tag TEXT PRIMARY KEY, creation_date TEXT, last_seen TEXT, devices TEXT, transactions TEXT, telegram_user_id INTEGER)''')
conn.commit()

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()
router = Router()
dp.include_router(router)

# Clash of Clans API Wrapper
class CoCAPI:
    def __init__(self, api_key):
        self.base_url = "https://api.clashofclans.com/v1"
        self.headers = {"Authorization": f"Bearer {api_key}"}

    async def fetch_player(self, tag):
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
        return "Mobile (via Telegram) 📱"

# Brawl Stars API Wrapper
class BrawlAPI:
    def __init__(self, api_key):
        self.base_url = "https://api.brawlstars.com/v1"
        self.headers = {"Authorization": f"Bearer {api_key}"}

    async def fetch_player(self, tag):
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{self.base_url}/players/%23{tag.strip('#')}", headers=self.headers) as resp:
                data = await resp.json()
                if 'reason' in data:
                    return None, f"❌ Error: {data.get('message', 'Unknown error')}"
                return data, None

coc_api = CoCAPI(COC_API_KEY)
brawl_api = BrawlAPI(BRAWL_API_KEY)

# Helper functions
def generate_key():
    return "COC-" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

def add_user(user_id, duration):
    expire_at = datetime.datetime.utcnow() + duration
    c.execute('INSERT OR REPLACE INTO users (user_id, expire_at) VALUES (?, ?)', (user_id, expire_at.isoformat()))
    conn.commit()

# Handlers
@router.message(Command("start"))
async def start(message: Message):
    await message.answer("🎉 <b>Welcome to the CoC & Brawl Bot!</b> 🎉\nUse /help to see all commands or /redeem <code>key</code> to get started! 🚀")

@router.message(Command("help"))
async def help_command(message: Message):
    help_text = """
🌟 <b>CoC & Brawl Bot Commands</b> 🌟
/start - Kick things off! 🎉
/help - Show this menu 📜
/key [1hour|1day|3day|7day] - (Admin) Generate a key 🔑
/allkey - (Admin) Show all keys and usage 📋
/redeem <code>key</code> - Activate your access 🎟️
/info - Check your access status ⏳
/check <code>player_tag</code> - Get CoC player stats 📊
/check_bs <code>player_tag</code> - Get Brawl Stars player stats 🎮
/brawler <code>player_tag</code> - Get Brawl Stars brawler summary ⭐
/linktag <code>player_tag</code> - Link your CoC tag to Telegram 🔗
/setdevice <code>player_tag</code> <code>device</code> - Update your device info 📱
/addinfo <code>tag</code> <code>creation_date</code> <code>last_seen</code> <code>devices</code> <code>transactions</code> - (Admin) Add player data ✍️
/updateinfo <code>tag</code> <code>field</code> <code>new_value</code> - (Admin) Edit player data 🔧
/removeinfo <code>tag</code> - (Admin) Delete player data 🗑️
/viewinfo <code>tag</code> - (Admin) View player data 👀
"""
    await message.answer(help_text)

@router.message(Command("key"))
async def keygen(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()[1:]
    if not args or args[0] not in ['1hour', '1day', '3day', '7day']:
        await message.answer("⚠️ Usage: /key 1hour | 1day | 3day | 7day")
        return
    duration_map = {'1hour': datetime.timedelta(hours=1), '1day': datetime.timedelta(days=1), 
                    '3day': datetime.timedelta(days=3), '7day': datetime.timedelta(days=7)}
    key = generate_key()
    c.execute('INSERT INTO keys (key, duration, created_by, used_by) VALUES (?, ?, ?, ?)', 
              (key, duration_map[args[0]].total_seconds() / 3600, message.from_user.id, ''))
    conn.commit()
    c.execute('SELECT used_by FROM keys WHERE key=?', (key,))
    used_by = c.fetchone()[0].split(',') if c.fetchone()[0] else []
    await message.answer(f"✅ <b>Key Generated!</b> 🔑\n<code>{key}</code>\nValid for: {args[0]}\nUsers Redeemed: {len(used_by)} 👥")

@router.message(Command("allkey"))
async def all_keys(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    c.execute('SELECT key, duration, used_by FROM keys')
    keys = c.fetchall()
    if not keys:
        await message.answer("❌ <b>No keys found!</b>")
        return
    response = "📋 <b>All Generated Keys</b> 📋\n"
    for key, duration, used_by in keys:
        users = used_by.split(',') if used_by else []
        duration_str = f"{int(duration)} hour{'s' if int(duration) != 1 else ''}"
        response += f"<code>{key}</code> - {duration_str}, Users: {len(users)} 👥\n"
    await message.answer(response)

@router.message(Command("redeem"))
async def redeem(message: Message):
    args = message.text.split()[1:]
    if not args:
        await message.answer("⚠️ Usage: /redeem <code>key</code>")
        return
    key = args[0]
    c.execute('SELECT key, duration, used_by FROM keys WHERE key=?', (key,))
    row = c.fetchone()
    if not row:
        await message.answer("❌ <b>Invalid key!</b>")
        return
    used_by = row[2].split(',') if row[2] else []
    if str(message.from_user.id) in used_by:
        await message.answer("❌ <b>You already used this key!</b>")
        return
    duration = datetime.timedelta(hours=row[1])
    add_user(message.from_user.id, duration)
    used_by.append(str(message.from_user.id))
    c.execute('UPDATE keys SET used_by=? WHERE key=?', (','.join(used_by), key))
    conn.commit()
    expire_at = datetime.datetime.utcnow() + duration
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
            await message.answer("❌ <b>Access Expired!</b> Use /redeem <code>key</code> to renew.")
    else:
        await message.answer("❌ <b>No Access!</b> Use /redeem <code>key</code> to activate.")

@router.message(Command("linktag"))
async def link_tag(message: Message):
    c.execute('SELECT expire_at FROM users WHERE user_id=?', (message.from_user.id,))
    row = c.fetchone()
    if not row or datetime.datetime.fromisoformat(row[0]) < datetime.datetime.utcnow():
        await message.answer("❌ <b>No Access!</b> Use /redeem <code>key</code>")
        return
    args = message.text.split()[1:]
    if not args:
        await message.answer("⚠️ Usage: /linktag <code>player_tag</code>")
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
        await message.answer("❌ <b>No Access!</b> Use /redeem <code>key</code>")
        return
    args = message.text.split()[1:]
    if len(args) < 2:
        await message.answer("⚠️ Usage: /setdevice <code>player_tag</code> <code>device</code>")
        return
    tag, device = args[0], " ".join(args[1:])
    c.execute('UPDATE player_info SET devices=? WHERE tag=? AND telegram_user_id=?', 
              (device, tag, message.from_user.id))
    if c.rowcount > 0:
        conn.commit()
        await message.answer(f"📱 <b>Device Updated!</b> ✅\nTag: {tag}\nNew Device: {device}")
    else:
        await message.answer(f"❌ <b>Tag {tag} not linked to you!</b> Use /linktag <code>player_tag</code> first.")

@router.message(Command("check"))
async def check_player(message: Message):
    c.execute('SELECT expire_at FROM users WHERE user_id=?', (message.from_user.id,))
    row = c.fetchone()
    if not row or datetime.datetime.fromisoformat(row[0]) < datetime.datetime.utcnow():
        await message.answer("❌ <b>No Access!</b> Use /redeem <code>key</code>")
        return
    args = message.text.split()[1:]
    if not args:
        await message.answer("⚠️ Usage: /check <code>player_tag</code>")
        return
    tag = args[0]
    data, error = await coc_api.fetch_player(tag)
    c.execute('SELECT creation_date, last_seen, devices, transactions, telegram_user_id FROM player_info WHERE tag=?', (tag,))
    secret_info = c.fetchone()
    if not data:
        await message.answer(error or "❌ <b>Player Not Found!</b>\nCheck the tag and try again. 🏷️")
        return
    safe_name = html.escape(data.get('name', 'Unknown'))
    response = f"🏰 <b>{safe_name}'s CoC Profile</b> 🏰\n"
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

@router.message(Command("check_bs"))
async def check_brawl_player(message: Message):
    c.execute('SELECT expire_at FROM users WHERE user_id=?', (message.from_user.id,))
    row = c.fetchone()
    if not row or datetime.datetime.fromisoformat(row[0]) < datetime.datetime.utcnow():
        await message.answer("❌ <b>No Access!</b> Use /redeem <code>key</code>")
        return
    args = message.text.split()[1:]
    if not args:
        await message.answer("⚠️ Usage: /check_bs <code>player_tag</code>")
        return
    tag = args[0]
    data, error = await brawl_api.fetch_player(tag)
    if not data:
        await message.answer(error or "❌ <b>Player Not Found!</b>\nCheck the tag and try again. 🏷️")
        return
    safe_name = html.escape(data.get('name', 'Unknown'))
    response = f"🎮 <b>{safe_name}'s Brawl Stars Profile</b> 🎮\n"
    response += f"🏷️ <b>Tag:</b> {data.get('tag', tag)}\n"
    response += f"🏆 <b>Trophies:</b> {data.get('trophies', 'N/A')}\n"
    response += f"⭐ <b>3v3 Wins:</b> {data.get('3vs3Victories', 0)}\n"
    response += f"👤 <b>Solo Wins:</b> {data.get('soloVictories', 0)}\n"
    response += f"👥 <b>Duo Wins:</b> {data.get('duoVictories', 0)}\n"
    response += f"🏅 <b>Best Brawler Trophies:</b> {data.get('highestTrophies', 'N/A')}\n"
    await message.answer(response)

@router.message(Command("brawler"))
async def brawler_details(message: Message):
    c.execute('SELECT expire_at FROM users WHERE user_id=?', (message.from_user.id,))
    row = c.fetchone()
    if not row or datetime.datetime.fromisoformat(row[0]) < datetime.datetime.utcnow():
        await message.answer("❌ <b>No Access!</b> Use /redeem <code>key</code>")
        return
    args = message.text.split()[1:]
    if not args:
        await message.answer("⚠️ Usage: /brawler <code>player_tag</code>")
        return
    tag = args[0]
    data, error = await brawl_api.fetch_player(tag)
    if not data:
        await message.answer(error or "❌ <b>Player Not Found!</b>\nCheck the tag and try again. 🏷️")
        return
    safe_name = html.escape(data.get('name', 'Unknown'))
    brawlers = data.get('brawlers', [])
    total_brawlers = len(brawlers)
    total_star_powers = sum(len(b.get('starPowers', [])) for b in brawlers)
    total_gadgets = sum(len(b.get('gadgets', [])) for b in brawlers)
    response = f"⭐ <b>{safe_name}'s Brawler Summary</b> ⭐\n"
    response += f"👾 <b>Brawlers:</b> {total_brawlers}/91\n"
    response += f"🌟 <b>Total Star Powers:</b> {total_star_powers}\n"
    response += f"🔧 <b>Total Gadgets:</b> {total_gadgets}\n"
    await message.answer(response)

@router.message(Command("addinfo"))
async def addinfo(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()[1:]
    if len(args) < 5:
        await message.answer("⚠️ Usage: /addinfo <code>tag</code> <code>creation_date</code> <code>last_seen</code> <code>devices</code> <code>transactions</code>")
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
        await message.answer("⚠️ Usage: /updateinfo <code>tag</code> <code>field</code> <code>new_value</code>")
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
        await message.answer("⚠️ Usage: /removeinfo <code>tag</code>")
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
        await message.answer("⚠️ Usage: /viewinfo <code>tag</code>")
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