import os
import logging
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes
)
import httpx

# --- Config ---
TELEGRAM_TOKEN = "8703348510:AAGUtXl7kRebu6_iuGAhQv0XV6XMZAXwMMc"
OWM_API_KEY = "c0002c86f6c3e5b5e946e14b426842ad"
OWM_URL = "https://api.openweathermap.org/data/2.5/weather"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# --- Clothing logic ---
def get_clothing_advice(temp: float, feels_like: float, weather_id: int, wind_speed: float, humidity: int) -> str:
    lines = []
    t = feels_like

    # Wind chill penalty for advice text
    wind_note = ""
    if wind_speed >= 10:
        wind_note = " (вітер робить холодніше)"
    elif wind_speed >= 6:
        wind_note = " (є помітний вітер)"

    humidity_note = ""
    if humidity >= 85 and temp < 15:
        humidity_note = " + висока вологість підсилює холод"

    if t >= 28:
        if humidity >= 70:
            lines.append("🩳 Шорти і футболка. Спекотно і волого — обирай дихаючі тканини.")
        else:
            lines.append("🩳 Шорти і футболка. Спекотно.")
    elif t >= 22:
        lines.append("👕 Футболка, легкі штани або шорти.")
    elif t >= 16:
        lines.append(f"👔 Лонгслів або легкий светр{wind_note}.")
    elif t >= 10:
        lines.append(f"🧥 Куртка або худі, джинси{wind_note}{humidity_note}.")
    elif t >= 3:
        lines.append(f"🧥 Тепла куртка, шарф{wind_note}{humidity_note}.")
    elif t >= -5:
        lines.append(f"🧥 Зимова куртка, шапка, шарф{wind_note}{humidity_note}.")
    else:
        lines.append("🧥❄️ Повний зимовий комплект: куртка, термобілизна, шапка, рукавиці.")

    if 500 <= weather_id < 600:
        if weather_id in (502, 503, 504):
            lines.append("🌧️ Сильний дощ — водонепроникна куртка і чоботи.")
        else:
            lines.append("🌧️ Дощ — візьми парасольку.")
    elif 600 <= weather_id < 700:
        lines.append("❄️ Сніг — водонепроникне взуття і теплі шкарпетки.")
    elif 200 <= weather_id < 300:
        lines.append("⛈️ Гроза — парасолька обов'язкова, краще залишись вдома.")

    if wind_speed >= 15:
        lines.append("💨 Дуже сильний вітер — вітрозахисний верхній шар обов'язковий.")
    elif wind_speed >= 10:
        lines.append("💨 Сильний вітер — вітрозахисна куртка буде до речі.")

    if humidity >= 85 and temp >= 20:
        lines.append("💧 Висока вологість — обирай легкі тканини, що дихають.")

    return "\n".join(lines)

# --- Weather fetch ---
async def fetch_weather_by_city(city: str) -> dict:
    params = {"q": city, "appid": OWM_API_KEY, "units": "metric", "lang": "en"}
    async with httpx.AsyncClient() as client:
        r = await client.get(OWM_URL, params=params, timeout=10)
        r.raise_for_status()
        return r.json()


async def fetch_weather_by_coords(lat: float, lon: float) -> dict:
    params = {"lat": lat, "lon": lon, "appid": OWM_API_KEY, "units": "metric", "lang": "en"}
    async with httpx.AsyncClient() as client:
        r = await client.get(OWM_URL, params=params, timeout=10)
        r.raise_for_status()
        return r.json()


def format_weather_reply(data: dict) -> str:
    city = data["name"]
    country = data["sys"]["country"]
    temp = data["main"]["temp"]
    feels_like = data["main"]["feels_like"]
    weather_id = data["weather"][0]["id"]
    description = data["weather"][0]["description"].capitalize()
    wind_speed = data["wind"]["speed"]
    humidity = data["main"]["humidity"]

    advice = get_clothing_advice(temp, feels_like, weather_id, wind_speed)

    return (
        f"📍 *{city}, {country}*\n"
        f"🌡️ {temp:.0f}°C (feels like {feels_like:.0f}°C)\n"
        f"☁️ {description}\n"
        f"💧 Humidity: {humidity}%\n"
        f"💨 Wind: {wind_speed:.0f} m/s\n\n"
        f"*What to wear:*\n{advice}"
    )


# --- Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[KeyboardButton("📍 Share my location", request_location=True)]]
    markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(
        "👋 Send me your *city name* or share your *location*, "
        "and I'll tell you what to wear today.",
        parse_mode="Markdown",
        reply_markup=markup,
    )


async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    loc = update.message.location
    try:
        data = await fetch_weather_by_coords(loc.latitude, loc.longitude)
        await update.message.reply_text(format_weather_reply(data), parse_mode="Markdown")
    except Exception as e:
        logger.error(e)
        await update.message.reply_text("⚠️ Couldn't fetch weather. Try again later.")


async def handle_city(update: Update, context: ContextTypes.DEFAULT_TYPE):
    city = update.message.text.strip()
    try:
        data = await fetch_weather_by_city(city)
        await update.message.reply_text(format_weather_reply(data), parse_mode="Markdown")
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            await update.message.reply_text("❌ City not found. Check the spelling and try again.")
        else:
            await update.message.reply_text("⚠️ Weather service error. Try again later.")
    except Exception as e:
        logger.error(e)
        await update.message.reply_text("⚠️ Something went wrong. Try again later.")


# --- Main ---
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.LOCATION, handle_location))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_city))
    logger.info("Bot started.")
    import asyncio
    asyncio.run(app.run_polling())


if __name__ == "__main__":
    main()