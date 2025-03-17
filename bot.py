import json
import os
import sqlite3
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import pytz

# Load environment variables from .env file
load_dotenv()

class ExchangeRateBot:
    def __init__(self):
        # Get the bot token from the environment variable
        self.bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        if not self.bot_token:
            raise ValueError("Please set the TELEGRAM_BOT_TOKEN environment variable in the .env file.")

        # Initialize the bot application
        self.application = Application.builder().token(self.bot_token).post_init(self.post_init).build()

        # Add command handlers
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("rates", self.send_rates))  # Add /rates handler

        # Initialize the database
        self.init_db()

        # Initialize the scheduler
        self.scheduler = AsyncIOScheduler(timezone=pytz.timezone("Asia/Bangkok"))

    async def post_init(self, application: Application):
        """Set up bot commands using set_my_commands."""
        await application.bot.set_my_commands([
            ("start", "Start the bot and subscribe to daily rates"),
            ("rates", "Get the latest exchange rates"),
        ])

    def init_db(self):
        """Initialize the SQLite database to store user chat IDs."""
        self.conn = sqlite3.connect("users.db")
        self.cursor = self.conn.cursor()
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                chat_id INTEGER PRIMARY KEY
            )
        """)
        self.conn.commit()

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler for the /start command."""
        chat_id = update.message.chat_id

        # Save the user's chat ID to the database if not already present
        self.cursor.execute("INSERT OR IGNORE INTO users (chat_id) VALUES (?)", (chat_id,))
        self.conn.commit()

        await update.message.reply_text(
            "Welcome! You will now receive daily exchange rates for USD, RUB, and EUR at 10 AM Bangkok time.\n\n"
            "Use /rates to get the latest exchange rates at any time."
        )

    def load_exchange_rates(self):
        """Load the exchange rates from the JSON file."""
        with open("exchange_rates.json", "r") as file:
            data = json.load(file)
        return data

    def get_latest_rates(self, data):
        """Get the latest date and rates for USD, RUB, and EUR."""
        # Get the latest date (assuming the JSON is sorted by date)
        sorted_dates = sorted(data.keys(), reverse=True)
        latest_date = sorted_dates[0]
        previous_date = sorted_dates[1] if len(sorted_dates) > 1 else None

        latest_rates = data[latest_date]["rates"]
        previous_rates = data[previous_date]["rates"] if previous_date else None

        # Extract USD, RUB, and EUR rates
        usd = latest_rates.get("USD", {})
        rub = latest_rates.get("RUB", {})
        eur = latest_rates.get("EUR", {})

        # Compare with previous rates
        def get_trend(current, previous, key):
            if not previous or key not in previous:
                return ""
            current_rate = current.get(key, 0)
            previous_rate = previous.get(key, {}).get(key, 0)
            if current_rate > previous_rate:
                return '<span style="color: green;">↑</span>'  # Green up arrow
            elif current_rate < previous_rate:
                return '<span style="color: red;">↓</span>'  # Red down arrow
            return ""

        usd_trend = get_trend(usd, previous_rates.get("USD") if previous_rates else None, "buyingRate")
        rub_trend = get_trend(rub, previous_rates.get("RUB") if previous_rates else None, "buyingRate")
        eur_trend = get_trend(eur, previous_rates.get("EUR") if previous_rates else None, "buyingRate")

        return latest_date, usd, rub, eur, usd_trend, rub_trend, eur_trend

    def format_rates_message(self, latest_date, usd, rub, eur, usd_trend, rub_trend, eur_trend):
        """Format the exchange rates into a message."""
        return (
            f"📅 Latest rates as of <b>{latest_date}</b>:\n\n"
            f"🇺🇸 <b>USD (United States)</b>\n"
            f"  Buying: {usd.get('buyingRate', 'N/A')} {usd_trend}\n"
            f"  Selling: {usd.get('sellingRate', 'N/A')}\n\n"
            f"🇷🇺 <b>RUB (Russia)</b>\n"
            f"  Buying: {rub.get('buyingRate', 'N/A')} {rub_trend}\n"
            f"  Selling: {rub.get('sellingRate', 'N/A')}\n\n"
            f"🇪🇺 <b>EUR (European Union)</b>\n"
            f"  Buying: {eur.get('buyingRate', 'N/A')} {eur_trend}\n"
            f"  Selling: {eur.get('sellingRate', 'N/A')}\n"
        )

    async def send_rates(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler for the /rates command."""
        data = self.load_exchange_rates()
        latest_date, usd, rub, eur, usd_trend, rub_trend, eur_trend = self.get_latest_rates(data)

        # Format the message
        message = self.format_rates_message(latest_date, usd, rub, eur, usd_trend, rub_trend, eur_trend)

        # Send the message to the user who issued the /rates command
        await update.message.reply_text(message, parse_mode="HTML")

    async def send_daily_rates(self):
        """Send the daily exchange rates to all registered users."""
        data = self.load_exchange_rates()
        latest_date, usd, rub, eur, usd_trend, rub_trend, eur_trend = self.get_latest_rates(data)

        # Format the message
        message = self.format_rates_message(latest_date, usd, rub, eur, usd_trend, rub_trend, eur_trend)

        # Send the message to all registered users
        self.cursor.execute("SELECT chat_id FROM users")
        users = self.cursor.fetchall()
        for user in users:
            chat_id = user[0]
            await self.application.bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode="HTML"  # Enable HTML formatting
            )

    def run(self):
        """Run the bot."""
        print("Bot is running...")
        # Start the scheduler after the bot is running
        self.application.run_polling()
        self.scheduler.add_job(self.send_daily_rates, "cron", hour=10, minute=0)
        self.scheduler.start()

if __name__ == "__main__":
    bot = ExchangeRateBot()
    bot.run()
