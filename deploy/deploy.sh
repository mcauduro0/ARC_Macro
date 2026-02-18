#!/bin/bash
#
# BRLUSD Dashboard — DigitalOcean Deployment Script
# Run this on a fresh Ubuntu 22.04 Droplet (4 vCPU, 8GB RAM recommended)
#
# Usage: bash deploy.sh
#
set -euo pipefail

APP_DIR="/opt/brlusd-dashboard"
REPO_URL=""  # Will be set after GitHub export
NODE_VERSION="22"
PYTHON_VERSION="3.11"

echo "============================================"
echo "  BRLUSD Dashboard — DigitalOcean Setup"
echo "============================================"

# ── 1. System Update ──────────────────────────────────────────────────
echo "[1/10] Updating system packages..."
apt-get update -y && apt-get upgrade -y
apt-get install -y curl wget git build-essential software-properties-common \
  nginx certbot python3-certbot-nginx ufw

# ── 2. Node.js 22 ────────────────────────────────────────────────────
echo "[2/10] Installing Node.js ${NODE_VERSION}..."
if ! command -v node &> /dev/null; then
  curl -fsSL https://deb.nodesource.com/setup_${NODE_VERSION}.x | bash -
  apt-get install -y nodejs
fi
npm install -g pnpm pm2

echo "  Node: $(node --version)"
echo "  pnpm: $(pnpm --version)"
echo "  PM2:  $(pm2 --version)"

# ── 3. Python 3.11 ───────────────────────────────────────────────────
echo "[3/10] Installing Python ${PYTHON_VERSION}..."
add-apt-repository -y ppa:deadsnakes/ppa
apt-get update -y
apt-get install -y python${PYTHON_VERSION} python${PYTHON_VERSION}-venv python${PYTHON_VERSION}-dev
# Create symlink if needed
if ! command -v python3.11 &> /dev/null; then
  ln -sf /usr/bin/python${PYTHON_VERSION} /usr/bin/python3.11
fi
# Install pip
python3.11 -m ensurepip --upgrade 2>/dev/null || true
python3.11 -m pip install --upgrade pip

echo "  Python: $(python3.11 --version)"

# ── 4. MySQL 8.0 ─────────────────────────────────────────────────────
echo "[4/10] Installing MySQL 8.0..."
if ! command -v mysql &> /dev/null; then
  apt-get install -y mysql-server
  systemctl start mysql
  systemctl enable mysql
fi

# Create database and user
echo "[4b/10] Configuring MySQL database..."
mysql -u root <<EOF
CREATE DATABASE IF NOT EXISTS brlusd_dashboard CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'brlusd'@'localhost' IDENTIFIED BY '$(openssl rand -base64 24)';
GRANT ALL PRIVILEGES ON brlusd_dashboard.* TO 'brlusd'@'localhost';
FLUSH PRIVILEGES;
EOF

echo "  MySQL: $(mysql --version)"
echo ""
echo "  ⚠️  IMPORTANT: Note the MySQL password above or set it in .env"
echo "  DATABASE_URL=mysql://brlusd:<PASSWORD>@localhost:3306/brlusd_dashboard"
echo ""

# ── 5. Firewall ──────────────────────────────────────────────────────
echo "[5/10] Configuring firewall..."
ufw allow OpenSSH
ufw allow 'Nginx Full'
ufw --force enable

# ── 6. Clone/Pull Application ────────────────────────────────────────
echo "[6/10] Setting up application..."
mkdir -p ${APP_DIR}

if [ -d "${APP_DIR}/.git" ]; then
  echo "  Pulling latest changes..."
  cd ${APP_DIR} && git pull
else
  if [ -n "${REPO_URL}" ]; then
    echo "  Cloning repository..."
    git clone ${REPO_URL} ${APP_DIR}
  else
    echo "  ⚠️  No REPO_URL set. Copy files manually to ${APP_DIR}"
    echo "  Or set REPO_URL at the top of this script and re-run."
  fi
fi

cd ${APP_DIR}

# ── 7. Install Dependencies ──────────────────────────────────────────
echo "[7/10] Installing Node.js dependencies..."
pnpm install --frozen-lockfile 2>/dev/null || pnpm install

echo "[7b/10] Installing Python dependencies..."
python3.11 -m pip install -r server/model/requirements.txt

# ── 8. Build Application ─────────────────────────────────────────────
echo "[8/10] Building application..."
# Build frontend + backend with DO entry point
pnpm run build:do

# ── 9. Database Migration ────────────────────────────────────────────
echo "[9/10] Running database migrations..."
pnpm db:push

# ── 10. Start with PM2 ───────────────────────────────────────────────
echo "[10/10] Starting application with PM2..."
pm2 delete brlusd-dashboard 2>/dev/null || true
pm2 start ecosystem.config.cjs
pm2 save
pm2 startup systemd -u root --hp /root 2>/dev/null || true

echo ""
echo "============================================"
echo "  ✅ Deployment Complete!"
echo "============================================"
echo ""
echo "  App:    http://$(curl -s ifconfig.me):3000"
echo "  Status: pm2 status"
echo "  Logs:   pm2 logs brlusd-dashboard"
echo ""
echo "  Next steps:"
echo "  1. Edit ${APP_DIR}/.env with your API keys"
echo "  2. Configure Nginx reverse proxy (see deploy/nginx.conf)"
echo "  3. Restart: pm2 restart brlusd-dashboard"
echo ""
