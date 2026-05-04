#!/bin/sh
# HF Hugging Face cache (/home/appuser/.cache/huggingface) is often a Docker volume
# owned by root: böylece appuser yazamaz. Bir kerelik chown sonra işlem kullanıcıda çalışır.
set -e
if [ "$(id -u)" = "0" ]; then
  mkdir -p /home/appuser/.cache/huggingface
  chown -R appuser:appuser /home/appuser/.cache/huggingface || true
  exec runuser -u appuser -- "$@"
fi
exec "$@"
