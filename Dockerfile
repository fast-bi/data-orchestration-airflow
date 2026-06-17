# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
ARG BASE_AIRFLOW_IMAGE=apache/airflow:2.11.2-python3.11
ARG AIRFLOW_VERSION
FROM ${BASE_AIRFLOW_IMAGE}
LABEL maintainer=support@fast.bi

SHELL ["/bin/bash", "-o", "pipefail", "-e", "-u", "-x", "-c"]

USER 0

# Bumped 512.0.0 -> 573.0.0: rebuilt Go binaries (gcloud-crc32c, gke-gcloud-auth-plugin)
# remediate CVE-2025-68121 (crypto/tls). kubectl is installed standalone below instead
# of via the gcloud component (the bundled multi-version kubectl ships old Go 1.22.x).
ARG CLOUD_SDK_VERSION=573.0.0
# Pinned kubectl built with patched Go (>=1.24.13) — also remediates CVE-2025-68121.
ARG KUBECTL_VERSION=v1.33.13
ENV GCLOUD_HOME=/opt/google-cloud-sdk
ENV PATH="${GCLOUD_HOME}/bin/:${PATH}"
ENV CLOUDSDK_PYTHON=python3.11
ENV CLOUDSDK_PYTHON_SITEPACKAGES=0
ENV PYTHONPATH="/home/airflow/.local/lib/python3.11/site-packages"

# Install gcloud SDK
RUN DOWNLOAD_URL="https://dl.google.com/dl/cloudsdk/channels/rapid/downloads/google-cloud-sdk-${CLOUD_SDK_VERSION}-linux-x86_64.tar.gz" \
    && TMP_DIR="$(mktemp -d)" \
    && curl -fL "${DOWNLOAD_URL}" --output "${TMP_DIR}/google-cloud-sdk.tar.gz" \
    && mkdir -p "${GCLOUD_HOME}" \
    && tar xzf "${TMP_DIR}/google-cloud-sdk.tar.gz" -C "${GCLOUD_HOME}" --strip-components=1 \
    && CLOUDSDK_PYTHON="${CLOUDSDK_PYTHON}" CLOUDSDK_PYTHON_SITEPACKAGES="${CLOUDSDK_PYTHON_SITEPACKAGES}" "${GCLOUD_HOME}/install.sh" \
       --bash-completion=false \
       --path-update=false \
       --usage-reporting=false \
       --additional-components gke-gcloud-auth-plugin \
       --quiet \
    && rm -rf "${TMP_DIR}" \
    && rm -rf "${GCLOUD_HOME}/.install/.backup/" \
    && CLOUDSDK_PYTHON="${CLOUDSDK_PYTHON}" CLOUDSDK_PYTHON_SITEPACKAGES="${CLOUDSDK_PYTHON_SITEPACKAGES}" gcloud --version

# Install kubectl standalone (current release built with patched Go) and verify its
# checksum. Replaces the gcloud-bundled multi-version kubectl flagged by CVE-2025-68121.
RUN curl -fsSL -o /usr/local/bin/kubectl \
        "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl" \
    && curl -fsSL -o /tmp/kubectl.sha256 \
        "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl.sha256" \
    && echo "$(cat /tmp/kubectl.sha256)  /usr/local/bin/kubectl" | sha256sum --check \
    && chmod +x /usr/local/bin/kubectl \
    && rm -f /tmp/kubectl.sha256 \
    && kubectl version --client

# Install Python 3.11 and dependencies
RUN set -ex && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        python3.11 \
        python3.11-dev \
        python3.11-distutils \
        python3-pip \
        git \
        lsyncd \
        libopenmpi-dev && \
    # Security: pull patched OS libs (gnutls CVE-2026-33845/42010, openssl CVE-2026-31789)
    apt-get install -y --only-upgrade libgnutls30 libssl3 openssl && \
    update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1 && \
    update-alternatives --set python3 /usr/bin/python3.11 && \
    ln -sf /usr/bin/python3.11 /usr/bin/python && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Add Regitry Credentials - Not required when using PYPI.ORG registry.
# ADD pip.conf /etc/xdg/pip/pip.conf
# Add configurations - Not required when using PYPI.ORG registry.
COPY lsyncd.conf.lua /etc/lsyncd/lsyncd.conf.lua

# Setup directories and permissions
RUN mkdir -p /etc/lsyncd /home/airflow/.local/lib/python3.11/site-packages && \
    chown -R airflow:root /etc/lsyncd && \
    chmod 644 /etc/lsyncd/lsyncd.conf.lua && \
    chown -R airflow:root /home/airflow/.local

# Copy requirements files
COPY --chown=airflow:root requirements_main.txt requirements_fastbi.txt /home/airflow/

# Create plugins directory and copy package manager plugin
COPY --chown=airflow:root plugins/package_manager /opt/airflow/plugins/package_manager

USER ${AIRFLOW_UID}

# Set pip environment variables
ENV PIP_DEFAULT_TIMEOUT=1000 \
    PYTHON_SETUPTOOLS_TIMEOUT=1000 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Stage 1 Install main packages
RUN python3 -m pip install --upgrade pip wheel && \
    python3 -m pip install --no-cache-dir \
    --compile \
    --use-pep517 \
        -r /home/airflow/requirements_main.txt && \
    pip check

# Stage 2 Install fastbi prereq packages
RUN python3 -m pip install --no-cache-dir \
        --compile \
        --use-pep517 \
        -r /home/airflow/requirements_fastbi.txt && \
    pip check