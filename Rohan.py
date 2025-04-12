import sqlite3
import random
import string
import aiohttp
import html
import re
from aiogram import Bot, Dispatcher, types, Router
from aiogram.filters import Command
from aiogram.client.default import DefaultBotProperties
from aiogram.types import Message
import asyncio
import datetime
from config import BOT_TOKEN, ADMIN_ID, COC_API_KEY, BRAWL_API_KEY, CR_API_KEY

# Initialize DB
conn = sqlite3.connect('database.sqlite')
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, expire_at TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS keys (key TEXT PRIMARY KEY, duration INTEGER, max_users INTEGER, created_by INTEGER, used_by TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS player_info (tag TEXT PRIMARY KEY, creation_date TEXT, last_seen TEXT, devices TEXT, transactions TEXT, telegram_user_id INTEGER, obstacles TEXT, skins TEXT)''')
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
        # Gold Pass skin database (expanded)
        self.gold_pass_skins = {
            "gladiator queen": {"month": "2019-04", "hero": "Archer Queen"},
            "primal queen": {"month": "2020-04", "hero": "Archer Queen"},
            "clockwork queen": {"month": "2020-10", "hero": "Archer Queen"},
            "party queen": {"month": "2021-08", "hero": "Archer Queen"},
            "shadow queen": {"month": "2021-12", "hero": "Archer Queen"},
            "warrior queen": {"month": "2022-05", "hero": "Archer Queen"},
            "goblin queen": {"month": "2023-06", "hero": "Archer Queen"},
            "ice queen": {"month": "2023-12", "hero": "Archer Queen"},
            "clash-o-ween queen": {"month": "2024-10", "hero": "Archer Queen"},
            "snake queen": {"month": "2025-02", "hero": "Archer Queen"},
        }

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

    def estimate_creation_date(self, data, obstacles=None, skins=None):
        exp_level = data.get('expLevel', 1)
        th_level = data.get('townHallLevel', 1)
        trophies = data.get('trophies', 0)
        attack_wins = data.get('attackWins', 0)
        donations = data.get('donations', 0)

        # Obstacle-based dating
        if obstacles:
            for year in range(2012, 2026):
                if f"Clashmas Tree {year}" in obstacles:
                    return f"December {year} (confirmed by Clashmas Tree {year}) 🎄"
            for year in range(2014, 2026):
                if f"Anniversary Cake {year}" in obstacles:
                    return f"August {year} (confirmed by Anniversary Cake {year}) 🎂"

        # Skin-based dating
        if skins:
            earliest_month = None
            earliest_skin = None
            for skin in skins:
                skin = skin.lower().strip()
                if skin in self.gold_pass_skins:
                    skin_month = self.gold_pass_skins[skin]["month"]
                    skin_date = datetime.datetime.strptime(skin_month, "%Y-%m")
                    # Check for suspicious low level
                    if exp_level < 50 and skin_date < datetime.datetime(2020, 1, 1):
                        return f"{skin_month} (suspicious: {skin} skin with low level {exp_level}) ⚠️"
                    if not earliest_month or skin_date < datetime.datetime.strptime(earliest_month, "%Y-%m"):
                        earliest_month = skin_month
                        earliest_skin = skin
            if earliest_month:
                return f"{earliest_month} (confirmed by {earliest_skin} skin) 👑"

        # Heuristic for old accounts
        is_old_active = (exp_level > 180 and 
                         th_level >= 13 and 
                         (trophies >= 4000 or (attack_wins < 100 and donations < 100)))
        if is_old_active:
            return "Approx. December 2012–2015 (high-level active old account) 🏛️"

        # Detect rushers
        is_rusher = (exp_level > 150 and th_level >= 14 and trophies < 3000)

        # Non-linear estimate
        if is_rusher:
            months = th_level * 3
        else:
            if exp_level <= 50:
                months = exp_level * 0.5
            elif exp_level <= 100:
                months = 25 + (exp_level - 50)
            else:
                months = 75 + (exp_level - 100) * 1.1

        # Cap by TH release dates
        th_release_dates = {
            16: datetime.datetime(2023, 12, 1),
            15: datetime.datetime(2022, 10, 1),
            14: datetime.datetime(2021, 4, 1),
            13: datetime.datetime(2019, 12, 1),
            12: datetime.datetime(2018, 6, 1),
        }
        for th, release_date in th_release_dates.items():
            if th_level >= th:
                estimated_date = datetime.datetime.utcnow() - datetime.timedelta(days=months * 30)
                if estimated_date < release_date:
                    estimated_date = release_date + datetime.timedelta(days=30)
                return estimated_date.strftime('%Y-%m-%d') + f" (estimated, level {exp_level}/TH{th_level})"

        estimated_date = datetime.datetime.utcnow() - datetime.timedelta(days=months * 30)
        if estimated_date < datetime.datetime(2012, 8, 2):
            estimated_date = datetime.datetime(2012, 8, 2)
        return estimated_date.strftime('%Y-%m-%d') + f" (estimated, level {exp_level}/TH{th_level})"

    def infer_transactions(self, data, skins=None):
        gems = data.get('gems', 0)
        builder_huts = data.get('builderHuts', 5) if 'builderHuts' in data else 5
        season_pass = 'seasonPass' in data and data['seasonPass'].get('tier', 0) > 0
        transactions = []

        if season_pass:
            transactions.append("Active Gold Pass detected 🏅")
        if gems > 1000 or builder_huts > 5:
            transactions.append("Possible purchase (high gems or 6th builder) 💰")
        if skins:
            for skin in skins:
                skin = skin.lower().strip()
                if skin in self.gold_pass_skins:
                    skin_month = self.gold_pass_skins[skin]["month"]
                    transactions.append(f"Past Gold Pass or gem purchase ({skin}, {skin_month}) 👑")
        
        return ", ".join(transactions) if transactions else "No transaction was applied"

# Brawl Stars and Clash Royale API Wrappers
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

class ClashRoyaleAPI:
    def __init__(self, api_key):
        self.base_url = "https://api.clashroyale.com/v1"
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
clash_royale_api = ClashRoyaleAPI(CR_API_KEY)

# Helper function to guess country by name
def guess_country_by_name(name):
    name_lower = name.lower().strip()
    if re.search(r'[\u4e00-\u9fff]', name):
        return "China 🇨🇳 (based on name)"
    indian_names = {'rohan', 'aryan', 'priya', 'rahul', 'neha', 'vikram', 'ananya'}
    for indian in indian_names:
        if indian in name_lower:
            return "India 🇮🇳 (based on name)"
    return "Unknown 🌐"

# Helper functions
def generate_key():
    return "COC-" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

def add_user(user_id, duration):
    expire_at = datetime.datetime.utcnow() + duration
    c.execute('INSERT OR REPLACE INTO users (user_id, expire_at) VALUES (?, ?)', (user_id, expire_at.isoformat()))
    conn.commit()

# Handlers
@router.message(Command("skin"))
async def set_skins(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ <b>Admin-only command!</b>")
        return
    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        await message.answer("⚠️ Usage: /skin player_tag skin1,skin2,...")
        return
    tag = args[1]
    skins = args[2].split(',')
    valid_skins = []
    invalid_skins = []

    # Validate skins
    for skin in skins:
        skin = skin.lower().strip()
        if skin in coc_api.gold_pass_skins:
            valid_skins.append(skin)
        else:
            invalid_skins.append(skin)

    if not valid_skins:
        await message.answer(f"❌ <b>No valid skins provided!</b> Invalid: {', '.join(invalid_skins)}")
        return

    skins_str = ','.join(valid_skins)
    c.execute('UPDATE player_info SET skins=? WHERE tag=?', (skins_str, tag))
    if c.rowcount == 0:
        c.execute('INSERT INTO player_info (tag, skins, telegram_user_id) VALUES (?, ?, ?)', 
                  (tag, skins_str, message.from_user.id))
    conn.commit()

    response = f"✅ <b>Skins Set for {tag}</b> 👑\nSkins: {', '.join(valid_skins)}"
    if invalid_skins:
        response += f"\n⚠️ Ignored invalid skins: {', '.join(invalid_skins)}"
    await message.answer(response)

@router.message(Command("check"))
async def check_player(message: Message):
    c.execute('SELECT expire_at FROM users WHERE user_id=?', (message.from_user.id,))
    row = c.fetchone()
    if not row or datetime.datetime.fromisoformat(row[0]) < datetime.datetime.utcnow():
        await message.answer("❌ <b>No Access!</b> Use /redeem key")
        return
    args = message.text.split(maxsplit=2)
    if len(args) < 2:
        await message.answer("⚠️ Usage: /check player_tag [obstacles]")
        return
    tag = args[1]
    obstacles = args[2].split(',') if len(args) > 2 else []

    data, error = await coc_api.fetch_player(tag)
    c.execute('SELECT creation_date, last_seen, devices, transactions, telegram_user_id, obstacles, skins FROM player_info WHERE tag=?', (tag,))
    secret_info = c.fetchone()
    if not data:
        await message.answer(error or "❌ <b>Player Not Found!</b>")
        return

    safe_name = html.escape(data.get('name', 'Unknown'))
    region = "Unknown 🌐"
    if 'clan' in data and 'location' in data['clan']:
        region = html.escape(data['clan']['location'].get('name', 'Unknown')) + " 🌍"
    possible_country = guess_country_by_name(data.get('name', ''))

    # Update player info
    devices = secret_info[2] if secret_info else coc_api.infer_device(message)
    last_seen = secret_info[1] if secret_info else coc_api.infer_last_seen(data)
    stored_obstacles = secret_info[5].split(',') if secret_info and secret_info[5] else []
    stored_skins = secret_info[6].split(',') if secret_info and secret_info[6] else []
    if obstacles:
        stored_obstacles = list(set(stored_obstacles + obstacles))
    obstacles_str = ','.join(stored_obstacles) if stored_obstacles else None
    skins_str = ','.join(stored_skins) if stored_skins else None
    transactions = coc_api.infer_transactions(data, stored_skins)

    c.execute('INSERT OR REPLACE INTO player_info (tag, creation_date, last_seen, devices, transactions, telegram_user_id, obstacles, skins) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
              (tag, None, last_seen, devices, transactions, message.from_user.id, obstacles_str, skins_str))
    conn.commit()

    response = f"🏰 <b>{safe_name}'s CoC Profile</b> 🏰\n"
    response += f"📊 <b>Level:</b> {data.get('expLevel', 'N/A')} | <b>TH:</b> {data.get('townHallLevel', 'N/A')}\n"
    response += f"🏷️ <b>Tag:</b> {data.get('tag', tag)}\n"
    response += f"🌐 <b>Region:</b> {region}\n"
    response += f"🇳 <b>Possible Country:</b> {possible_country}\n"
    response += f"🏆 <b>Trophies:</b> {data.get('trophies', 'N/A')}\n"
    response += f"⚔️ <b>Attack Wins:</b> {data.get('attackWins', 0)}\n"
    response += f"🛡️ <b>Defense Wins:</b> {data.get('defenseWins', 0)}\n"
    response += f"🎁 <b>Donations:</b> {data.get('donations', 0)}\n"
    response += f"⏰ <b>Last Seen:</b> {last_seen}\n\n"
    response += "🔍 <b>Extra Info</b> 🔍\n"
    response += f"📅 <b>Created:</b> {coc_api.estimate_creation_date(data, stored_obstacles, stored_skins)}\n"
    response += f"⏰ <b>Manual Last Seen:</b> {last_seen}\n"
    response += f"📱 <b>Device:</b> {devices}"
    if secret_info and secret_info[4] == message.from_user.id:
        response += " (Yours! 🔗)"
    response += "\n"
    response += f"💰 <b>Transactions:</b> {transactions}\n"
    if stored_obstacles:
        response += f"🎄 <b>Obstacles:</b> {', '.join(stored_obstacles)}\n"
    else:
        response += f"🎄 <b>Obstacles:</b> None provided\n"
    if stored_skins:
        response += f"👑 <b>Skins:</b> {', '.join(stored_skins)}\n"
    else:
        response += f"👑 <b>Skins:</b> None provided\n"
    response += f"ℹ️ <b>Auto-Linked!</b> Device: {devices} (Yours! 🔗)"
    await message.answer(response)

# Other handlers
@router.message(Command("start"))
async def start(message: Message):
    await message.answer("🎉 <b>Welcome to the CoC Bot!</b> 🎉\nUse /help to see commands or /redeem key to start! 🚀")

@router.message(Command("help"))
async def help_command(message: Message):
    help_text = """
🌟 <b>CoC Bot Commands</b> 🌟
/start - Kick things off! 🎉
/help - Show this menu 📜
/key [1hour|1day|3day|7day|30day] max_users - (Admin) Generate a key 🔑
/allkey - (Admin) Show all keys 📋
/redeem key - Activate access 🎟️
/info - Check access status ⏳
/check player_tag [obstacles] - Get player stats and store data 📊
/skin player_tag skin1,skin2,... - (Admin) Set skins for a player 👑
/check_bs player_tag - Brawl Stars stats 🎮
/check_cr player_tag - Clash Royale stats 👑
/linktag player_tag - Link CoC tag 🔗
/setdevice player_tag device - Update device 📱
/addinfo tag creation_date last_seen devices transactions obstacles skins - (Admin) Add data ✍️
/updateinfo tag field new_value - (Admin) Edit data 🔧
/removeinfo tag - (Admin) Delete data 🗑️
/viewinfo tag - (Admin) View data 👀
"""
    await message.answer(help_text)

@router.message(Command("key"))
async def keygen(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()[1:]
    if len(args) != 2 or args[0] not in ['1hour', '1day', '3day', '7day', '30day'] or not args[1].isdigit():
        await message.answer("⚠️ Usage: /key [1hour|1day|3day|7day|30day] max_users")
        return
    duration_str = args[0]
    max_users = int(args[1])
    if max_users < 1:
        await message.answer("❌ <b>Max users must be at least 1!</b>")
        return
    duration_map = {
        '1hour': datetime.timedelta(hours=1),
        '1day': datetime.timedelta(days=1),
        '3day': datetime.timedelta(days=3),
        '7day': datetime.timedelta(days=7),
        '30day': datetime.timedelta(days=30)
    }
    key = generate_key()
    c.execute('INSERT INTO keys (key, duration, max_users, created_by, used_by) VALUES (?, ?, ?, ?, ?)', 
              (key, duration_map[duration_str].total_seconds() / 3600, max_users, message.from_user.id, ''))
    conn.commit()
    response = f"✅ <b>Key Generated!</b> 🔑\n<code>{key}</code>\nDuration: {duration_str} | Max Users: {max_users}"
    await message.answer(response)

@router.message(Command("allkey"))
async def all_keys(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    c.execute('SELECT key, duration, max_users, used_by FROM keys')
    keys = c.fetchall()
    if not keys:
        await message.answer("❌ <b>No keys found!</b>")
        return
    response = "📋 <b>All Generated Keys</b> 📋\n"
    for key, duration, max_users, used_by in keys:
        users = used_by.split(',') if used_by else []
        duration_str = f"{int(duration)} hour{'s' if int(duration) != 1 else ''}"
        response += f"<code>{key}</code> - Duration: {duration_str} | Max Users: {max_users} | Redeemed: {len(users)}\n"
    await message.answer(response)

@router.message(Command("redeem"))
async def redeem(message: Message):
    args = message.text.split()[1:]
    if not args:
        await message.answer("⚠️ Usage: /redeem key")
        return
    key = args[0]
    c.execute('SELECT key, duration, max_users, used_by FROM keys WHERE key=?', (key,))
    row = c.fetchone()
    if not row:
        await message.answer("❌ <b>Invalid key!</b>")
        return
    duration, max_users, used_by = row[1], row[2], row[3].split(',') if row[3] else []
    if str(message.from_user.id) in used_by:
        await message.answer("❌ <b>You already used this key!</b>")
        return
    if len(used_by) >= max_users:
        await message.answer("❌ <b>Key redemption limit reached!</b>")
        return
    duration = datetime.timedelta(hours=duration)
    add_user(message.from_user.id, duration)
    used_by.append(str(message.from_user.id))
    c.execute('UPDATE keys SET used_by=? WHERE key=?', (','.join(used_by), key))
    conn.commit()
    expire_at = datetime.datetime.utcnow() + duration
    await message.answer(f"🎉 <b>Redeemed!</b> ✅\nAccess valid until: {expire_at.strftime('%Y-%m-%d %H:%M UTC')}")

@router.message(Command("info"))
async def info(message: Message):
    c.execute('SELECT expire_at FROM users WHERE user_id=?', (message.from_user.id,))
    row = c.fetchone()
    if row:
        expire_at = datetime.datetime.fromisoformat(row[0])
        left = expire_at - datetime.datetime.utcnow()
        if left.total_seconds() > 0:
            await message.answer(f"👤 <b>User: @{message.from_user.username}</b>\n✅ Access Active\nExpires in: {left.days} days, {(left.seconds // 3600)} hours")
        else:
            await message.answer("❌ <b>Access Expired!</b> Use /redeem key")
    else:
        await message.answer("❌ <b>No Access!</b> Use /redeem key")

@router.message(Command("linktag"))
async def link_tag(message: Message):
    c.execute('SELECT expire_at FROM users WHERE user_id=?', (message.from_user.id,))
    row = c.fetchone()
    if not row or datetime.datetime.fromisoformat(row[0]) < datetime.datetime.utcnow():
        await message.answer("❌ <b>No Access!</b> Use /redeem key")
        return
    args = message.text.split()[1:]
    if not args:
        await message.answer("⚠️ Usage: /linktag player_tag")
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
        await message.answer("❌ <b>No Access!</b> Use /redeem key")
        return
    args = message.text.split()[1:]
    if len(args) < 2:
        await message.answer("⚠️ Usage: /setdevice player_tag device")
        return
    tag, device = args[0], " ".join(args[1:])
    c.execute('UPDATE player_info SET devices=? WHERE tag=? AND telegram_user_id=?', 
              (device, tag, message.from_user.id))
    if c.rowcount > 0:
        conn.commit()
        await message.answer(f"📱 <b>Device Updated!</b> ✅\nTag: {tag}\nNew Device: {device}")
    else:
        await message.answer(f"❌ <b>Tag {tag} not linked to you!</b> Use /linktag first.")

@router.message(Command("addinfo"))
async def addinfo(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split(maxsplit=6)
    if len(args) < 7:
        await message.answer("⚠️ Usage: /addinfo tag creation_date last_seen devices transactions obstacles skins")
        return
    tag, creation_date, last_seen, devices, transactions, obstacles, skins = args[1:]
    c.execute('INSERT OR REPLACE INTO player_info (tag, creation_date, last_seen, devices, transactions, obstacles, skins) VALUES (?, ?, ?, ?, ?, ?, ?)', 
              (tag, creation_date, last_seen, devices, transactions, obstacles, skins))
    conn.commit()
    await message.answer("✅ <b>Info Added!</b>")

@router.message(Command("updateinfo"))
async def updateinfo(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()[1:]
    if len(args) < 3:
        await message.answer("⚠️ Usage: /updateinfo tag field new_value")
        return
    allowed_fields = ['creation_date', 'last_seen', 'devices', 'transactions', 'obstacles', 'skins']
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
        await message.answer("⚠️ Usage: /removeinfo tag")
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
        await message.answer("⚠️ Usage: /viewinfo tag")
        return
    tag = args[0]
    c.execute('SELECT * FROM player_info WHERE tag=?', (tag,))
    row = c.fetchone()
    if row:
        await message.answer(f"👀 <b>Player Info</b>\nTag: {row[0]}\nCreated: {row[1]}\nLast Seen: {row[2]}\nDevices: {row[3]}\nTransactions: {row[4]}\nObstacles: {row[6]}\nSkins: {row[7]}")
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