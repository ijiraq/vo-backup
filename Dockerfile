# Build a standalone vo-backup binary for Linux x86_64.
#
# Base: AlmaLinux 8 (glibc 2.28) — compatible with RHEL 8 / ~4-year-old distros.
#
# Build:
#   docker build -t vo-backup-build .
#
# Extract binary to ./dist/:
#   mkdir -p dist
#   docker run --rm -v "$PWD/dist:/out" vo-backup-build
#
# Test on the target host:
#   ./dist/vo-backup --help

FROM almalinux:8

RUN dnf install -y \
        python3.11 \
        python3.11-pip \
        gcc \
        binutils \
    && dnf clean all

WORKDIR /build

COPY pyproject.toml README.md ./
COPY src ./src

RUN python3.11 -m pip install --upgrade pip \
    && python3.11 -m pip install --no-cache-dir . pyinstaller

RUN pyinstaller --onefile \
        --name vo-backup \
        --paths src \
        --collect-all vos \
        --collect-all cadcutils \
        --collect-submodules vo_backup \
        --copy-metadata vos \
        --copy-metadata cadcutils \
        --copy-metadata PyYAML \
        --copy-metadata click \
        --copy-metadata pathspec \
        src/vo_backup/cli.py

RUN test -x /build/dist/vo-backup

# When /out is mounted, copy the artifact there; otherwise print its location.
CMD if [ -d /out ]; then \
        cp /build/dist/vo-backup /out/vo-backup && \
        chmod +x /out/vo-backup && \
        echo "Wrote /out/vo-backup"; \
    else \
        echo "Binary: /build/dist/vo-backup"; \
        ls -lh /build/dist/vo-backup; \
    fi
