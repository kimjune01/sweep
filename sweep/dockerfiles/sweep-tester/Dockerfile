# sweep-tester: one fat image with the toolchains sweep most often
# attests against. Built locally via `sweep cache rebuild-image`.
#
# Why fat: per-language images (rust:bookworm, golang:bookworm, etc.)
# each cost ~1-2GB to pull cold the first time we attest in their
# language. With this image, pull-cost is paid once across all repos.
# Setup commands (apt-get, system libs) also bake in, so the per-attest
# `setup_cmd` becomes mostly empty.
#
# Drift escape hatch: any repo can override via
#   sweep retro set <repo> test_env docker:<specific-image>
# so a repo needing rust-nightly or go-1.21 doesn't get blocked here.

FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8

# System libs that show up in most build setup_cmds. Grouped so the
# layer caches well and apt's cache gets cleaned in the same step.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        clang \
        cmake \
        curl \
        git \
        libssl-dev \
        lld \
        ninja-build \
        pkg-config \
        ca-certificates \
        gnupg \
        bash \
        make \
        unzip \
        zip \
        xz-utils \
    && rm -rf /var/lib/apt/lists/*

# Rust via rustup so the toolchain is updateable inside the image
# without rebuilding. Stable channel by default; repos that need
# nightly override via the escape hatch.
ENV RUSTUP_HOME=/usr/local/rustup
ENV CARGO_HOME=/usr/local/cargo
ENV PATH=/usr/local/cargo/bin:$PATH
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \
        | sh -s -- -y --default-toolchain stable --no-modify-path \
    && rustup component add clippy rustfmt

# Go — official .tar.gz install. Picked 1.23 as a sane stable target;
# bump when the ecosystem moves.
ENV GO_VERSION=1.23.4
ENV PATH=/usr/local/go/bin:$PATH
RUN ARCH=$(dpkg --print-architecture) \
    && case "$ARCH" in amd64) GO_ARCH=amd64;; arm64) GO_ARCH=arm64;; *) echo "unsupported arch $ARCH" && exit 1;; esac \
    && curl -fsSL "https://go.dev/dl/go${GO_VERSION}.linux-${GO_ARCH}.tar.gz" -o /tmp/go.tgz \
    && tar -C /usr/local -xzf /tmp/go.tgz \
    && rm /tmp/go.tgz

# Python 3.12 + uv (operator's preferred package manager).
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-pip python3-venv \
    && rm -rf /var/lib/apt/lists/*
RUN curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh

# Node 20 + pnpm. Skipping corepack because `corepack prepare pnpm@latest
# --activate` is fragile (signature-verification flakes against pnpm's
# registry layout). Pinning pnpm via `npm install -g` is older but
# reliable and stays out of corepack's policy surface.
ENV NODE_VERSION=20.18.1
ENV PNPM_VERSION=9.15.0
RUN ARCH=$(dpkg --print-architecture) \
    && case "$ARCH" in amd64) NODE_ARCH=x64;; arm64) NODE_ARCH=arm64;; *) echo "unsupported arch $ARCH" && exit 1;; esac \
    && curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-${NODE_ARCH}.tar.xz" -o /tmp/node.tar.xz \
    && tar -C /usr/local --strip-components=1 -xJf /tmp/node.tar.xz \
    && rm /tmp/node.tar.xz \
    && npm install -g "pnpm@${PNPM_VERSION}" \
    && pnpm --version

# gh CLI — useful inside the container if a test_cmd ever needs it
# (rare, but reqa/respond may eventually want a ground-truth gh).
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
        | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg \
    && chmod a+r /usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
        > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update && apt-get install -y --no-install-recommends gh \
    && rm -rf /var/lib/apt/lists/*

# Working directory mirrors `_run_in_test_env`'s mount point.
WORKDIR /work

# Cache mount target. CARGO_TARGET_DIR / GOMODCACHE / GOCACHE all
# point at /cache via -e flags from `_run_in_test_env`, so build
# artifacts persist across container runs.
RUN mkdir -p /cache

CMD ["bash"]
