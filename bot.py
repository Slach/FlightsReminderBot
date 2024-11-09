import os
import logging
import sqlite3
import asyncio
import aiohttp
from datetime import datetime, timedelta
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove, LabeledPrice
from telegram.ext import (
    Application, 
    CommandHandler, 
    MessageHandler, 
    ConversationHandler,
    CallbackQueryHandler,
    filters, 
    ContextTypes,
    PreCheckoutQueryHandler
)
from calendar import monthcalendar

# Load environment variables
load_dotenv()

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Conversation states
AIRLINE, FLIGHT_NUMBER, FLIGHT_DATE = range(3)
XTR_PRICE = int(os.getenv('XTR_PRICE'))
BOT_TOKEN = os.getenv('BOT_TOKEN')  # Using BOT_TOKEN instead of TOKEN

# Database setup
def setup_database():
    conn = sqlite3.connect('flights.db')
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS flight_tracks (
            chat_id INTEGER,
            airline TEXT,
            flight_number TEXT,
            flight_date TEXT,
            PRIMARY KEY (chat_id, airline, flight_number, flight_date)
        )
    ''')
    conn.commit()
    conn.close()

# Command handlers
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a message when the command /start is issued."""
    welcome_message = (
        "👋 *Welcome to Flight Tracker Bot!*\n\n"
        "I can help you track flights and provide real-time updates on their status. "
        "Here's what I can do:\n\n"
        "✈️ *Track Flights*\n"
        "• Monitor flight status in real-time\n"
        "• Get automatic status updates\n"
        "• Track multiple flights simultaneously\n\n"
        "🔍 *Flight Information*\n"
        "• Departure & arrival times\n"
        "• Airport information\n"
        "• Flight status with visual indicators\n\n"
        "To get started, use the /flight command to track a flight, or type /help to see all available commands.\n\n"
        "Happy tracking! ✈️"
    )
    await update.message.reply_text(welcome_message, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a message when the command /help is issued."""
    help_text = (
        "🤖 *Available Commands:*\n\n"
        "/start - Start the bot\n"
        "/help - Show this help message\n"
        "/flight - Track a flight\n"
        "  • Enter airline name\n"
        "  • Enter flight number\n"
        "  • Select flight date\n\n"
        "/payment - Make a USDT payment\n"
        "ℹ️ *How to use:*\n"
        "1. Use /flight to start tracking a flight\n"
        "2. Follow the prompts to enter flight details\n"
        "3. The bot will automatically check and update you about the flight status\n\n"
        "✨ *Features:*\n"
        "• Real-time flight tracking\n"
        "• Automatic status updates\n"
        "• Calendar date selection\n"
        "• Support for multiple airlines"
    )
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle unknown commands and messages by showing help."""
    await update.message.reply_text(
        "I don't understand that command. Here's what I can do:",
        parse_mode='Markdown'
    )
    await help_command(update, context)

# Flight command handlers
async def flight_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start the flight tracking conversation."""
    await update.message.reply_text(
        "Please enter the airline name (e.g., 'United', 'Delta', 'American'):"
    )
    return AIRLINE

async def airline_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Store airline and ask for flight number."""
    context.user_data['airline'] = update.message.text
    await update.message.reply_text(
        "Please enter the flight number:"
    )
    return FLIGHT_NUMBER

async def flight_number_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Store flight number and ask for date."""
    context.user_data['flight_number'] = update.message.text
    
    # Create date picker keyboard
    keyboard = [
        [InlineKeyboardButton("Today", callback_data="today")],
        [InlineKeyboardButton("Tomorrow", callback_data="tomorrow")],
        [InlineKeyboardButton("📅 Select from Calendar", callback_data="calendar")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "Please select the flight date:",
        reply_markup=reply_markup
    )
    return FLIGHT_DATE

async def date_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle date selection."""
    query = update.callback_query
    await query.answer()
    
    if query.data == "calendar":
        # Show calendar for current month
        await show_calendar(query.message, context)
        return FLIGHT_DATE
    
    # Calculate date based on selection
    today = datetime.now()
    if query.data == "today":
        flight_date = today.strftime("%Y%m%d")
    elif query.data == "tomorrow":
        flight_date = (today + timedelta(days=1)).strftime("%Y%m%d")
    elif query.data.startswith("date_"):
        # Handle calendar date selection
        selected_date = datetime.strptime(query.data[5:], "%Y%m%d")
        flight_date = selected_date.strftime("%Y%m%d")
    else:
        return FLIGHT_DATE
    
    return await save_flight_data(update, context, flight_date)

async def show_calendar(message, context: ContextTypes.DEFAULT_TYPE):
    """Display an inline calendar for date selection."""
    now = datetime.now()
    year = now.year
    month = now.month
    
    # Create calendar matrix
    cal = monthcalendar(year, month)
    
    # Create keyboard with calendar
    keyboard = []
    
    # Add month and year header
    month_year = now.strftime("%B %Y")
    keyboard.append([InlineKeyboardButton(month_year, callback_data="ignore")])
    
    # Add weekday headers
    weekdays = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
    keyboard.append([InlineKeyboardButton(day, callback_data="ignore") for day in weekdays])
    
    # Add calendar days
    for week in cal:
        row = []
        for day in week:
            if day == 0:
                # Empty day
                btn = InlineKeyboardButton(" ", callback_data="ignore")
            else:
                # Create date string in YYYYMMDD format
                date = datetime(year, month, day)
                date_str = date.strftime("%Y%m%d")
                
                # Only allow selecting current or future dates
                if date >= now.replace(hour=0, minute=0, second=0, microsecond=0):
                    btn = InlineKeyboardButton(
                        str(day),
                        callback_data=f"date_{date_str}"
                    )
                else:
                    btn = InlineKeyboardButton(" ", callback_data="ignore")
            row.append(btn)
        keyboard.append(row)
    
    # Add cancel button
    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await message.edit_text(
        "Please select a date from the calendar:",
        reply_markup=reply_markup
    )

async def save_flight_data(update: Update, context: ContextTypes.DEFAULT_TYPE, flight_date):
    """Save flight data to database and start tracking."""
    chat_id = update.effective_chat.id
    airline = context.user_data['airline']
    flight_number = context.user_data['flight_number']
    
    conn = sqlite3.connect('flights.db')
    c = conn.cursor()
    
    # Insert new tracking record
    c.execute('''
        INSERT OR REPLACE INTO flight_tracks (chat_id, airline, flight_number, flight_date)
        VALUES (?, ?, ?, ?)
    ''', (chat_id, airline, flight_number, flight_date))
    
    # Get all chat_ids for this flight
    c.execute('''
        SELECT chat_id 
        FROM flight_tracks 
        WHERE airline = ? AND flight_number = ? AND flight_date = ?
    ''', (airline, flight_number, flight_date))
    
    chat_ids = [row[0] for row in c.fetchall()]
    conn.commit()
    conn.close()
    
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"Flight tracking set up for:\nAirline: {airline}\nFlight: {flight_number}\nDate: {flight_date}"
    )
    
    # Start immediate check with all relevant chat_ids
    await check_flight_status(
        context.bot,
        chat_ids,
        airline,
        flight_number,
        flight_date
    )
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel the conversation."""
    await update.message.reply_text('Flight tracking setup cancelled.')
    return ConversationHandler.END

# Flight status checking
async def check_flight_status(bot, chat_ids, airline, flight_number, flight_date):
    """Check flight status using the API and notify multiple chat IDs."""
    api_key = os.getenv('FLIGHTAPI_KEY')
    url = f"https://api.flightapi.io/airline/{api_key}?num={flight_number}&name={airline}&date={flight_date}"
    
    logger.info(f"Checking flight status - Airline: {airline}, Flight: {flight_number}, Date: {flight_date}")
    logger.info(f"Will notify chat IDs: {chat_ids}")
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    logger.info(f"Successfully fetched flight data for {airline} {flight_number}")
                    
                    # Format flight data as a card
                    try:
                        departure_info = data[0]['departure'][0]
                        arrival_info = data[1]['arrival'][0]
                        
                        # Get status and emoji
                        status = departure_info.get('status', 'Unknown')
                        status_emoji = get_status_emoji(status)
                        
                        message = (
                            f"✈️ *Flight {airline} {flight_number}*\n\n"
                            f"*Status:* {status_emoji} {status}\n\n"
                            f"*Departure:*\n"
                            f"🌍 {departure_info['Airport:']}\n"
                            f"🕒 {departure_info['Scheduled Time:']}\n\n"
                            f"*Arrival:*\n"
                            f"📍 {arrival_info['Airport:']}\n"
                            f"🕒 {arrival_info['Scheduled Time:']}\n"
                        )
                    except (KeyError, IndexError) as e:
                        logger.error(f"Error parsing flight data: {str(e)}")
                        message = "Error: Could not parse flight information"
                else:
                    error_text = await response.text()
                    logger.error(f"API request failed with status {response.status}: {error_text}")
                    message = f"Error: Could not fetch flight status. Status code: {response.status}"
                
                # Send message to all chat IDs
                for chat_id in chat_ids:
                    try:
                        await bot.send_message(
                            chat_id=chat_id,
                            text=message,
                            parse_mode='Markdown'
                        )
                        logger.info(f"Sent flight status update to chat_id: {chat_id}")
                    except Exception as e:
                        logger.error(f"Failed to send message to chat_id {chat_id}: {str(e)}")
                        
        except aiohttp.ClientError as e:
            logger.error(f"Network error while fetching flight data: {str(e)}")
            message = "Error: Could not connect to flight status service"
            for chat_id in chat_ids:
                try:
                    await bot.send_message(
                        chat_id=chat_id,
                        text=message
                    )
                except Exception as send_error:
                    logger.error(f"Failed to send error message to chat_id {chat_id}: {str(send_error)}")
        except Exception as e:
            logger.error(f"Unexpected error checking flight status: {str(e)}")

def get_status_emoji(status):
    """Return appropriate emoji for flight status."""
    status = status.lower()
    if 'scheduled' in status:
        return '📅'
    elif 'active' in status or 'en route' in status:
        return '✈️'
    elif 'landed' in status:
        return '🛬'
    elif 'delayed' in status:
        return '⏰'
    elif 'cancelled' in status:
        return '❌'
    return '❓'

async def periodic_flight_check(application: Application):
    """Check all tracked flights every hour."""
    while True:
        await asyncio.sleep(int(os.getenv('FLIGHTAPI_POLL_INTERVAL', '3600')))
        conn = sqlite3.connect('flights.db')
        c = conn.cursor()
        
        # Get current date in YYYYMMDD format
        current_date = datetime.now().strftime("%Y%m%d")
        
        # Group by flight details and collect chat_ids
        c.execute('''
            SELECT 
                airline,
                flight_number,
                flight_date,
                GROUP_CONCAT(chat_id) as chat_ids
            FROM flight_tracks 
            WHERE flight_date >= ?
            GROUP BY airline, flight_number, flight_date
        ''', (current_date,))
        
        grouped_flights = c.fetchall()
        conn.close()
        
        for airline, flight_number, flight_date, chat_ids_str in grouped_flights:
            # Convert chat_ids string to list of integers
            chat_ids = [int(id) for id in chat_ids_str.split(',')]
            await check_flight_status(
                application.bot,
                chat_ids,
                airline,
                flight_number,
                flight_date
            )
        

async def payment_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the payment command using XTR"""
    chat_id = update.message.chat_id
    title = "Flight Tracking Service"
    description = "Access to flight tracking features"
    payload = "Flight-Tracker-Payment"
    currency = "XTR"
    prices = [LabeledPrice("Flight Tracking", int(XTR_PRICE * 100))]  # Convert to smallest currency unit

    await context.bot.send_invoice(
        chat_id=chat_id,
        title=title,
        description=description,
        payload=payload,
        provider_token="",  # Empty token for digital goods
        currency=currency,
        prices=prices,
        start_parameter="start_parameter"
    )

async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the precheckout callback"""
    query = update.pre_checkout_query
    if query.invoice_payload != 'Flight-Tracker-Payment':
        await query.answer(ok=False, error_message="Something went wrong...")
    else:
        await query.answer(ok=True)

async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle successful payments"""
    payment = update.message.successful_payment
    telegram_payment_charge_id = payment.telegram_payment_charge_id
    
    await update.message.reply_text(
        f"✅ Payment successful!\n\n"
        f"Payment ID: `{telegram_payment_charge_id}`\n\n"
        "You now have access to flight tracking features. Use /flight to start tracking flights.",
        parse_mode='Markdown'
    )

def main():
    """Start the bot."""
    # Setup database
    setup_database()
    
    # Create the Application and pass it your bot's token with job queue enabled
    application = (
        Application.builder()
        .token(os.getenv('BOT_TOKEN'))
        .build()
    )
    
    # Initialize job queue
    job_queue = application.job_queue

    # Add conversation handler for flight tracking
    flight_conv_handler = ConversationHandler(
        entry_points=[CommandHandler('flight', flight_command)],
        states={
            AIRLINE: [MessageHandler(filters.TEXT & ~filters.COMMAND, airline_step)],
            FLIGHT_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, flight_number_step)],
            FLIGHT_DATE: [
                CallbackQueryHandler(date_step),
            ],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
        per_message=False,
        per_chat=True,
        per_user=True,
    )
    
    # Add handlers
    application.add_handler(flight_conv_handler)
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown_command))
    application.add_handler(CommandHandler("payment", payment_command))
    application.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))

    # Start periodic flight checking using job_queue
    async def periodic_check(context: ContextTypes.DEFAULT_TYPE):
        await periodic_flight_check(application)
    
    job_queue.run_repeating(periodic_check, interval=3600, first=10)

    # Start the Bot
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main() 