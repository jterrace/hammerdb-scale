# HammerDB Scale - Base Image
#
# Verified working: SQL Server and PostgreSQL.
# Oracle needs the extension image (Dockerfile.oracle) because Oracle Instant
# Client cannot be redistributed.
#
# ARCHITECTURE: x86_64. HammerDB 6.0 does publish ARM64 tarballs and this image
# would build for ARM, but the Oracle extension cannot (Instant Client is
# x86_64-only), so the pair is kept uniformly x86_64 to avoid shipping a base
# image that works on ARM alongside an Oracle image that does not.
#
# BUILD:
#   docker build -t sillidata/hammerdb-scale:6.0 .
#
# To build a different HammerDB version:
#   docker build --build-arg HAMMERDB_VERSION=5.0 -t sillidata/hammerdb-scale:5.0 .
#
# Prefer hack/build-images.sh, which builds this and the Oracle
# image in the right order and verifies both.

FROM ubuntu:24.04

# The HammerDB version is defined once here and flows into the install path,
# HAMMERDB_HOME and the image label. entrypoint.sh reads HAMMERDB_HOME rather
# than hardcoding a path, so a version bump is this one argument.
ARG HAMMERDB_VERSION=6.0

# Provenance. Populated by the release script; harmless when built by hand.
ARG VCS_REF=unknown
ARG BUILD_DATE=unknown
ARG IMAGE_VERSION=dev

LABEL maintainer="hammerdb-scale"
LABEL description="HammerDB Scale Test Runner - Multi-Database Performance Testing"
LABEL hammerdb.version="${HAMMERDB_VERSION}"
LABEL database.support="mssql,postgresql (oracle via extension image)"
LABEL org.opencontainers.image.title="hammerdb-scale"
LABEL org.opencontainers.image.description="HammerDB Scale Test Runner - Multi-Database Performance Testing"
LABEL org.opencontainers.image.source="https://github.com/PureStorage-OpenConnect/hammerdb-scale"
LABEL org.opencontainers.image.licenses="Apache-2.0"
LABEL org.opencontainers.image.version="${IMAGE_VERSION}"
LABEL org.opencontainers.image.revision="${VCS_REF}"
LABEL org.opencontainers.image.created="${BUILD_DATE}"

# Set environment variables
ENV DEBIAN_FRONTEND=noninteractive
ENV HAMMERDB_HOME=/opt/HammerDB-${HAMMERDB_VERSION}

# Install base packages and SQL Server drivers (Microsoft - permissive license)
RUN apt-get update && \
    apt-get install -y \
        apt-transport-https \
        curl \
        gnupg2 \
        wget \
        python3 \
        python3-pip \
        vim && \
    # Add Microsoft repository for SQL Server tools
    curl -sSL -O https://packages.microsoft.com/config/ubuntu/24.04/packages-microsoft-prod.deb && \
    dpkg -i packages-microsoft-prod.deb && \
    rm packages-microsoft-prod.deb && \
    apt-get update && \
    ACCEPT_EULA=Y apt-get install -y mssql-tools18 msodbcsql18 unixodbc unixodbc-dev && \
    # HammerDB bundles Pgtcl but links against the system libpq at runtime;
    # without libpq5 the PostgreSQL driver fails with
    # "Failed to load Pgtcl - libpq.so.5: cannot open shared object file".
    # postgresql-client provides psql for diagnostics.
    apt-get install -y libpq5 postgresql-client && \
    echo 'export PATH="$PATH:/opt/mssql-tools18/bin"' >> ~/.bashrc && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /var/apt/cache/* /tmp/* /var/tmp/*

# Install Python dependencies for Pure Storage metrics collection
RUN python3 -m pip install --no-cache-dir --break-system-packages requests urllib3

# Install HammerDB
WORKDIR /opt
RUN wget "https://github.com/TPC-Council/HammerDB/releases/download/v${HAMMERDB_VERSION}/HammerDB-${HAMMERDB_VERSION}-Prod-Lin-UBU24.tar.gz" && \
    tar -xzf "HammerDB-${HAMMERDB_VERSION}-Prod-Lin-UBU24.tar.gz" && \
    rm "HammerDB-${HAMMERDB_VERSION}-Prod-Lin-UBU24.tar.gz" && \
    echo 'export LD_LIBRARY_PATH=/usr/lib/x86_64-linux-gnu/:$LD_LIBRARY_PATH' >> ~/.bashrc

# Configure HammerDB
RUN chmod +x "${HAMMERDB_HOME}/hammerdbcli" && \
    ln -sf /opt/mssql-tools18/bin/bcp "${HAMMERDB_HOME}/bcp" && \
    ln -sf /opt/mssql-tools18/bin/bcp /usr/local/bin/bcp

# Add entrypoint script
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Add Pure Storage metrics collection script
COPY scripts/collect_pure_metrics.py ${HAMMERDB_HOME}/scripts/collect_pure_metrics.py
RUN chmod +x "${HAMMERDB_HOME}/scripts/collect_pure_metrics.py"

WORKDIR ${HAMMERDB_HOME}

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
