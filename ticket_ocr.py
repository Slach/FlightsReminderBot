import json
import base64
import fitz  # PyMuPDF for PDF processing
import requests
from typing import Dict, Any

ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'pdf'}
OLLAMA_API_URL = "http://ollama:11434/api/generate"

def allowed_file(filename: str) -> bool:
    """Check if file has an allowed extension."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

async def process_image(image_data: bytes) -> Dict[str, Any]:
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

async def process_pdf(pdf_data: bytes) -> Dict[str, Any]:
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