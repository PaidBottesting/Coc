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
c.execute('''CREATE TABLE IF NOT EXISTS player_info (tag TEXT PRIMARY KEY, creation_date TEXT, last_seen TEXT, devices TEXT, transactions TEXT)''')
conn.commit()

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()
router = Router()
dp.include_router(router)

# Helper functions
def generate_key():
    return "COC-" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

def add_user(user_id, duration_days):
    expire_at = datetime.datetime.utcnow() + datetime.timedelta(days=duration_days)
    c.execute('INSERT OR REPLACE INTO users (user_id, expire_at) VALUES (?, ?)', (user_id, expire_at.isoformat()))
    conn.commit()

async def get_coc_data(tag):
    headers = {'Authorization': f'Bearer {COC_API_KEY}'}
    async with aiohttp.ClientSession() as session:
        async with session.get(f'https://api.clashofclans.com/v1/players/%23{tag.strip("#")}', headers=headers) as resp:
            try:
                return await resp.json()
            except:
                return None

# Handlers
@router.message(Command("start"))
async def start(message: Message):
    await message.answer("Welcome! Use /redeem &lt;key&gt; to activate access.")

@router.message(Command("help"))
async def help_command(message: Message):
    help_text = """
<b>🤖 Available Commands:</b>

/start - Start the bot
/help - Show all commands
/key [1day|3day|7day] - (Admin) Generate redeem key
/redeem &lt;key&gt; - Redeem your key
/info - Check your access validity
/check &lt;player_tag&gt; - Get player info from CoC API + manual database
/addinfo &lt;tag&gt; &lt;creation_date&gt; &lt;last_seen&gt; &lt;devices&gt; &lt;transactions&gt; - (Admin) Add manual info
/updateinfo &lt;tag&gt; &lt;field&gt; &lt;new_value&gt; - (Admin) Update player info
/removeinfo &lt;tag&gt; - (Admin) Remove player info
/viewinfo &lt;tag&gt; - (Admin) View stored player info
"""
    await message.answer(help_text)

@router.message(Command("key"))
async def keygen(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()[1:]
    if not args or args[0] not in ['1day', '3day', '7day']:
        await message.answer("Usage: /key 1day or /key 3day or /key 7day")
        return
    duration_map = {'1day': 1, '3day': 3, '7day': 7}
    key = generate_key()
    c.execute('INSERT INTO keys (key, duration, created_by) VALUES (?, ?, ?)', (key, duration_map[args[0]], message.from_user.id))
    conn.commit()
    await message.answer(f"✅ Key Generated:\n<code>{key}</code>\nValid for: {args[0]}")

@router.message(Command("redeem"))
async def redeem(message: Message):
    args = message.text.split()[1:]
    if not args:
        await message.answer("Usage: /redeem &lt;key&gt;")
        return
    key = args[0]
    c.execute('SELECT key, duration, used_by FROM keys WHERE key=?', (key,))
    row = c.fetchone()
    if not row:
        await message.answer("❌ Invalid key.")
        return
    if row[2]:
        await message.answer("❌ Key already used.")
        return
    add_user(message.from_user.id, row[1])
    c.execute('UPDATE keys SET used_by=? WHERE key=?', (message.from_user.id, key))
    conn.commit()
    expire_at = datetime.datetime.utcnow() + datetime.timedelta(days=row[1])
    await message.answer(f"✅ Redeemed! Access valid until {expire_at.strftime('%Y-%m-%d %H:%M UTC')}.")

@router.message(Command("info"))
async def info(message: Message):
    c.execute('SELECT expire_at FROM users WHERE user_id=?', (message.from_user.id,))
    row = c.fetchone()
    if row:
        expire_at = datetime.datetime.fromisoformat(row[0])
        left = expire_at - datetime.datetime.utcnow()
        if left.total_seconds() > 0:
            await message.answer(f"👤 User: @{message.from_user.username}\nAccess Active\nExpires in: {left.days} days, {(left.seconds // 3600)} hours")
        else:
            await message.answer("❌ Your access has expired.")
    else:
        await message.answer("❌ You don't have access. Use /redeem &lt;key&gt;.")

@router.message(Command("check"))
async def check_player(message: Message):
    c.execute('SELECT expire_at FROM users WHERE user_id=?', (message.from_user.id,))
    row = c.fetchone()
    if not row or datetime.datetime.fromisoformat(row[0]) < datetime.datetime.utcnow():
        await message.answer("❌ You don't have access. Use /redeem &lt;key&gt;.")
        return
    args = message.text.split()[1:]
    if not args:
        await message.answer("Usage: /check &lt;player_tag&gt;")
        return
    tag = args[0]
    data = await get_coc_data(tag)
    c.execute('SELECT creation_date, last_seen, devices, transactions FROM player_info WHERE tag=?', (tag,))
    secret_info = c.fetchone()
    if not data:
        await message.answer("❌ Player not found.")
        return
    response = f"<b>Official Info:</b>\nName: {data['name']}\nLevel: {data['expLevel']}\nTH: {data['townHallLevel']}\nTag: {data['tag']}\n\n"
    if secret_info:
        response += "<b>Manual Info:</b>\n"
        response += f"Account Created: {secret_info[0]}\nLast Seen: {secret_info[1]}\nDevices: {secret_info[2]}\nTransactions: {secret_info[3]}"
    else:
        response += "No manual info stored for this player."
    await message.answer(response)

@router.message(Command("addinfo"))
async def addinfo(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()[1:]
    if len(args) < 5:
        await message.answer("Usage: /addinfo &lt;tag&gt; &lt;creation_date&gt; &lt;last_seen&gt; &lt;devices&gt; &lt;transactions&gt;")
        return
    c.execute('INSERT OR REPLACE INTO player_info (tag, creation_date, last_seen, devices, transactions) VALUES (?, ?, ?, ?, ?)', tuple(args[:5]))
    conn.commit()
    await message.answer("✅ Info added.")

@router.message(Command("updateinfo"))
async def updateinfo(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()[1:]
    if len(args) < 3:
        await message.answer("Usage: /updateinfo &lt;tag&gt; &lt;field&gt; &lt;new_value&gt;")
        return
    allowed_fields = ['creation_date', 'last_seen', 'devices', 'transactions']
    if args[1] not in allowed_fields:
        await message.answer(f"❌ Invalid field. Allowed fields: {', '.join(allowed_fields)}")
        return
    c.execute(f'UPDATE player_info SET {args[1]}=? WHERE tag=?', (args[2], args[0]))
    conn.commit()
    await message.answer("✅ Info updated.")

@router.message(Command("removeinfo"))
async def removeinfo(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()[1:]
    if not args:
        await message.answer("Usage: /removeinfo &lt;tag&gt;")
        return
    tag = args[0]
    c.execute('DELETE FROM player_info WHERE tag=?', (tag,))
    conn.commit()
    await message.answer("✅ Info removed.")

@router.message(Command("viewinfo"))
async def viewinfo(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.text.split()[1:]
    if not args:
        await message.answer("Usage: /viewinfo &lt;tag&gt;")
        return
    tag = args[0]
    c.execute('SELECT * FROM player_info WHERE tag=?', (tag,))
    row = c.fetchone()
    if row:
        await message.answer(f"Tag: {row[0]}\nCreated: {row[1]}\nLast Seen: {row[2]}\nDevices: {row[3]}\nTransactions: {row[4]}")
    else:
        await message.answer("❌ No info stored for this tag.")

async def main():
    print("Bot starting...")
    try:
        await dp.start_polling(bot)
    finally:
        conn.close()

if __name__ == '__main__':
    asyncio.run(main())
