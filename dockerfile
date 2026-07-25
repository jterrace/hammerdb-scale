# HammerDB Scale - Base Image
# Supports: SQL Server, PostgreSQL, MySQL (Oracle requires extension image)
#
# This is the public base image containing HammerDB and open-source database
# drivers. For Oracle support, build the extension image using Dockerfile.oracle
#
# BUILD:
#   docker build -t sillidata/hammerdb-scale:latest .
#
# To build a different HammerDB version:
#   docker build --build-arg HAMMERDB_VERSION=5.0 -t sillidata/hammerdb-scale:5.0 .
#
# ORACLE USERS:
#   docker build -f Dockerfile.oracle -t myregistry/hammerdb-scale-oracle:latest .

FROM ubuntu:24.04

# The HammerDB version is defined once here and flows into the install path,
# HAMMERDB_HOME and the image label. entrypoint.sh reads HAMMERDB_HOME rather
# than hardcoding a path, so a version bump is this one argument.
ARG HAMMERDB_VERSION=6.0

LABEL maintainer="hammerdb-scale"
LABEL description="HammerDB Scale Test Runner - Multi-Database Performance Testing"
LABEL hammerdb.version="${HAMMERDB_VERSION}"
LABEL database.support="mssql,postgresql,mysql (oracle via extension)"

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
