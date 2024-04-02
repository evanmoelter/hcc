#!/usr/bin/env bash
set -e
set -o noglob

# Setup fisher plugin manager for fish and install plugins
/usr/bin/fish -c "
curl -sL https://git.io/fisher | source && fisher install jorgebucaran/fisher
fisher install decors/fish-colored-man
fisher install edc/bass
fisher install jorgebucaran/autopair.fish
fisher install nickeb96/puffer-fish
fisher install PatrickF1/fzf.fish
"

# Create/update virtual environment
if ! grep -q "venv /workspaces/" .venv/pyvenv.cfg; then
    rm -rf .venv
fi
task workstation:venv

# Install terraform
/bin/bash -c "
sudo apk add --update --virtual .deps --no-cache gnupg && \
cd /tmp && \
wget https://releases.hashicorp.com/terraform/1.7.5/terraform_1.7.5_linux_amd64.zip && \
wget https://releases.hashicorp.com/terraform/1.7.5/terraform_1.7.5_SHA256SUMS && \
wget https://releases.hashicorp.com/terraform/1.7.5/terraform_1.7.5_SHA256SUMS.sig && \
wget -qO- https://www.hashicorp.com/.well-known/pgp-key.txt | gpg --import && \
gpg --verify terraform_1.7.5_SHA256SUMS.sig terraform_1.7.5_SHA256SUMS && \
grep terraform_1.7.5_linux_amd64.zip terraform_1.7.5_SHA256SUMS | sha256sum -c && \
unzip /tmp/terraform_1.7.5_linux_amd64.zip -d /tmp && \
sudo mv /tmp/terraform /usr/local/bin/terraform && \
rm -f /tmp/terraform_1.7.5_linux_amd64.zip terraform_1.7.5_SHA256SUMS 1.7.5/terraform_1.7.5_SHA256SUMS.sig && \
sudo apk del .deps
"
