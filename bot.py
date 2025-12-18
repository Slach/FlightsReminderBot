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
from typing import List, Dict, Any
import json
import base64
from PIL import Image
from io import BytesIO
import fitz  # PyMuPDF for PDF processing
import requests
from ticket_ocr import allowed_file, process_pdf, process_image

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

# Add new function to handle Aviationstack API calls
async def check_flight_aviationstack(session: aiohttp.ClientSession, 
                                   flight_number: str, 
                                   airline_iata: str, 
                                   flight_date: str) -> Dict[str, Any]:
    """Check flight status using Aviationstack API."""
    api_key = os.getenv('AVIATIONSTACK_KEY')
    base_url = "http://api.aviationstack.com/v1/flights"
    
    params = {
        'access_key': api_key,
        'flight_date': datetime.strptime(flight_date, "%Y%m%d").strftime("%Y-%m-%d"),
        'flight_number': flight_number,
        'airline_iata': airline_iata
    }
    
    try:
        async with session.get(base_url, params=params) as response:
            if response.status == 200:
                data = await response.json()
                if data.get('data'):
                    return data['data'][0]  # Return first matching flight
            return None
    except Exception as e:
        logger.error(f"Aviationstack API error: {str(e)}")
        return None

# Add new function to handle FlightAPI calls
async def check_flight_flightapi(session: aiohttp.ClientSession,
                               flight_number: str,
                               airline: str,
                               flight_date: str) -> Dict[str, Any]:
    """Check flight status using FlightAPI."""
    api_key = os.getenv('FLIGHTAPI_KEY')
    url = f"https://api.flightapi.io/airline/{api_key}"
    
    params = {
        'num': flight_number,
        'name': airline,
        'date': flight_date
    }
    
    try:
        async with session.get(url, params=params) as response:
            if response.status == 200:
                data = await response.json()
                return data
            return None
    except Exception as e:
        logger.error(f"FlightAPI error: {str(e)}")
        return None

# Format response for Aviationstack
def format_aviationstack_response(flight_data: Dict[str, Any]) -> str:
    """Format Aviationstack API response into a message."""
    try:
        status = flight_data.get('flight_status', 'Unknown')
        status_emoji = get_status_emoji(status)
        
        departure = flight_data.get('departure', {})
        arrival = flight_data.get('arrival', {})
        
        message = (
            f"✈️ *Flight {flight_data.get('airline', {}).get('iata', '')} {flight_data.get('flight', {}).get('number', '')}*\n\n"
            f"*Status:* {status_emoji} {status}\n\n"
            f"*Departure:*\n"
            f"🌍 {departure.get('airport', 'Unknown')}\n"
            f"🕒 {departure.get('scheduled', 'Unknown')}\n"
            f"🚪 Terminal: {departure.get('terminal', 'N/A')}\n"
            f"🚶 Gate: {departure.get('gate', 'N/A')}\n\n"
            f"*Arrival:*\n"
            f"📍 {arrival.get('airport', 'Unknown')}\n"
            f"🕒 {arrival.get('scheduled', 'Unknown')}\n"
            f" Terminal: {arrival.get('terminal', 'N/A')}\n"
            f"🚶 Gate: {arrival.get('gate', 'N/A')}"
        )
        
        if flight_data.get('live'):
            live = flight_data['live']
            message += (
                f"\n\n*Live Data:*\n"
                f"📍 Latitude: {live.get('latitude', 'N/A')}\n"
                f"📍 Longitude: {live.get('longitude', 'N/A')}\n"
                f"✈️ Altitude: {live.get('altitude', 'N/A')}m\n"
                f"🎯 Direction: {live.get('direction', 'N/A')}°"
            )
        
        return message
    except Exception as e:
        logger.error(f"Error formatting Aviationstack response: {str(e)}")
        return "Error formatting flight information"

async def periodic_flight_check(application: Application):
    """Check all tracked flights periodically based on configured provider."""
    api_provider = os.getenv('API_PROVIDER', 'aviationstack').lower()
    
    # Database connection and query
    conn = sqlite3.connect('flights.db')
    c = conn.cursor()
    current_date = datetime.now().strftime("%Y%m%d")
    
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
    
    async with aiohttp.ClientSession() as session:
        for airline, flight_number, flight_date, chat_ids_str in grouped_flights:
            chat_ids = [int(id) for id in chat_ids_str.split(',')]
            
            try:
                if api_provider == 'aviationstack':
                    # Assume airline is IATA code for Aviationstack
                    flight_data = await check_flight_aviationstack(
                        session, 
                        flight_number,
                        airline,  # Using airline as IATA code
                        flight_date
                    )
                    if flight_data:
                        message = format_aviationstack_response(flight_data)
                    else:
                        message = "Could not fetch flight information"
                        
                else:  # Default to FlightAPI
                    flight_data = await check_flight_flightapi(
                        session,
                        flight_number,
                        airline,
                        flight_date
                    )
                    if flight_data:
                        # Use existing format for FlightAPI response
                        message = format_flight_data(flight_data)
                    else:
                        message = "Could not fetch flight information"
                
                # Send updates to all subscribed users
                for chat_id in chat_ids:
                    try:
                        await application.bot.send_message(
                            chat_id=chat_id,
                            text=message,
                            parse_mode='Markdown'
                        )
                        logger.info(f"Sent flight update to chat_id: {chat_id}")
                    except Exception as e:
                        logger.error(f"Failed to send message to chat_id {chat_id}: {str(e)}")
                        
            except Exception as e:
                logger.error(f"Error checking flight status: {str(e)}")
                continue

