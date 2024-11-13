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
ARG BASE_AIRFLOW_IMAGE=apache/airflow:2.10.3-python3.11
ARG AIRFLOW_VERSION
FROM ${BASE_AIRFLOW_IMAGE}

SHELL ["/bin/bash", "-o", "pipefail", "-e", "-u", "-x", "-c"]

USER 0

ARG CLOUD_SDK_VERSION=501.0.0
ENV GCLOUD_HOME=/opt/google-cloud-sdk

ENV PATH="${GCLOUD_HOME}/bin/:${PATH}"

RUN DOWNLOAD_URL="https://dl.google.com/dl/cloudsdk/channels/rapid/downloads/google-cloud-sdk-${CLOUD_SDK_VERSION}-linux-x86_64.tar.gz" \
    && TMP_DIR="$(mktemp -d)" \
    && curl -fL "${DOWNLOAD_URL}" --output "${TMP_DIR}/google-cloud-sdk.tar.gz" \
    && mkdir -p "${GCLOUD_HOME}" \
    && tar xzf "${TMP_DIR}/google-cloud-sdk.tar.gz" -C "${GCLOUD_HOME}" --strip-components=1 \
    && "${GCLOUD_HOME}/install.sh" \
       --bash-completion=false \
       --path-update=false \
       --usage-reporting=false \
       --additional-components alpha beta kubectl \
       --quiet \
    && rm -rf "${TMP_DIR}" \
    && rm -rf "${GCLOUD_HOME}/.install/.backup/" \
    && gcloud --version

RUN apt-get update \
  && apt-get install -y --no-install-recommends \
         build-essential libopenmpi-dev libsasl2-dev git lsyncd \
  && apt-get autoremove -yqq --purge \
  && apt-get clean \
  && rm -rf /var/lib/apt/lists/*

# Add fast-bi-dbt-runner config
ADD pip.conf /etc/xdg/pip/pip.conf

# Add lsyncd config
COPY lsyncd.conf.lua /etc/lsyncd/lsyncd.conf.lua

# Make sure the config directory has right permissions
RUN mkdir -p /etc/lsyncd && \
    chown -R airflow:root /etc/lsyncd && \
    chmod 644 /etc/lsyncd/lsyncd.conf.lua

USER ${AIRFLOW_UID}

COPY requirements.txt /home/airflow

RUN pip install --no-cache-dir -r /home/airflow/requirements.txt

RUN pip install --upgrade pip
