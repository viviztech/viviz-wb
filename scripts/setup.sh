#!/bin/bash
set -e

echo "=== Viviz WhatsApp Business — Setup ==="

cd /home/ubuntu/whatsapp-business

# Create virtualenv
python3 -m venv venv
source venv/bin/activate

# Install deps
pip install --upgrade pip
pip install -r requirements.txt

# Create directories
mkdir -p logs app/static/{css,js,img}

# Copy env if not exists
if [ ! -f .env ]; then
  cp .env.example .env
  echo "⚠  .env created from .env.example — fill in your credentials!"
fi

echo "✅ Setup complete. Edit .env then run: sudo systemctl start whatsapp-business"
