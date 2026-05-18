FROM python:3.11-slim

WORKDIR /app

RUN mkdir -p /tmp/chroma_sessions /tmp/uploads

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

EXPOSE 7860

ENV TMPDIR=/tmp

CMD ["streamlit", "run", "app.py", "--server.port=7860", "--server.address=0.0.0.0"]