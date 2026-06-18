#!/usr/bin/env bash
# Install packages from /opt/airflow/requirements.txt with full dependency resolution.
#
# The image ships apache-airflow-providers-google (google-cloud-storage 3.x,
# gcsfs 2026.x). dbt-bigquery declares google-cloud-storage<3.2, which forces
# a downgrade to gcs 3.1.x. Newer gcsfs requires gcs>=3.9, so any requirements
# file that pulls dbt-bigquery MUST also cap gcsfs at <2025.1.0 to prevent
# pip from backtracking through hundreds of google-* versions and blowing
# past pod startup timeouts.
#
# Example requirements.txt for dbt:
#   gcsfs>=2024.6.0,<2025.1.0
#   dbt-core==1.9.8
#   dbt-bigquery==1.9.2
#
# Note: dbt-core >=1.9.9 requires protobuf>=6 (incompatible with image's 5.29.6);
# dbt-core <=1.8 requires protobuf<5 (also incompatible). Pin to 1.9.0–1.9.8.
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

echo "Installing runtime packages from ${REQUIREMENTS_FILE}..."
pip install --no-cache-dir -r "${REQUIREMENTS_FILE}"
echo "${current_hash}" > "${MARKER_FILE}"
echo "Runtime package install complete"