# Add helper function to format FlightAPI response
def format_flight_data(flight_data: Dict[str, Any]) -> str:
    """Format FlightAPI response into a message."""
    try:
        departure_info = flight_data[0]['departure'][0]
        arrival_info = flight_data[1]['arrival'][0]
        
        status = departure_info.get('status', 'Unknown')
        status_emoji = get_status_emoji(status)
        
        message = (
            f"✈️ *Flight Status Update*\n\n"
            f"*Status:* {status_emoji} {status}\n\n"
            f"*Departure:*\n"
            f"🌍 {departure_info.get('Airport:', 'Unknown')}\n"
            f"🕒 {departure_info.get('Scheduled Time:', 'Unknown')}\n\n"
            f"*Arrival:*\n"
            f"📍 {arrival_info.get('Airport:', 'Unknown')}\n"
            f"🕒 {arrival_info.get('Scheduled Time:', 'Unknown')}"
        )
        return message
    except Exception as e:
        logger.error(f"Error formatting FlightAPI response: {str(e)}")
        return "Error formatting flight information"

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

# Add new constants
ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'pdf'}
OLLAMA_API_URL = "http://ollama:11434/api/generate"

# Add helper functions
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

async def process_image(image_data):
    """Process image using Ollama vision model"""
    # Convert image to base64
    image_base64 = base64.b64encode(image_data).decode('utf-8')
    
    # Prepare the prompt from file
    with open('ollama/prompt.txt', 'r') as f:
        prompt = f.read()
    
    # Prepare request to Ollama
    payload = {
        "model": "llama3.2-vision",
        "prompt": prompt,
        "images": [image_base64],
        "stream": False
    }
    
    # Make request to Ollama
    response = requests.post(OLLAMA_API_URL, json=payload)
    if response.status_code == 200:
        try:
            result = response.json()
            return json.loads(result['response'])  # Parse the JSON response
        except json.JSONDecodeError:
            return None
    return None

async def process_pdf(pdf_data):
    """Process PDF using Ollama vision model"""
    results = []
    
    # Open PDF
    pdf_document = fitz.open(stream=pdf_data, filetype="pdf")
    
    # Process each page
    for page_num in range(len(pdf_document)):
        page = pdf_document[page_num]
        
        # Convert page to image
        pix = page.get_pixmap()
        img_data = pix.tobytes("png")
        
        # Process the image
        result = await process_image(img_data)
        if result:
            results.append(result)
    
    # Combine results
    combined_results = {
        "segments": []
    }
    for result in results:
        if result and "segments" in result:
            combined_results["segments"].extend(result["segments"])
    
    return combined_results

# Add new handler for file uploads
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle uploaded documents"""
    message = update.message
    
    if not message.document:
        await message.reply_text("Please send a document file.")
        return
    
    file = message.document
    if not allowed_file(file.file_name):
        await message.reply_text(
            f"Sorry, only {', '.join(ALLOWED_EXTENSIONS)} files are supported."
        )
        return
    
    # Download the file
    file_obj = await context.bot.get_file(file.file_id)
    file_data = await file_obj.download_as_bytearray()
    
    # Process based on file type
    file_ext = file.file_name.rsplit('.', 1)[1].lower()
    
    await message.reply_text("Processing your file... Please wait.")
    
    try:
        if file_ext == 'pdf':
            result = await process_pdf(file_data)
        else:  # image files
            result = await process_image(file_data)
        
        if result and result.get('segments'):
            # Format response message
            response = "*Flight Information Extracted:*\n\n"
            for idx, segment in enumerate(result['segments'], 1):
                response += f"*Flight Segment {idx}:*\n"
                response += f"Flight: `{segment.get('flight_number', 'N/A')}`\n"
                
                dep = segment.get('departure', {})
                response += f"From: {dep.get('airport', 'N/A')} ({dep.get('code', 'N/A')})\n"
                response += f"Departure: {dep.get('datetime', 'N/A')}\n"
                
                arr = segment.get('arrival', {})
                response += f"To: {arr.get('airport', 'N/A')} ({arr.get('code', 'N/A')})\n"
                response += f"Arrival: {arr.get('datetime', 'N/A')}\n"
                
                for passenger in segment.get('passengers', []):
                    response += f"Passenger: {passenger.get('name', 'N/A')}\n"
                    response += f"Seat: {passenger.get('seat', 'N/A')}\n"
                
                cost = segment.get('cost', {})
                if cost.get('amount'):
                    response += f"Cost: {cost.get('amount')} {cost.get('currency', '')}\n"
                
                response += "\n"
            
            await message.reply_text(response, parse_mode='Markdown')
        else:
            await message.reply_text(
                "Sorry, I couldn't extract flight information from this document."
            )
    except Exception as e:
        logger.error(f"Error processing file: {str(e)}")
        await message.reply_text(
            "Sorry, there was an error processing your file. Please try again."
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
    application.add_handler(MessageHandler(
        filters.Document.ALL & ~filters.COMMAND,
        handle_document
    ))

    # Start periodic flight checking using job_queue
    async def periodic_check(context: ContextTypes.DEFAULT_TYPE):
        await periodic_flight_check(application)
    
    job_queue.run_repeating(periodic_check, interval=int(os.getenv('API_POLL_INTERVAL', '3600')), first=10)

    # Start the Bot
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main() 