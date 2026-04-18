#!/bin/bash
set -e

APP_DIR=/home/ubuntu/whatsapp-business
SERVICE=whatsapp-business

echo "=== Deploying Viviz WhatsApp Business ==="

# Upload from local
rsync -avz --exclude='.env' --exclude='*.db' --exclude='__pycache__' \
  --exclude='.git' --exclude='venv' --exclude='logs' \
  -e "ssh -i ~/.ssh/copytrade-key.pem" \
  ~/projects/whatsapp-business/ \
  ubuntu@13.205.180.69:$APP_DIR/

echo "📦 Files uploaded. Restarting service..."
ssh -i ~/.ssh/copytrade-key.pem ubuntu@13.205.180.69 "
  cd $APP_DIR
  source venv/bin/activate
  pip install -r requirements.txt -q
  sudo systemctl restart $SERVICE
  sudo systemctl status $SERVICE --no-pager
"
echo "✅ Deployment complete!"
