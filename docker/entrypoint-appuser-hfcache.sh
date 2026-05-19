#!/bin/sh
# HF Hugging Face cache (/home/appuser/.cache/huggingface) is often a Docker volume
# owned by root: böylece appuser yazamaz. Bir kerelik chown sonra işlem kullanıcıda çalışır.
#
# ./logs host bind mount çoğu VPS’te root:root kalır; logger import’unda mkdir PermissionError olur.
# Root aşamasında log ağacını oluşturup appuser’a devrediyoruz.
set -e
if [ "$(id -u)" = "0" ]; then
  mkdir -p /home/appuser/.cache/huggingface
  chown -R appuser:appuser /home/appuser/.cache/huggingface || true
  mkdir -p /app/logs/challenge_service /app/logs/event_service /app/logs/feature_request_service
  chown -R appuser:appuser /app/logs
  exec runuser -u appuser -- "$@"
fi
exec "$@"
