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
ARG BASE_AIRFLOW_IMAGE=apache/airflow:2.11.0-python3.11
ARG AIRFLOW_VERSION
FROM ${BASE_AIRFLOW_IMAGE}
LABEL maintainer=support@fast.bi

SHELL ["/bin/bash", "-o", "pipefail", "-e", "-u", "-x", "-c"]

USER 0

ARG CLOUD_SDK_VERSION=536.0.0
ENV GCLOUD_HOME=/opt/google-cloud-sdk
ENV PATH="${GCLOUD_HOME}/bin/:${PATH}"
ENV PYTHONPATH="/home/airflow/.local/lib/python3.11/site-packages"

# Install gcloud SDK
RUN DOWNLOAD_URL="https://dl.google.com/dl/cloudsdk/channels/rapid/downloads/google-cloud-sdk-${CLOUD_SDK_VERSION}-linux-x86_64.tar.gz" \
    && TMP_DIR="$(mktemp -d)" \
    && curl -fL "${DOWNLOAD_URL}" --output "${TMP_DIR}/google-cloud-sdk.tar.gz" \
    && mkdir -p "${GCLOUD_HOME}" \
    && tar xzf "${TMP_DIR}/google-cloud-sdk.tar.gz" -C "${GCLOUD_HOME}" --strip-components=1 \
    && "${GCLOUD_HOME}/install.sh" \
       --bash-completion=false \
       --path-update=false \
       --usage-reporting=false \
       --additional-components kubectl \
       --quiet \
    && rm -rf "${TMP_DIR}" \
    && rm -rf "${GCLOUD_HOME}/.install/.backup/" \
    && gcloud --version

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