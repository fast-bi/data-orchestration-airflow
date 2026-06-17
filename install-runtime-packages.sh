#!/usr/bin/env bash
# Install packages from /opt/airflow/requirements.txt without pip dependency resolution.
#
# The image already ships apache-airflow-providers-google (google-cloud-storage 3.x).
# dbt-bigquery declares google-cloud-storage<3.2, so a normal `pip install -r`
# backtracks through hundreds of google-* versions and never finishes within pod
# startup timeouts. Runtime packages work with the image's google stack; we only
# need the wheels themselves.
set -euo pipefail

REQUIREMENTS_FILE="${1:-/opt/airflow/requirements.txt}"
MARKER_FILE="${2:-/home/airflow/.local/.runtime-requirements.sha256}"

if [[ ! -f "${REQUIREMENTS_FILE}" ]]; then
  echo "No requirements file at ${REQUIREMENTS_FILE}, skipping package install"
  exit 0
fi

if ! grep -qvE '^[[:space:]]*(#.*)?$' "${REQUIREMENTS_FILE}"; then
  echo "Requirements file is empty, skipping package install"
  exit 0
fi

current_hash="$(sha256sum "${REQUIREMENTS_FILE}" | awk '{print $1}')"
if [[ -f "${MARKER_FILE}" ]] && [[ "$(cat "${MARKER_FILE}")" == "${current_hash}" ]]; then
  echo "Requirements unchanged, skipping package install"
  exit 0
fi

echo "Installing runtime packages from ${REQUIREMENTS_FILE} (--no-deps)..."
pip install --no-cache-dir --no-deps -r "${REQUIREMENTS_FILE}"
echo "${current_hash}" > "${MARKER_FILE}"
echo "Runtime package install complete"
