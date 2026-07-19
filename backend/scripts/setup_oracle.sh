#!/bin/bash
# Setup AI-Agent-JIRA backend on Oracle Cloud (Oracle Linux / RHEL-based)
# Run as: bash setup_oracle.sh
set -e

APP_DIR="$HOME/AI-Agent-JIRA"
SERVICE_NAME="ai-agent-jira"
PORT=8000

echo "=== [1/7] System packages ==="
sudo dnf install -y git curl unzip wget make
sudo dnf install -y gcc openssl-devel bzip2-devel libffi-devel zlib-devel

# Install Python 3.11 — try dnf first, compile from source if unavailable
if ! command -v python3.11 &>/dev/null; then
    if sudo dnf install -y python3.11 2>/dev/null; then
        echo "python3.11 installed via dnf"
    else
        echo "python3.11 not in repos — compiling from source (takes ~5 min)..."
        PYTHON_VERSION="3.11.9"
        cd /tmp
        wget -q "https://www.python.org/ftp/python/${PYTHON_VERSION}/Python-${PYTHON_VERSION}.tgz"
        tar xzf "Python-${PYTHON_VERSION}.tgz"
        cd "Python-${PYTHON_VERSION}"
        ./configure --enable-optimizations --quiet
        make -j"$(nproc)" --quiet
        sudo make altinstall --quiet
        cd ~
        rm -rf "/tmp/Python-${PYTHON_VERSION}" "/tmp/Python-${PYTHON_VERSION}.tgz"
        echo "python3.11 compiled and installed"
    fi
fi

# Ensure pip for 3.11
python3.11 -m ensurepip --upgrade 2>/dev/null || true

echo "=== [2/7] Clone or update repo ==="
if [ -d "$APP_DIR" ]; then
    echo "Repo exists — pulling latest"
    cd "$APP_DIR" && git pull
else
    echo "Enter GitHub repo URL (or press Enter to skip and upload manually):"
    read -r REPO_URL
    if [ -n "$REPO_URL" ]; then
        git clone "$REPO_URL" "$APP_DIR"
    else
        echo "Skipping clone. Upload your code to $APP_DIR manually, then re-run."
        mkdir -p "$APP_DIR/backend"
        exit 0
    fi
fi

echo "=== [3/7] Python venv + dependencies ==="
cd "$APP_DIR/backend"
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip setuptools -q
pip install -r requirements.txt -q

echo "=== [4/7] Environment file ==="
if [ ! -f "$APP_DIR/backend/.env" ]; then
    cp "$APP_DIR/backend/.env.example" "$APP_DIR/backend/.env" 2>/dev/null || cat > "$APP_DIR/backend/.env" << 'EOF'
GROQ_API_KEY=
GROQ_MODEL=llama-3.3-70b-versatile
JIRA_BASE_URL=
JIRA_EMAIL=
JIRA_API_TOKEN=
JIRA_PROJECT_KEY=DEMO
LANGSMITH_API_KEY=
LANGSMITH_PROJECT=
EOF
    echo ""
    echo ">>> .env created at $APP_DIR/backend/.env"
    echo ">>> Edit it now to add your API keys:"
    echo "    nano $APP_DIR/backend/.env"
    echo ""
    read -p "Press Enter after editing .env to continue..."
fi

echo "=== [5/7] systemd service ==="
VENV_PYTHON="$APP_DIR/backend/.venv/bin/python"
VENV_UVICORN="$APP_DIR/backend/.venv/bin/uvicorn"

sudo tee /etc/systemd/system/${SERVICE_NAME}.service > /dev/null << EOF
[Unit]
Description=AI Agent JIRA Backend
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$APP_DIR/backend
EnvironmentFile=$APP_DIR/backend/.env
ExecStart=$VENV_UVICORN app.main:app --host 0.0.0.0 --port $PORT
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable ${SERVICE_NAME}
sudo systemctl restart ${SERVICE_NAME}

echo "=== [6/7] Firewall — open port $PORT ==="
# Ubuntu ufw
if command -v ufw &>/dev/null; then
    sudo ufw allow ${PORT}/tcp
    sudo ufw --force enable
fi

# Oracle Cloud also blocks ports via iptables rules (even if ufw allows)
# This inserts a rule before the default REJECT at the end
if sudo iptables -L INPUT -n | grep -q "REJECT\|DROP"; then
    sudo iptables -I INPUT 6 -p tcp --dport ${PORT} -j ACCEPT
    # Persist iptables rules
    sudo dnf install -y -q iptables-services
    sudo service iptables save
fi

echo "=== [7/7] Status ==="
sleep 2
sudo systemctl status ${SERVICE_NAME} --no-pager -l

PUBLIC_IP=$(curl -s ifconfig.me 2>/dev/null || echo "<your-public-ip>")
echo ""
echo "================================================"
echo " Backend running at: http://${PUBLIC_IP}:${PORT}"
echo " Health check:       http://${PUBLIC_IP}:${PORT}/health"
echo " Logs:               journalctl -u ${SERVICE_NAME} -f"
echo " Restart:            sudo systemctl restart ${SERVICE_NAME}"
echo "================================================"
echo ""
echo "IMPORTANT: Also open port ${PORT} in Oracle Cloud Security List:"
echo "  OCI Console → VCN → Subnet → Security List → Ingress Rules"
echo "  Source: 0.0.0.0/0  Protocol: TCP  Port: ${PORT}"
