# Airflow GCP

Forked Airflow image with Google Cloud SDK and kubectl preinstalled for GCP-native Airflow deployments and Kubernetes operators.

## Overview

This image extends `apache/airflow:2.11.0-python3.11` by installing Google Cloud SDK (gcloud) and `kubectl`. It enables tasks that require GCP authentication, GCS/BigQuery interaction, and Kubernetes operations (e.g., K8s/GKE operators, sidecar sync with lsyncd).

## Docker Image

### Base Image
- **Base**: apache/airflow:2.11.0-python3.11

### Additions
- Google Cloud SDK (configurable version)
- kubectl
- Python 3.11 toolchain and essentials
- lsyncd config support

## Build

```bash
# Build the image
./build.sh

# Or manually
docker build -t airflow-gcp .
```

## Key Environment

- `CLOUD_SDK_VERSION` – gcloud SDK version (default set in Dockerfile)
- `GCLOUD_HOME` – /opt/google-cloud-sdk
- `PATH` includes gcloud and kubectl

## Usage Notes

- Authenticate via service account:
  ```bash
  gcloud auth activate-service-account --key-file /path/to/sa.json
  ```
- Configure project/region:
  ```bash
  gcloud config set project <PROJECT_ID>
  gcloud config set compute/region <REGION>
  ```
- Use Kubernetes operators or invoke `kubectl` directly from tasks

## Requirements Files

- `requirements_main.txt` – core Python dependencies installed system-wide
- `requirements_fastbi.txt` – additional Fast.BI prerequisites

## Getting Help

- **Documentation**: https://wiki.fast.bi
- **Issues**: https://github.com/fast-bi/airflow-gcp/issues
- **Email**: support@fast.bi

## License

See LICENSE (inherits Apache Airflow licensing; this repo applies its own license file for additions).
