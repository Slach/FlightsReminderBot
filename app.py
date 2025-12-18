from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv
import os
from werkzeug.utils import secure_filename
import asyncio
from ticket_ocr import allowed_file, process_pdf, process_image

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

# Add configuration
UPLOAD_FOLDER = 'uploads'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

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

@app.route('/upload', methods=['POST'])
async def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        try:
            # Process file based on type
            file_ext = filename.rsplit('.', 1)[1].lower()
            with open(filepath, 'rb') as f:
                file_data = f.read()
            
            if file_ext == 'pdf':
                result = await process_pdf(file_data)
            else:
                result = await process_image(file_data)
            
            # Clean up
            os.remove(filepath)
            
            return jsonify(result)
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    return jsonify({'error': 'Invalid file type'}), 400

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000) 