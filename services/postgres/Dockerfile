FROM postgres:15-alpine

COPY init.sql /docker-entrypoint-initdb.d/01-init.sql

ENV POSTGRES_DB=aegis
ENV POSTGRES_USER=aegis
ENV POSTGRES_PASSWORD=aegis_demo_password
