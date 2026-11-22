# Campaign Ledger as a container (used on the Pi cluster; on Windows keep using start.bat).
# All campaign data lives in /data, which the cluster keeps on a saved disk.
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DND_TRACKER_DATA=/data
WORKDIR /app
COPY requirements.txt ./
# pytest is only for the test suite, not needed to run the app
RUN grep -iv '^pytest' requirements.txt > /tmp/req.txt && pip install --no-cache-dir -r /tmp/req.txt
COPY app ./app
COPY run.py ./
RUN useradd --uid 10001 --user-group --no-create-home ledger && mkdir -p /data && chown ledger:ledger /data
USER 10001
EXPOSE 5050
CMD ["python", "run.py", "--lan", "--no-browser", "--port", "5050"]
