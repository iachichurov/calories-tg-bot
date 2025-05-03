# Используем официальный образ Python 3.11 (slim-версия для меньшего размера)
# Ты можешь выбрать другую версию, если необходимо, но убедись, что она >= 3.10
FROM python:3.12-slim

# Устанавливаем рабочую директорию внутри контейнера
WORKDIR /app

# --- ИЗМЕНЕНО: Устанавливаем curl и tzdata ---
# Обновляем список пакетов
# Устанавливаем curl (для отладки сети) и tzdata (данные часовых поясов)
# -y - автоматически отвечать "да"
# --no-install-recommends - не ставить лишние пакеты
# && apt-get clean - очищаем кеш apt
# && rm -rf /var/lib/apt/lists/* - удаляем списки пакетов для уменьшения размера
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl tzdata && \
    apt-get clean && \
    ln -fs /usr/share/zoneinfo/UTC /etc/localtime && \
    dpkg-reconfigure -f noninteractive tzdata && \
    rm -rf /var/lib/apt/lists/*
ENV TZ=UTC

# Копируем файл с зависимостями
COPY requirements.txt .

# Устанавливаем Python-зависимости
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Копируем код приложения
# Убедись, что .dockerignore настроен правильно
COPY . .

# Команда для запуска бота
CMD ["python", "main.py"]
