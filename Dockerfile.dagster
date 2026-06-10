ARG BASE_IMAGE=python:3.12-slim
FROM ${BASE_IMAGE}

ARG DAGSTER_VERSION=1.13.8

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV DAGSTER_HOME=/opt/dagster/dagster_home

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip install -U uv

RUN python -m uv pip install \
    dagster==${DAGSTER_VERSION} \
    dagster-graphql \
    dagster-webserver \
    dagster-postgres \
    dagster-k8s \
    "dagster-celery[flower,redis,kubernetes]" \
    dagster-celery-k8s

RUN mkdir -p $DAGSTER_HOME

WORKDIR $DAGSTER_HOME
