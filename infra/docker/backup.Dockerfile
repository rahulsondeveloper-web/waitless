# Nightly database + media backups (optionally copied to S3).
FROM postgres:18
RUN apt-get update \
    && apt-get install -y --no-install-recommends awscli \
    && rm -rf /var/lib/apt/lists/*
COPY infra/backup/backup.sh /usr/local/bin/waitless-backup
RUN chmod +x /usr/local/bin/waitless-backup
ENTRYPOINT ["/usr/local/bin/waitless-backup"]
