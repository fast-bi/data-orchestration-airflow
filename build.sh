#!/bin/bash
#

set -o errexit
catch() {
    echo 'catching!'
    if [ "$1" != "0" ]; then
    # error handling goes here
    echo "Error $1 occurred on $2"
    fi
}
trap 'catch $? $LINENO' EXIT

airflow_version="2.10.2-python3.11"
airflow_version_short=$(echo $airflow_version | cut -d '-' -f 1)

# docker build . \
#   --pull \
#   --build-arg BASE_AIRFLOW_IMAGE="apache/airflow:${airflow_version}" --build-arg AIRFLOW_VERSION="${airflow_version}" \
#   --tag europe-central2-docker.pkg.dev/fast-bi-common/airflow/airflow-gcp:${airflow_version}

# docker push europe-central2-docker.pkg.dev/fast-bi-common/airflow/airflow-gcp:${airflow_version}

docker buildx build . \
  --pull \
  --build-arg BASE_AIRFLOW_IMAGE="apache/airflow:${airflow_version}" --build-arg AIRFLOW_VERSION="${airflow_version}" \
  --tag europe-central2-docker.pkg.dev/fast-bi-common/airflow/airflow-gcp:${airflow_version_short} \
  --platform linux/amd64 \
  --push

##
##pip install --index-url https://europe-central2-python.pkg.dev/fast-bi-common/bi-platform-pypi-packages/simple/ fast-bi-dbt-runner==0.0.1

