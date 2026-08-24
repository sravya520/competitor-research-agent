# Start from a prebuilt Linux image that already has Python 3.11 installed --
# matching the version this project was developed against. "slim" is a
# stripped-down variant: same Python, far fewer OS extras, much smaller image.
FROM python:3.11-slim

# Where our code lives inside the container. Every command after this runs
# from here, and it's created automatically if it doesn't exist.
WORKDIR /app

# Dependencies are copied and installed BEFORE the application code, and the
# order is deliberate. Docker caches each step and reuses it when that step's
# inputs haven't changed. Dependencies change rarely; application code changes
# constantly. This way, editing app.py doesn't invalidate the install step, so
# rebuilds take seconds instead of reinstalling every package.
COPY requirements.txt .

# --no-cache-dir: pip's download cache is useless in an image that will never
# install anything again, and it would just make the image bigger.
#
# --retries/--timeout: some of these wheels are tens of megabytes, and a single
# dropped connection fails the whole build with no partial progress kept. Same
# reasoning as the retry policy in config.py -- a transient network failure is
# worth another attempt rather than surrendering the entire operation.
RUN pip install --no-cache-dir --retries 10 --timeout 120 -r requirements.txt

# Now the rest of the code. What actually gets copied is governed by
# .dockerignore -- notably NOT .env, whose keys must never be baked in.
COPY . .

# Documents which port the app listens on. This is a declaration for humans
# and tooling; it does not itself open anything.
EXPOSE 8501

# What runs when the container starts.
#
# --server.address=0.0.0.0 is not optional. Streamlit defaults to binding
# localhost, which inside a container means "reachable only from within this
# container" -- the app would start, appear healthy, and refuse every
# connection from outside. 0.0.0.0 means "accept connections on any interface".
#
# ${PORT:-8501} uses the PORT environment variable when the host provides one
# (Render and most container platforms assign a port and expect the app to
# honour it) and falls back to 8501 locally, where nothing sets it.
#
# --server.headless=true stops Streamlit trying to open a browser and prompting
# for an email on first run; there is no browser or user inside a container.
#
# The ["sh", "-c", ...] wrapper exists so ${PORT} is expanded by a shell --
# Docker does not do variable substitution in the JSON form on its own. The
# leading `exec` then REPLACES that shell with Streamlit, so Streamlit becomes
# the container's main process and receives stop signals directly. Without it,
# the shell would stay in the middle, absorb the shutdown signal, and Streamlit
# would be force-killed instead of exiting cleanly.
CMD ["sh", "-c", "exec streamlit run app.py --server.port=${PORT:-8501} --server.address=0.0.0.0 --server.headless=true"]
