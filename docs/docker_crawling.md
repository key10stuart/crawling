# Docker Crawling

This repo can be run in Docker for reproducible, headless crawling. The Docker
image uses a Playwright base image so JS rendering works out of the box.

## Quick Start (Headless)

Build:
```bash
docker build -t crawler .
```

Run a single domain:
```bash
docker run --rm \
  -v "$(pwd)/corpus:/app/corpus" \
  -v "$(pwd)/seeds:/app/seeds" \
  -v "$(pwd)/profiles:/app/profiles" \
  -v "$(pwd)/configs:/app/configs" \
  crawler --domain schneider.com --js-auto
```

Run tier 1:
```bash
docker run --rm \
  -v "$(pwd)/corpus:/app/corpus" \
  -v "$(pwd)/seeds:/app/seeds" \
  -v "$(pwd)/profiles:/app/profiles" \
  -v "$(pwd)/configs:/app/configs" \
  crawler --tier 1 -j 4 --js-auto
```

## docker-compose

Default compose runs `--help` so you can override args:
```bash
docker compose run --rm crawl --domain jbhunt.com --js-auto
```

## Notes

- Headed browser mode (`--no-headless`) is not supported by default in Docker.
-  To use it, run the Xvfb image and pass `--no-headless`.
- Outputs are stored in `corpus/` on the host via volume mounts.
- If you want a lighter image, consider trimming `requirements.txt`.

## Optional Xvfb (Headed)

Build:
```bash
docker build -f Dockerfile.xvfb -t crawler-xvfb .
```

Run with visible browser mode (rendered to Xvfb):
```bash
docker run --rm \
  -v "$(pwd)/corpus:/app/corpus" \
  -v "$(pwd)/seeds:/app/seeds" \
  -v "$(pwd)/profiles:/app/profiles" \
  -v "$(pwd)/configs:/app/configs" \
  crawler-xvfb --domain knight-swift.com --no-headless
```

Compose:
```bash
docker compose run --rm crawl-xvfb --domain knight-swift.com --no-headless
```
