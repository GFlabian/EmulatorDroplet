#!/usr/bin/env bash
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive
WORKER_DIR="/opt/EmulatorDroplet"
ANDROID_SDK_ROOT="/opt/android-sdk"

echo "[1/6] Installing system packages & KVM dependencies..."
apt-get update -y
apt-get install -y \
  git curl wget unzip jq python3 python3-pip python3-venv \
  openjdk-17-jdk-headless \
  qemu-kvm libvirt-daemon-system libvirt-clients bridge-utils \
  libpulse0 libnss3 libxcomposite1 libxcursor1 libxi6 libxtst6 libasound2t64 \
  libglib2.0-0 libsm6 libxrender1 libxrandr2 libfontconfig1

echo "[2/6] Setting up Android SDK at ${ANDROID_SDK_ROOT}..."
mkdir -p "${ANDROID_SDK_ROOT}/cmdline-tools"
if [ ! -f "${ANDROID_SDK_ROOT}/cmdline-tools/latest/bin/sdkmanager" ]; then
  CMDLINE_ZIP="/tmp/commandlinetools-linux.zip"
  curl -fsSL "https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip" -o "${CMDLINE_ZIP}"
  unzip -q -o "${CMDLINE_ZIP}" -d "${ANDROID_SDK_ROOT}/cmdline-tools"
  rm -rf "${ANDROID_SDK_ROOT}/cmdline-tools/latest"
  mv "${ANDROID_SDK_ROOT}/cmdline-tools/cmdline-tools" "${ANDROID_SDK_ROOT}/cmdline-tools/latest"
  rm -f "${CMDLINE_ZIP}"
fi

export ANDROID_SDK_ROOT="${ANDROID_SDK_ROOT}"
export ANDROID_HOME="${ANDROID_SDK_ROOT}"
export EMU_SDK_ROOT="${ANDROID_SDK_ROOT}"
export PATH="${ANDROID_SDK_ROOT}/cmdline-tools/latest/bin:${ANDROID_SDK_ROOT}/platform-tools:${ANDROID_SDK_ROOT}/emulator:${PATH}"

echo "[3/6] Accepting licenses and installing platform-tools, emulator, and Android 14/15/16 system images..."
yes | sdkmanager --licenses > /dev/null || true
sdkmanager --install \
  "platform-tools" \
  "emulator" \
  "platforms;android-36" \
  "platforms;android-35" \
  "platforms;android-34" \
  "system-images;android-36.1;google_apis;x86_64" \
  "system-images;android-35;google_apis;x86_64" \
  "system-images;android-34;google_apis;x86_64"

echo "[4/6] Setting up Python virtual environment in ${WORKER_DIR}..."
cd "${WORKER_DIR}"
python3 -m venv "${WORKER_DIR}/venv"
"${WORKER_DIR}/venv/bin/pip" install --upgrade pip
"${WORKER_DIR}/venv/bin/pip" install -r "${WORKER_DIR}/requirements.txt"

echo "[5/6] Creating systemd service freya-worker.service..."
cat >/etc/systemd/system/freya-worker.service <<EOF
[Unit]
Description=FreyaEmulator Worker API Server
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=${WORKER_DIR}
Environment="EMU_SDK_ROOT=${ANDROID_SDK_ROOT}"
Environment="ANDROID_SDK_ROOT=${ANDROID_SDK_ROOT}"
Environment="ANDROID_HOME=${ANDROID_SDK_ROOT}"
Environment="EMU_AVD_HOME=${WORKER_DIR}/avds"
Environment="ANDROID_AVD_HOME=${WORKER_DIR}/avds"
Environment="PATH=${ANDROID_SDK_ROOT}/cmdline-tools/latest/bin:${ANDROID_SDK_ROOT}/platform-tools:${ANDROID_SDK_ROOT}/emulator:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
ExecStart=${WORKER_DIR}/venv/bin/python ${WORKER_DIR}/server.py --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
EOF

echo "[6/6] Enabling and starting freya-worker..."
systemctl daemon-reload
systemctl enable freya-worker
systemctl restart freya-worker

echo "EmulatorDroplet Worker setup complete!"
