#!/bin/bash
# Run once on fresh EC2 Ubuntu server
set -e

echo "=== Server Init: Viviz WhatsApp Business ==="

APP_DIR=/home/ubuntu/whatsapp-business

# System deps
sudo apt update -y
sudo apt install -y python3-pip python3-venv nginx certbot python3-certbot-nginx git

# App directory
sudo mkdir -p $APP_DIR
sudo chown ubuntu:ubuntu $APP_DIR

# Systemd service
sudo cp $APP_DIR/whatsapp-business.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable whatsapp-business

# Nginx
sudo cp $APP_DIR/nginx.conf /etc/nginx/sites-available/whatsapp-business
sudo ln -sf /etc/nginx/sites-available/whatsapp-business /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx

# SSL (run after DNS is pointed)
# sudo certbot --nginx -d wa.viviztech.in --non-interactive --agree-tos -m admin@viviztech.in

echo "✅ Server initialized!"
echo "   1. Upload files: bash scripts/deploy.sh"
echo "   2. Run setup:    bash scripts/setup.sh"
echo "   3. Fill .env:    nano /home/ubuntu/whatsapp-business/.env"
echo "   4. Start:        sudo systemctl start whatsapp-business"
echo "   5. SSL:          sudo certbot --nginx -d wa.viviztech.in"
