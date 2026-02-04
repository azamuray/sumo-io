import os
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo, ReplyKeyboardMarkup, KeyboardButton

# Get bot token from environment
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://sumo.lovza.ru")

# Initialize bot and dispatcher
bot = Bot(token=BOT_TOKEN) if BOT_TOKEN else None
dp = Dispatcher()


@dp.message(Command("play", "start", "game"))
async def cmd_play(message: types.Message):
    """Handle /play, /start, /game commands"""

    # Different message and button for group vs private chat
    if message.chat.type in ["group", "supergroup"]:
        # In groups, use inline URL button (web_app doesn't work in groups with inline)
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="🎮 Играть в Sumo.io",
                url=f"{WEBAPP_URL}?startapp=group_{message.chat.id}"
            )]
        ])
        text = "🏟 Кто хочет сразиться?\n\nНажми кнопку — все из группы попадут в одну комнату!"
        await message.answer(text, reply_markup=keyboard)
    else:
        # In private chat, use web_app button for native experience
        keyboard = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(
                text="🎮 Играть",
                web_app=WebAppInfo(url=WEBAPP_URL)
            )]],
            resize_keyboard=True
        )
        text = "👋 Добро пожаловать в Sumo.io!\n\nСталкивай соперников с арены и побеждай!"
        await message.answer(text, reply_markup=keyboard)


@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    """Handle /help command"""
    text = """🎮 *Sumo.io* — мультиплеерная игра

*Как играть:*
• Свайпай по экрану, чтобы двигаться
• Сталкивай соперников с арены
• Последний на арене — победитель!

*Команды:*
/play — начать игру
/help — эта справка

*В группе:*
Добавь бота в группу и напиши /play — все участники смогут играть вместе!"""

    await message.answer(text, parse_mode="Markdown")


async def process_update(update_data: dict):
    """Process incoming update from webhook"""
    if bot:
        update = types.Update(**update_data)
        await dp.feed_update(bot, update)
