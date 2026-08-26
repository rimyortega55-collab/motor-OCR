#!/usr/bin/env bash
# Preparacion del entorno de desarrollo en Codespaces.
set -euo pipefail

echo ">> Dependencias de sistema"
sudo apt-get update -qq
# libgl1 y libglib2.0-0: OpenCV las carga al importarse y no vienen en la imagen.
# tesseract: motor de respaldo del pipeline (pytesseract).
sudo apt-get install -y -qq \
    libgl1 \
    libglib2.0-0 \
    tesseract-ocr \
    tesseract-ocr-spa \
    tesseract-ocr-eng

echo ">> Paquete y dependencias de Python"
pip install --upgrade pip -q
pip install -e ".[dev]" -q

echo ">> Verificacion de hardware"
python - <<'PY'
import cpuinfo
flags = set(cpuinfo.get_cpu_info().get("flags", []))
print("CPU :", cpuinfo.get_cpu_info().get("brand_raw"))
for f in ("avx", "avx2", "fma"):
    print(f"  {f:5}: {'SI' if f in flags else 'NO'}")
if "avx2" not in flags:
    print("  AVISO: sin AVX2 la inferencia de docTR/easyocr sera lenta.")
PY

echo ">> Listo. Probar con: python pruebas/test_capa1.py"
