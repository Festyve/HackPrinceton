FROM python:3.13-slim
WORKDIR /app
COPY runtime.py /app/runtime.py
USER 10001:10001
ENTRYPOINT ["python", "/app/runtime.py"]
