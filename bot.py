import os
import logging
import json
import asyncio
from datetime import time
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes
)
import httpx

# --- Config ---
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
OWM_API_KEY = os.environ["OWM_API_KEY"]
OWM_CURRENT_URL = "https://api.openweathermap.org/data/2.5/weather"
OWM_FORECAST_URL = "https://api.openweathermap.org/data/2.5/forecast"
USERS_FILE = "users.json"
MORNING_HOUR = 7
MORNING_MINUTE = 30

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# --- User storage ---
def load_users() -> dict:
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, "r") as f:
            return json.load(f)
    return {}


def save_users(users: dict):
    with open(USERS_FILE, "w") as f:
        json.dump(users, f)


def save_user_city(chat_id: int, city: str, lat: float = None, lon: float = None):
    users = load_users()
    users[str(chat_id)] = {"city": city, "lat": lat, "lon": lon}
    save_users(users)


# --- Clothing logic ---
def get_clothing_advice(temp: float, feels_like: float, weather_id: int, wind_speed: float, humidity: int) -> str:
    lines = []
    t = feels_like

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
    params = {"q": city, "appid": OWM_API_KEY, "units": "metric", "lang": "uk"}
    async with httpx.AsyncClient() as client:
        r = await client.get(OWM_CURRENT_URL, params=params, timeout=10)
        r.raise_for_status()
        return r.json()


async def fetch_weather_by_coords(lat: float, lon: float) -> dict:
    params = {"lat": lat, "lon": lon, "appid": OWM_API_KEY, "units": "metric", "lang": "uk"}
    async with httpx.AsyncClient() as client:
        r = await client.get(OWM_CURRENT_URL, params=params, timeout=10)
        r.raise_for_status()
        return r.json()


async def fetch_forecast_by_city(city: str) -> dict:
    params = {"q": city, "appid": OWM_API_KEY, "units": "metric", "lang": "uk", "cnt": 40}
    async with httpx.AsyncClient() as client:
        r = await client.get(OWM_FORECAST_URL, params=params, timeout=10)
        r.raise_for_status()
        return r.json()


async def fetch_forecast_by_coords(lat: float, lon: float) -> dict:
    params = {"lat": lat, "lon": lon, "appid": OWM_API_KEY, "units": "metric", "lang": "uk", "cnt": 40}
    async with httpx.AsyncClient() as client:
        r = await client.get(OWM_FORECAST_URL, params=params, timeout=10)
        r.raise_for_status()
        return r.json()


# --- Format replies ---
def format_weather_reply(data: dict) -> str:
    city = data["name"]
    country = data["sys"]["country"]
    temp = data["main"]["temp"]
    feels_like = data["main"]["feels_like"]
    weather_id = data["weather"][0]["id"]
    description = data["weather"][0]["description"].capitalize()
    wind_speed = data["wind"]["speed"]
    humidity = data["main"]["humidity"]
    advice = get_clothing_advice(temp, feels_like, weather_id, wind_speed, humidity)

    return (
        f"📍 *{city}, {country}*\n"
        f"🌡️ {temp:.0f}°C (відчувається як {feels_like:.0f}°C)\n"
        f"☁️ {description}\n"
        f"💧 Вологість: {humidity}%\n"
        f"💨 Вітер: {wind_speed:.0f} м/с\n\n"
        f"*Що вдягнути:*\n{advice}"
    )


def format_morning_forecast(forecast_data: dict) -> str:
    city = forecast_data["city"]["name"]
    country = forecast_data["city"]["country"]
    target_hours = [8, 14, 18]
    slots = {}

    for item in forecast_data["list"]:
        dt_txt = item["dt_txt"]
        hour = int(dt_txt[11:13])

        for t in target_hours:
            if hour == t and t not in slots:
                slots[t] = item

        if len(slots) == 3:
            break

    if not slots:
        return "⚠️ Не вдалося отримати прогноз."

    lines = [f"🌅 *Прогноз на день — {city}, {country}*\n"]
    labels = {8: "🕗 08:00 (ранок)", 14: "🕑 14:00 (день)", 18: "🕕 18:00 (вечір)"}

    for hour in target_hours:
        if hour not in slots:
            continue
        item = slots[hour]
        temp = item["main"]["temp"]
        feels_like = item["main"]["feels_like"]
        weather_id = item["weather"][0]["id"]
        description = item["weather"][0]["description"].capitalize()
        wind_speed = item["wind"]["speed"]
        humidity = item["main"]["humidity"]
        advice = get_clothing_advice(temp, feels_like, weather_id, wind_speed, humidity)

        lines.append(
            f"*{labels[hour]}*\n"
            f"🌡️ {temp:.0f}°C (відчувається як {feels_like:.0f}°C), {description}\n"
            f"💧 {humidity}% | 💨 {wind_speed:.0f} м/с\n"
            f"{advice}\n"
        )

    return "\n".join(lines)


# --- Morning job ---
async def send_morning_forecasts(context):
    users = load_users()
    for chat_id, user_data in users.items():
        try:
            if user_data.get("lat") and user_data.get("lon"):
                data = await fetch_forecast_by_coords(user_data["lat"], user_data["lon"])
            else:
                data = await fetch_forecast_by_city(user_data["city"])
            msg = format_morning_forecast(data)
            await context.bot.send_message(chat_id=int(chat_id), text=msg, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Morning forecast failed for {chat_id}: {e}")


# --- Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[KeyboardButton("📍 Поділитися локацією", request_location=True)]]
    markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(
        "👋 Надішли мені назву *міста* або поділися *локацією*, "
        "і я скажу що вдягнути сьогодні.\n\n"
        "Також щодня о *7:30* я надсилатиму прогноз на ранок, день і вечір — "
        "для цього просто надішли своє місто або локацію один раз.",
        parse_mode="Markdown",
        reply_markup=markup,
    )


async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    loc = update.message.location
    try:
        data = await fetch_weather_by_coords(loc.latitude, loc.longitude)
        save_user_city(update.message.chat_id, data["name"], loc.latitude, loc.longitude)
        await update.message.reply_text(
            format_weather_reply(data) + "\n\n✅ _Локацію збережено. Щодня о 7:30 надсилатиму прогноз._",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(e)
        await update.message.reply_text("⚠️ Не вдалося отримати погоду. Спробуй пізніше.")


async def handle_city(update: Update, context: ContextTypes.DEFAULT_TYPE):
    city = update.message.text.strip()
    try:
        data = await fetch_weather_by_city(city)
        save_user_city(update.message.chat_id, data["name"])
        await update.message.reply_text(
            format_weather_reply(data) + "\n\n✅ _Місто збережено. Щодня о 7:30 надсилатиму прогноз._",
            parse_mode="Markdown"
        )
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            await update.message.reply_text("❌ Місто не знайдено. Перевір написання і спробуй знову.")
        else:
            await update.message.reply_text("⚠️ Помилка сервісу погоди. Спробуй пізніше.")
    except Exception as e:
        logger.error(e)
        await update.message.reply_text("⚠️ Щось пішло не так. Спробуй пізніше.")


# --- Main ---
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.job_queue.run_daily(
        send_morning_forecasts,
        time=time(MORNING_HOUR, MORNING_MINUTE)
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.LOCATION, handle_location))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_city))

    logger.info("Bot started.")
    asyncio.run(app.run_polling())


if __name__ == "__main__":
    main()
