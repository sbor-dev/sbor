FROM nestybox/ubuntu-noble-docker:latest AS runtime

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
    util-linux \
    curl && \
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -y \
    nodejs \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install --no-cache-dir --break-system-packages \
    flake8 \
    pylint \
    py-spy \
    uv

RUN npm install -g --ignore-scripts @earendil-works/pi-coding-agent

WORKDIR /app

COPY ./pyproject.toml ./uv.lock ./

RUN uv sync --frozen --no-install-project

COPY ./sbor ./sbor

RUN uv sync --frozen

COPY ./agent/prompts/reviewer /opt/sbor/reviewer

ENV PATH="/app/.venv/bin:$PATH" \
    SBOR_REVIEWER_ASSETS_DIR=/opt/sbor/reviewer

# love government <3
RUN git config --system http.version HTTP/1.1


FROM runtime AS validation

COPY ./validation ./validation

COPY ./agent /root/.pi/agent

RUN useradd --create-home sbor

COPY --chown=sbor:sbor ./agent/prompts/reviewer /home/sbor/.pi/agent

COPY --chown=sbor:sbor ./agent/prompts/judge /home/sbor/.pi/judge

RUN chmod -R go-rwx /home/sbor/.pi


FROM runtime AS reviewer
