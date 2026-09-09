FROM nestybox/ubuntu-noble-docker:latest

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    clang \
    clang-format \
    clang-tidy \
    clang-tools \
    libclang-dev \
    llvm-dev \
    python3-clang \
    valgrind \
    libunwind-dev \
    python3 \
    python3-pip \
    python3-venv \
    curl && \
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -y \
    nodejs \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install --no-cache-dir --break-system-packages \
    flake8 \
    pylint \
    py-spy

RUN npm install -g --ignore-scripts @earendil-works/pi-coding-agent

COPY ./agent /root/.pi/agent

CMD ["/bin/bash"]
