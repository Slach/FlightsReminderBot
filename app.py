from flask import Flask, render_template
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()

app = Flask(__name__)

# Configuration from environment variables
app.config.update(
    SECRET_KEY=os.getenv('FLASK_SECRET_KEY'),
    MERCHANT_USDT_WALLET=os.getenv('MERCHANT_USDT_WALLET'),
    PAYMENT_AMOUNT=float(os.getenv('PAYMENT_AMOUNT', '1.0')),  # Default 1 USDT
    TON_NETWORK=os.getenv('TON_NETWORK', 'mainnet')  # or 'testnet'
)

@app.route('/')
def index():
    return render_template('index.html',
                         wallet_address=app.config['MERCHANT_USDT_WALLET'],
                         amount=app.config['PAYMENT_AMOUNT'])

@app.route('/process_payment', methods=['POST'])
def process_payment():
    # Here you would implement the payment processing logic
    # This is just a placeholder that returns success
    return {'status': 'success'}

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000) 