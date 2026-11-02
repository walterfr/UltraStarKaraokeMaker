#!/usr/bin/env bash
# Instalador universal do USKMaker para Linux (Debian/Ubuntu/Mint, Fedora/RHEL/openSUSE, Arch e AppImage).
# Uso: curl -fsSL https://raw.githubusercontent.com/walterfr/UltraStarKaraokeMaker/main/packaging/linux/install.sh | bash
set -euo pipefail

REPO="walterfr/UltraStarKaraokeMaker"
echo "==> Consultando a última versão do USKMaker em github.com/${REPO}..."
RELEASE_JSON=$(curl -fsSL "https://api.github.com/repos/${REPO}/releases/latest")
TAG=$(echo "$RELEASE_JSON" | grep -m1 '"tag_name":' | cut -d'"' -f4)
VER="${TAG#v}"

if [ -z "$VER" ]; then
  echo "Erro: não foi possível determinar a versão mais recente." >&2
  exit 1
fi

echo "==> Versão encontrada: v${VER}"
TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT

if command -v apt-get >/dev/null 2>&1; then
  DEB_URL="https://github.com/${REPO}/releases/download/${TAG}/USKMaker_${VER}_amd64.deb"
  echo "==> Baixando pacote Debian/Ubuntu (${DEB_URL})..."
  curl -fL "$DEB_URL" -o "${TMP_DIR}/uskmaker.deb"
  sudo apt-get update -qq || true
  sudo apt-get install -y "${TMP_DIR}/uskmaker.deb"
  echo "==> USKMaker v${VER} instalado com sucesso!"
elif command -v dnf >/dev/null 2>&1; then
  RPM_URL="https://github.com/${REPO}/releases/download/${TAG}/USKMaker-${VER}-1.x86_64.rpm"
  echo "==> Baixando pacote RPM (${RPM_URL})..."
  curl -fL "$RPM_URL" -o "${TMP_DIR}/uskmaker.rpm"
  sudo dnf install -y "${TMP_DIR}/uskmaker.rpm"
  echo "==> USKMaker v${VER} instalado com sucesso!"
elif command -v zypper >/dev/null 2>&1; then
  RPM_URL="https://github.com/${REPO}/releases/download/${TAG}/USKMaker-${VER}-1.x86_64.rpm"
  echo "==> Baixando pacote RPM (${RPM_URL})..."
  curl -fL "$RPM_URL" -o "${TMP_DIR}/uskmaker.rpm"
  sudo zypper --non-interactive install --allow-unsigned-rpm "${TMP_DIR}/uskmaker.rpm"
  echo "==> USKMaker v${VER} instalado com sucesso!"
else
  APPIMAGE_URL="https://github.com/${REPO}/releases/download/${TAG}/USKMaker_${VER}_amd64.AppImage"
  DEST_DIR="${HOME}/.local/bin"
  mkdir -p "$DEST_DIR"
  echo "==> Baixando AppImage (${APPIMAGE_URL})..."
  curl -fL "$APPIMAGE_URL" -o "${DEST_DIR}/USKMaker.AppImage"
  chmod +x "${DEST_DIR}/USKMaker.AppImage"
  echo "==> USKMaker v${VER} salvo em ${DEST_DIR}/USKMaker.AppImage (com suporte a atualizações OTA)!"
fi
