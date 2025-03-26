import sqlite3
import random
import string
import aiohttp
from aiogram import Bot, Dispatcher, types, executor
from config import BOT_TOKEN, ADMIN_ID, COC_API_KEY
import datetime

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)

# Initialize DB
conn = sqlite3.connect('database.sqlite')
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, expire_at TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS keys (key TEXT, duration INTEGER, created_by INTEGER, used_by INTEGER DEFAULT NULL)''')
c.execute('''CREATE TABLE IF NOT EXISTS player_info (tag TEXT PRIMARY KEY, creation_date TEXT, last_seen TEXT, devices TEXT, transactions TEXT)''')
conn.commit()

@dp.message_handler(commands=['help'])
async def help_command(message: types.Message):
    help_text = """
<b>🤖 Available Commands:</b>

/start - Start the bot
/help - Show all commands
/key [1day|3day|7day] - (Admin) Generate redeem key
/redeem <key> - Redeem your key
/info - Check your access validity
/check <player_tag> - Get player info from CoC API + manual database
/addinfo <tag> <creation_date> <last_seen> <devices> <transactions> - (Admin) Add manual info
/updateinfo <tag> <field> <new_value> - (Admin) Update player info field
/removeinfo <tag> - (Admin) Remove player info
/viewinfo <tag> - (Admin) View stored player info

    await message.reply(help_text, parse_mode="HTML")

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
            if resp.status == 200:
                return await resp.json()
            else:
                return None

@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    await message.reply("Welcome! Use /redeem <key> to activate access.")

@dp.message_handler(commands=['key'])
async def keygen(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.get_args().split()
    if not args or args[0] not in ['1day', '3day', '7day']:
        await message.reply("Usage: /key 1day or /key 3day or /key 7day")
        return
    duration_map = {'1day': 1, '3day': 3, '7day': 7}
    key = generate_key()
    c.execute('INSERT INTO keys (key, duration, created_by) VALUES (?, ?, ?)', (key, duration_map[args[0]], message.from_user.id))
    conn.commit()
    await message.reply(f"✅ Key Generated:\n`{key}`\nValid for: {args[0]}", parse_mode="Markdown")

@dp.message_handler(commands=['redeem'])
async def redeem(message: types.Message):
    args = message.get_args().split()
    if not args:
        await message.reply("Usage: /redeem <key>")
        return
    key = args[0]
    c.execute('SELECT key, duration, used_by FROM keys WHERE key=?', (key,))
    row = c.fetchone()
    if not row:
        await message.reply("❌ Invalid key.")
        return
    if row[2]:
        await message.reply("❌ Key already used.")
        return
    add_user(message.from_user.id, row[1])
    c.execute('UPDATE keys SET used_by=? WHERE key=?', (message.from_user.id, key))
    conn.commit()
    expire_at = datetime.datetime.utcnow() + datetime.timedelta(days=row[1])
    await message.reply(f"✅ Redeemed! Access valid until {expire_at.strftime('%Y-%m-%d %H:%M UTC')}.")

@dp.message_handler(commands=['info'])
async def info(message: types.Message):
    c.execute('SELECT expire_at FROM users WHERE user_id=?', (message.from_user.id,))
    row = c.fetchone()
    if row:
        expire_at = datetime.datetime.fromisoformat(row[0])
        left = expire_at - datetime.datetime.utcnow()
        if left.total_seconds() > 0:
            await message.reply(f"👤 User: @{message.from_user.username}\nAccess Active\nExpires in: {left.days} days, {left.seconds // 3600} hours")
        else:
            await message.reply("❌ Your access has expired.")
    else:
        await message.reply("❌ You don't have access. Use /redeem <key>.")

@dp.message_handler(commands=['check'])
async def check_player(message: types.Message):
    c.execute('SELECT expire_at FROM users WHERE user_id=?', (message.from_user.id,))
    row = c.fetchone()
    if not row or datetime.datetime.fromisoformat(row[0]) < datetime.datetime.utcnow():
        await message.reply("❌ You don't have access. Use /redeem <key>.")
        return
    args = message.get_args().split()
    if not args:
        await message.reply("Usage: /check <player_tag>")
        return
    tag = args[0]
    data = await get_coc_data(tag)
    c.execute('SELECT creation_date, last_seen, devices, transactions FROM player_info WHERE tag=?', (tag,))
    secret_info = c.fetchone()
    if not data:
        await message.reply("❌ Player not found.")
        return
    response = f"**Official Info:**\nName: {data['name']}\nLevel: {data['expLevel']}\nTown Hall: {data['townHallLevel']}\nTag: {data['tag']}\n\n"
    if secret_info:
        response += "**Manual Info:**\n"
        response += f"Account Created: {secret_info[0]}\nLast Seen: {secret_info[1]}\nDevices: {secret_info[2]}\nTransactions: {secret_info[3]}"
    else:
        response += "No manual secret info stored for this player."
    await message.reply(response, parse_mode="Markdown")

@dp.message_handler(commands=['addinfo'])
async def addinfo(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.get_args().split()
    if len(args) < 5:
        await message.reply("Usage: /addinfo <tag> <creation_date> <last_seen> <devices> <transactions>")
        return
    c.execute('INSERT OR REPLACE INTO player_info (tag, creation_date, last_seen, devices, transactions) VALUES (?, ?, ?, ?, ?)', tuple(args[:5]))
    conn.commit()
    await message.reply("✅ Info added.")

@dp.message_handler(commands=['updateinfo'])
async def updateinfo(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = message.get_args().split()
    if len(args) < 3:
        await message.reply("Usage: /updateinfo <tag> <field> <new_value>")
        return
    c.execute(f'UPDATE player_info SET {args[1]}=? WHERE tag=?', (args[2], args[0]))
    conn.commit()
    await message.reply("✅ Info updated.")

@dp.message_handler(commands=['removeinfo'])
async def removeinfo(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    tag = message.get_args()
    c.execute('DELETE FROM player_info WHERE tag=?', (tag,))
    conn.commit()
    await message.reply("✅ Info removed.")

@dp.message_handler(commands=['viewinfo'])
async def viewinfo(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    tag = message.get_args()
    c.execute('SELECT * FROM player_info WHERE tag=?', (tag,))
    row = c.fetchone()
    if row:
        await message.reply(f"Tag: {row[0]}\nCreated: {row[1]}\nLast Seen: {row[2]}\nDevices: {row[3]}\nTransactions: {row[4]}")
    else:
        await message.reply("❌ No info stored for this tag.")

if __name__ == '__main__':
    print("Bot starting...")
    executor.start_polling(dp)
