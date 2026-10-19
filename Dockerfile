FROM python:3.12-slim

WORKDIR /code

# Dependencies first: if only the code changes, Docker reuses this layer and the build takes seconds.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# A single uvicorn process on purpose: MemorySaver keeps conversations in this process's RAM.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
