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

# First stage: Google Cloud SDK
FROM google/cloud-sdk:slim AS gcloud-sdk

# Main stage
ARG AIRFLOW_VERSION
FROM apache/airflow:${AIRFLOW_VERSION:?err}-python3.11

SHELL ["/bin/bash", "-o", "pipefail", "-e", "-u", "-x", "-c"]

USER 0

# Set up Google Cloud SDK
ENV GCLOUD_HOME=/opt/google-cloud-sdk
ENV PATH="${GCLOUD_HOME}/bin/:${PATH}"

# Copy Google Cloud SDK from the first stage
COPY --from=gcloud-sdk /google-cloud-sdk ${GCLOUD_HOME}

# Install additional gcloud components
RUN gcloud components install alpha beta kubectl --quiet

# Install system dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libopenmpi-dev \
        libsasl2-dev \
        git \
        lsyncd \
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

# Install Python dependencies
COPY requirements.txt /home/airflow
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r /home/airflow/requirements.txt